// Shared headless Chrome DevTools (CDP) driver and hardened local static server.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

export const DEFAULT_CHROME_BIN = process.env.CHROME_BIN || "/usr/bin/google-chrome";
export const DEFAULT_CHROME_STARTUP_TIMEOUT_MS = (() => {
  const raw = process.env.CHROME_STARTUP_TIMEOUT_MS;
  if (!raw) {
    return 15000;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 15000;
})();

const MIME_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"],
  [".mjs", "application/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

/**
 * Send a raw HTTP GET request without client-side URL path normalization (for traversal tests).
 */
export function rawHttpGet(baseUrl, rawPath) {
  const parsed = new URL(baseUrl);
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: parsed.hostname,
        port: Number(parsed.port),
        method: "GET",
        path: rawPath,
      },
      (res) => {
        res.resume();
        res.on("end", () => resolve({ status: res.statusCode ?? 0 }));
      },
    );
    req.on("error", reject);
    req.end();
  });
}

function writeTextResponse(res, status, message) {
  res.writeHead(status, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(message);
}

/**
 * Start an ephemeral 127.0.0.1 HTTP server that refuses traversal, symlinks, and non-regular files.
 */
export function startStaticServer(rootDir) {
  const resolvedRoot = fs.realpathSync(rootDir);

  const server = http.createServer((req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      writeTextResponse(res, 405, "Method Not Allowed");
      return;
    }

    const rawTarget = (req.url ?? "/").split(/[?#]/, 1)[0];
    let pathname;
    try {
      pathname = decodeURIComponent(rawTarget);
    } catch {
      writeTextResponse(res, 400, "Bad Request");
      return;
    }

    if (pathname.includes("\0") || !pathname.startsWith("/")) {
      writeTextResponse(res, 400, "Bad Request");
      return;
    }

    if (
      pathname.includes("\\") ||
      pathname.split("/").some((segment) => segment === ".." || segment === ".")
    ) {
      writeTextResponse(res, 403, "Forbidden");
      return;
    }

    if (pathname === "/favicon.ico") {
      const faviconPath = path.join(resolvedRoot, "favicon.ico");
      if (!fs.existsSync(faviconPath)) {
        res.writeHead(204);
        res.end();
        return;
      }
    }

    const relativePath = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
    const candidatePath = path.resolve(resolvedRoot, relativePath);
    if (
      candidatePath !== resolvedRoot &&
      !candidatePath.startsWith(resolvedRoot + path.sep)
    ) {
      writeTextResponse(res, 403, "Forbidden");
      return;
    }

    const segments = relativePath.split("/").filter(Boolean);
    let current = resolvedRoot;
    for (const segment of segments) {
      current = path.join(current, segment);
      let segStat;
      try {
        segStat = fs.lstatSync(current);
      } catch {
        writeTextResponse(res, 404, "Not Found");
        return;
      }
      if (segStat.isSymbolicLink()) {
        writeTextResponse(res, 403, "Forbidden");
        return;
      }
    }

    let stat;
    let realCandidate;
    try {
      stat = fs.lstatSync(candidatePath);
      realCandidate = fs.realpathSync(candidatePath);
    } catch {
      writeTextResponse(res, 404, "Not Found");
      return;
    }

    if (
      stat.isSymbolicLink() ||
      !stat.isFile() ||
      !realCandidate.startsWith(resolvedRoot + path.sep)
    ) {
      writeTextResponse(res, 403, "Forbidden");
      return;
    }

    const ext = path.extname(realCandidate).toLowerCase();
    const contentType = MIME_TYPES.get(ext) || "application/octet-stream";
    const body = fs.readFileSync(realCandidate);
    res.writeHead(200, {
      "Content-Type": contentType,
      "Content-Length": String(body.length),
      "Cache-Control": "no-store",
    });
    if (req.method === "HEAD") {
      res.end();
    } else {
      res.end(body);
    }
  });

  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Failed to bind static server port"));
        return;
      }
      resolve({
        server,
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () =>
          new Promise((resolveClose) => {
            server.closeAllConnections?.();
            server.close(() => resolveClose());
          }),
      });
    });
  });
}

export class CdpClient {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = new Map();
    this.activeWaiters = new Set();
    this.closed = false;

    ws.addEventListener("message", (event) => {
      const payload = JSON.parse(String(event.data));
      if (typeof payload.id === "number") {
        const entry = this.pending.get(payload.id);
        if (!entry) {
          return;
        }
        this.pending.delete(payload.id);
        clearTimeout(entry.timer);
        if (payload.error) {
          entry.reject(
            new Error(`CDP error (${entry.method}): ${payload.error.message || JSON.stringify(payload.error)}`),
          );
        } else {
          entry.resolve(payload.result ?? {});
        }
        return;
      }

      if (payload.method) {
        const handlers = this.eventHandlers.get(payload.method);
        if (handlers) {
          for (const handler of [...handlers]) {
            handler(payload.params ?? {}, payload.sessionId);
          }
        }
      }
    });

    ws.addEventListener("close", () => {
      this.closed = true;
      for (const [id, entry] of this.pending.entries()) {
        clearTimeout(entry.timer);
        entry.reject(new Error(`CDP connection closed while waiting for ${entry.method} (#${id})`));
      }
      this.pending.clear();
      for (const rejectWaiter of [...this.activeWaiters]) {
        rejectWaiter(new Error("CDP WebSocket connection closed"));
      }
      this.activeWaiters.clear();
    });
  }

  static async connect(wsUrl, timeoutMs = 10000) {
    const ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        try {
          ws.close();
        } catch {
          // Ignore close errors on timed-out socket.
        }
        reject(new Error(`Timed out connecting to Chrome WebSocket: ${wsUrl}`));
      }, timeoutMs);

      ws.addEventListener(
        "open",
        () => {
          if (settled) {
            return;
          }
          settled = true;
          clearTimeout(timer);
          resolve();
        },
        { once: true },
      );

      ws.addEventListener(
        "error",
        (err) => {
          if (settled) {
            return;
          }
          settled = true;
          clearTimeout(timer);
          try {
            ws.close();
          } catch {
            // Ignore close errors.
          }
          reject(new Error(`WebSocket connection failed: ${err.message || "unknown error"}`));
        },
        { once: true },
      );
    });
    return new CdpClient(ws);
  }

  on(method, handler) {
    let handlers = this.eventHandlers.get(method);
    if (!handlers) {
      handlers = new Set();
      this.eventHandlers.set(method, handlers);
    }
    handlers.add(handler);
    return () => {
      handlers.delete(handler);
    };
  }

  _createEventWaiter(method, predicate = () => true, timeoutMs = 15000) {
    let timer = null;
    let off = () => {};
    let settled = false;
    let abortWaiter = () => {};

    const cleanup = () => {
      clearTimeout(timer);
      off();
      this.activeWaiters.delete(abortWaiter);
    };

    const promise = new Promise((resolve, reject) => {
      if (this.closed) {
        reject(new Error(`Cannot wait for ${method}: CDP WebSocket is closed`));
        return;
      }
      abortWaiter = (err) => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        reject(err);
      };
      this.activeWaiters.add(abortWaiter);

      timer = setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        reject(new Error(`Timed out waiting for CDP event ${method}`));
      }, timeoutMs);

      off = this.on(method, (params, sessionId) => {
        if (!settled && predicate(params, sessionId)) {
          settled = true;
          cleanup();
          resolve({ params, sessionId });
        }
      });
    });

    const cancel = () => {
      if (!settled) {
        settled = true;
        cleanup();
      }
    };

    return { promise, cancel };
  }

  waitForEvent(method, predicate = () => true, timeoutMs = 15000) {
    return this._createEventWaiter(method, predicate, timeoutMs).promise;
  }

  send(method, params = {}, sessionId = undefined, timeoutMs = 15000) {
    if (this.closed) {
      return Promise.reject(new Error(`Cannot send ${method}: CDP WebSocket is closed`));
    }
    const id = this.nextId;
    this.nextId += 1;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Timed out waiting for CDP response to ${method}`));
      }, timeoutMs);
      this.pending.set(id, { method, resolve, reject, timer });
      const message = sessionId ? { id, method, params, sessionId } : { id, method, params };
      this.ws.send(JSON.stringify(message));
    });
  }

  async createSession() {
    const { targetId } = await this.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await this.send("Target.attachToTarget", {
      targetId,
      flatten: true,
    });
    await this.send("Page.enable", {}, sessionId);
    await this.send("Page.bringToFront", {}, sessionId);
    await this.send("Runtime.enable", {}, sessionId);
    await this.send("Log.enable", {}, sessionId);
    return { targetId, sessionId };
  }

  async evaluate(sessionId, expression) {
    const response = await this.send(
      "Runtime.evaluate",
      {
        expression,
        awaitPromise: true,
        returnByValue: true,
      },
      sessionId,
    );
    if (response.exceptionDetails) {
      const details = response.exceptionDetails;
      const description =
        details.exception?.description || details.text || "Unknown evaluation exception";
      throw new Error(`Browser script exception: ${description}`);
    }
    return response.result?.value;
  }

  async waitUntil(sessionId, predicateExpr, description, timeoutMs = 10000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const ready = await this.evaluate(sessionId, `Boolean(${predicateExpr})`);
      if (ready) {
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error(`Timed out waiting for: ${description}`);
  }

  async navigate(sessionId, url) {
    const loadWaiter = this._createEventWaiter(
      "Page.loadEventFired",
      (_params, eventSessionId) => eventSessionId === sessionId,
      15000,
    );
    try {
      const navResult = await this.send("Page.navigate", { url }, sessionId);
      if (navResult.errorText) {
        throw new Error(`Navigation to ${url} failed: ${navResult.errorText}`);
      }
      await loadWaiter.promise;
    } finally {
      loadWaiter.cancel();
    }
    await this.waitUntil(sessionId, 'document.readyState === "complete"', `${url} readyState`);
  }

  async setViewport(sessionId, viewport) {
    await this.send(
      "Emulation.setDeviceMetricsOverride",
      {
        width: viewport.width,
        height: viewport.height,
        deviceScaleFactor: 1,
        mobile: viewport.mobile,
      },
      sessionId,
    );
    await this.evaluate(
      sessionId,
      "new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))",
    );
  }

  close() {
    try {
      this.ws.close();
    } catch {
      // Ignore close errors during cleanup.
    }
  }
}

export async function launchChrome(
  userDataDir,
  { onSpawn, startupTimeoutMs = DEFAULT_CHROME_STARTUP_TIMEOUT_MS } = {},
) {
  const args = [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--remote-debugging-port=0",
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank",
  ];

  const proc = spawn(DEFAULT_CHROME_BIN, args, {
    stdio: ["ignore", "pipe", "pipe"],
  });
  onSpawn?.(proc);

  const stderrChunks = [];
  const wsUrl = await new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;

    const cleanupListeners = () => {
      proc.stderr.off("data", onOutput);
      proc.stdout.off("data", onOutput);
      proc.off("error", onError);
      proc.off("exit", onExit);
    };

    const onOutput = (chunk) => {
      const text = chunk.toString("utf8");
      stderrChunks.push(text);
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(stderrChunks.join(""));
      if (match && !settled) {
        settled = true;
        clearTimeout(timer);
        cleanupListeners();
        resolve(match[1]);
      }
    };

    const onError = (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        cleanupListeners();
        reject(new Error(`Failed to launch ${DEFAULT_CHROME_BIN}: ${err.message}`));
      }
    };

    const onExit = (code, signal) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        cleanupListeners();
        reject(
          new Error(
            `Chrome exited before DevTools started (code=${code}, signal=${signal}). Stderr:\n${stderrChunks.join("")}`,
          ),
        );
      }
    };

    timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        cleanupListeners();
        terminateChrome(proc, null).finally(() => {
          reject(
            new Error(
              `Timed out waiting for headless Chrome DevTools URL. Stderr:\n${stderrChunks.join("")}`,
            ),
          );
        });
      }
    }, startupTimeoutMs);

    proc.stderr.on("data", onOutput);
    proc.stdout.on("data", onOutput);
    proc.once("error", onError);
    proc.once("exit", onExit);
  });

  return { proc, wsUrl };
}

export async function terminateChrome(proc, cdp) {
  if (cdp) {
    try {
      await cdp.send("Browser.close", {}, undefined, 1500);
    } catch {
      // Fallback to signal termination below.
    }
    cdp.close();
  }

  if (!proc || proc.exitCode !== null || proc.signalCode !== null) {
    return;
  }

  const waitForExit = (timeoutMs) =>
    new Promise((resolve) => {
      if (proc.exitCode !== null || proc.signalCode !== null) {
        resolve(true);
        return;
      }
      const timer = setTimeout(() => {
        proc.removeListener("exit", onExit);
        resolve(false);
      }, timeoutMs);
      const onExit = () => {
        clearTimeout(timer);
        resolve(true);
      };
      proc.once("exit", onExit);
    });

  if (cdp && (await waitForExit(1500))) {
    return;
  }
  try {
    proc.kill("SIGTERM");
  } catch {
    return;
  }
  if (await waitForExit(2000)) {
    return;
  }
  try {
    proc.kill("SIGKILL");
  } catch {
    return;
  }
  await waitForExit(2000);
}

export function attachErrorCollectors(cdp, sessionId) {
  const errors = [];
  const logErrors = [];

  const offException = cdp.on("Runtime.exceptionThrown", (params, eventSessionId) => {
    if (eventSessionId !== sessionId) {
      return;
    }
    const details = params.exceptionDetails;
    const text = details?.exception?.description || details?.text || "Uncaught pageerror";
    errors.push(`pageerror: ${text}`);
  });

  const offConsole = cdp.on("Runtime.consoleAPICalled", (params, eventSessionId) => {
    if (eventSessionId !== sessionId || params.type !== "error") {
      return;
    }
    const args = (params.args || []).map((a) => a.value ?? a.description ?? "").join(" ");
    errors.push(`console.error: ${args}`);
  });

  const offLog = cdp.on("Log.entryAdded", (params, eventSessionId) => {
    if (eventSessionId !== sessionId) {
      return;
    }
    const entry = params.entry;
    if (entry?.level === "error") {
      logErrors.push(`browser log error (${entry.source || "unknown"}): ${entry.text || ""}`);
    }
  });

  return {
    errors,
    logErrors,
    reset: () => {
      errors.length = 0;
      logErrors.length = 0;
    },
    assertClean: (context, { allowNetwork404 = false } = {}) => {
      const unexpectedLogErrors = allowNetwork404
        ? logErrors.filter((msg) => !msg.includes("status of 404"))
        : logErrors;
      const combined = [...errors, ...unexpectedLogErrors];
      assert.deepEqual(
        combined,
        [],
        `Unexpected browser errors during ${context}:\n${combined.join("\n")}`,
      );
    },
    dispose: () => {
      offException();
      offConsole();
      offLog();
    },
  };
}

/**
 * Manage idempotent async cleanup and SIGINT/SIGTERM shutdown for Chrome, servers, and temp dirs.
 */
export function createShutdownManager() {
  const tasks = [];
  let cleanupPromise = null;

  const add = (fn) => {
    tasks.push(fn);
  };

  const cleanup = () => {
    if (!cleanupPromise) {
      cleanupPromise = (async () => {
        for (const fn of [...tasks].reverse()) {
          try {
            await fn();
          } catch {
            // Continue cleaning remaining resources on failure.
          }
        }
      })();
    }
    return cleanupPromise;
  };

  const registerSignals = () => {
    let signaled = false;
    const handlers = new Map();
    for (const signal of ["SIGINT", "SIGTERM"]) {
      const handler = () => {
        if (signaled) {
          return;
        }
        signaled = true;
        cleanup().finally(() => {
          process.exit(signal === "SIGINT" ? 130 : 143);
        });
      };
      handlers.set(signal, handler);
      process.on(signal, handler);
    }
    return () => {
      for (const [signal, handler] of handlers.entries()) {
        process.off(signal, handler);
      }
    };
  };

  return { add, cleanup, registerSignals };
}
