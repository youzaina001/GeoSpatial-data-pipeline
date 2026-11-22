#!/usr/bin/env node
// Headless Chrome DevTools verification for the geocrawl static comparison explorer.

import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_CHROME_BIN = process.env.CHROME_BIN || "/usr/bin/google-chrome";
const DEFAULT_CHROME_STARTUP_TIMEOUT_MS = (() => {
  const raw = process.env.CHROME_STARTUP_TIMEOUT_MS;
  if (!raw) {
    return 15000;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 15000;
})();
const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900, mobile: false },
  { name: "mobile-390", width: 390, height: 844, mobile: true },
  { name: "narrow-320", width: 320, height: 720, mobile: true },
];

const MIME_TYPES = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"],
  [".mjs", "application/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

function parseArgs(argv) {
  let siteDir = null;
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--site-dir") {
      if (i + 1 >= argv.length) {
        throw new Error("--site-dir requires a directory argument");
      }
      siteDir = path.resolve(argv[i + 1]);
      i += 1;
    } else if (arg.startsWith("--site-dir=")) {
      const value = arg.slice("--site-dir=".length);
      if (!value) {
        throw new Error("--site-dir requires a non-empty directory argument");
      }
      siteDir = path.resolve(value);
    } else if (arg === "--help" || arg === "-h") {
      console.log("Usage: node tests/browser_check.mjs [--site-dir <path>]");
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return { siteDir };
}

function buildPromotedDemoSite(tmpRoot) {
  const demoDir = path.join(tmpRoot, "demo");
  const siteDir = path.join(tmpRoot, "site");
  execFileSync("uv", ["run", "geocrawl", "demo", "--output-dir", demoDir], {
    cwd: REPO_ROOT,
    stdio: "pipe",
  });

  const runsDir = path.join(demoDir, "cloudflare-ai-crawl-control", "runs");
  const runs = fs
    .readdirSync(runsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.ok(runs.length > 0, `Expected at least one demo run under ${runsDir}`);

  const latestRun = path.join(runsDir, runs[runs.length - 1]);
  execFileSync(
    "uv",
    ["run", "geocrawl", "promote", latestRun, "--publish-dir", siteDir, "--yes"],
    {
      cwd: REPO_ROOT,
      stdio: "pipe",
    },
  );
  return siteDir;
}

function copyExplorerAssets(srcDir, dstDir) {
  fs.mkdirSync(dstDir, { recursive: true });
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) {
      continue;
    }
    const srcPath = path.join(srcDir, entry.name);
    const dstPath = path.join(dstDir, entry.name);
    if (entry.isDirectory()) {
      copyExplorerAssets(srcPath, dstPath);
    } else if (entry.isFile()) {
      fs.copyFileSync(srcPath, dstPath);
    }
  }
}

function startStaticServer(rootDir) {
  const resolvedRoot = fs.realpathSync(rootDir);

  const server = http.createServer((req, res) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Method Not Allowed");
      return;
    }

    let pathname;
    try {
      const parsed = new URL(req.url ?? "/", "http://127.0.0.1");
      pathname = decodeURIComponent(parsed.pathname);
    } catch {
      res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Bad Request");
      return;
    }

    if (pathname.includes("\0")) {
      res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Bad Request");
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
      res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Forbidden");
      return;
    }

    let stat;
    try {
      stat = fs.lstatSync(candidatePath);
    } catch {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Not Found");
      return;
    }

    if (stat.isSymbolicLink() || !stat.isFile()) {
      res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      res.end("Forbidden");
      return;
    }

    const ext = path.extname(candidatePath).toLowerCase();
    const contentType = MIME_TYPES.get(ext) || "application/octet-stream";
    const body = fs.readFileSync(candidatePath);
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

class CdpClient {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = new Map();
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
    });
  }

  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`Timed out connecting to Chrome WebSocket: ${wsUrl}`));
      }, 10000);
      ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      ws.addEventListener("error", (err) => {
        clearTimeout(timer);
        reject(new Error(`WebSocket connection failed: ${err.message || "unknown error"}`));
      }, { once: true });
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

  waitForEvent(method, predicate = () => true, timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        off();
        reject(new Error(`Timed out waiting for CDP event ${method}`));
      }, timeoutMs);
      const off = this.on(method, (params, sessionId) => {
        if (predicate(params, sessionId)) {
          clearTimeout(timer);
          off();
          resolve({ params, sessionId });
        }
      });
    });
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
    const loadPromise = this.waitForEvent(
      "Page.loadEventFired",
      (_params, eventSessionId) => eventSessionId === sessionId,
      15000,
    );
    const navResult = await this.send("Page.navigate", { url }, sessionId);
    if (navResult.errorText) {
      throw new Error(`Navigation to ${url} failed: ${navResult.errorText}`);
    }
    await loadPromise;
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

async function launchChrome(
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
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        terminateChrome(proc, null).finally(() => {
          reject(
            new Error(
              `Timed out waiting for headless Chrome DevTools URL. Stderr:\n${stderrChunks.join("")}`,
            ),
          );
        });
      }
    }, startupTimeoutMs);

    const onOutput = (chunk) => {
      const text = chunk.toString("utf8");
      stderrChunks.push(text);
      const match = /DevTools listening on (ws:\/\/\S+)/.exec(stderrChunks.join(""));
      if (match && !settled) {
        settled = true;
        clearTimeout(timer);
        resolve(match[1]);
      }
    };

    proc.stderr.on("data", onOutput);
    proc.stdout.on("data", onOutput);
    proc.once("error", (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Failed to launch ${DEFAULT_CHROME_BIN}: ${err.message}`));
      }
    });
    proc.once("exit", (code, signal) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(
          new Error(
            `Chrome exited before DevTools started (code=${code}, signal=${signal}). Stderr:\n${stderrChunks.join("")}`,
          ),
        );
      }
    });
  });

  return { proc, wsUrl };
}

async function terminateChrome(proc, cdp) {
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

function attachErrorCollectors(cdp, sessionId) {
  const errors = [];

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
      errors.push(`browser log error (${entry.source || "unknown"}): ${entry.text || ""}`);
    }
  });

  return {
    errors,
    assertClean: (context) => {
      assert.deepEqual(errors, [], `Unexpected browser errors during ${context}:\n${errors.join("\n")}`);
    },
    dispose: () => {
      offException();
      offConsole();
      offLog();
    },
  };
}

async function verifyPromotedCloudflareSite(cdp, sessionId, baseUrl, comparison) {
  const collector = attachErrorCollectors(cdp, sessionId);
  try {
    await cdp.navigate(sessionId, `${baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-comparison-shell]").hidden && document.querySelectorAll("[data-page-row]").length > 0',
      "promoted explorer shells and page rows",
    );

    const firstScreen = await cdp.evaluate(
      sessionId,
      `(() => {
        const errorBanner = document.querySelector("[data-error-banner]");
        const summaryWords = document.querySelector("[data-summary-words]")?.textContent?.trim() ?? "";
        const windowRange = document.querySelector("[data-window-range]")?.textContent?.trim() ?? "";
        const comparedCount = document.querySelector("[data-compared-count]")?.textContent?.trim() ?? "";
        const excludedCount = document.querySelector("[data-excluded-count]")?.textContent?.trim() ?? "";
        const reproduceLink = document.querySelector("[data-reproduce-link]");
        const footer = document.querySelector("[data-attribution-footer]");
        const licenseLink = footer?.querySelector('a[href="https://creativecommons.org/licenses/by/4.0/"]');
        const rows = Array.from(document.querySelectorAll("[data-page-row]")).map((btn) => ({
          url: btn.querySelector(".page-row-url")?.textContent?.trim() ?? "",
          meta: btn.querySelector(".page-row-meta")?.textContent?.trim() ?? "",
          selected: btn.getAttribute("aria-current"),
        }));
        const detailLinks = Array.from(document.querySelectorAll("[data-page-detail] .captures-grid a")).map(
          (a) => a.href,
        );
        return {
          errorHidden: Boolean(errorBanner?.hidden),
          samplePill: document.querySelector("[data-sample-id]")?.textContent?.trim() ?? "",
          summaryWords,
          windowRange,
          comparedCount,
          excludedCount,
          reproduceText: reproduceLink?.textContent?.trim() ?? "",
          reproduceHref: reproduceLink?.getAttribute("href") ?? "",
          footerHidden: Boolean(footer?.hidden),
          footerText: footer?.textContent ?? "",
          licenseHref: licenseLink?.getAttribute("href") ?? "",
          rows,
          detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
          detailWords: document.querySelector("[data-page-detail] .detail-word-count")?.textContent?.trim() ?? "",
          detailLinks,
        };
      })()`,
    );

    assert.equal(firstScreen.errorHidden, true, "Error banner must stay hidden for valid comparison");
    assert.equal(firstScreen.samplePill, comparison.sample_id);
    assert.equal(firstScreen.summaryWords.replace(/,/g, ""), "1358");
    assert.ok(firstScreen.windowRange.includes("2025-10"), `Expected 2025-10 in ${firstScreen.windowRange}`);
    assert.ok(firstScreen.windowRange.includes("2026-04"), `Expected 2026-04 in ${firstScreen.windowRange}`);
    assert.equal(firstScreen.comparedCount, "2");
    assert.equal(firstScreen.excludedCount, "0");
    assert.equal(firstScreen.reproduceText, "Reproduce this result");
    assert.match(firstScreen.reproduceHref, /^https:\/\/github\.com\/youzaina001\/geocrawl\/tree\/[0-9a-f]{40}$/);
    assert.ok(firstScreen.reproduceHref.endsWith(`/${comparison.producing_commit}`));
    assert.equal(firstScreen.footerHidden, false, "Attribution footer must be visible");
    assert.ok(firstScreen.footerText.includes("CC BY 4.0"), "Attribution must mention CC BY 4.0");
    assert.equal(firstScreen.licenseHref, "https://creativecommons.org/licenses/by/4.0/");
    assert.equal(firstScreen.rows.length, 2);
    assert.equal(firstScreen.rows[0].selected, "true");
    assert.ok(firstScreen.rows[0].url.endsWith("/changelog/"));
    assert.equal(firstScreen.detailLinks.length, 2);
    for (const href of firstScreen.detailLinks) {
      assert.match(href, /^https:\/\/web\.archive\.org\//);
    }

    // Verify sort select switches order cleanly.
    const sortedAscFirst = await cdp.evaluate(
      sessionId,
      `(() => {
        const select = document.querySelector("[data-sort-select]");
        select.value = "new_words_asc";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return document.querySelector("[data-page-row] .page-row-url")?.textContent?.trim() ?? "";
      })()`,
    );
    assert.equal(sortedAscFirst, "https://developers.cloudflare.com/ai-crawl-control/");

    const sortedUrlFirst = await cdp.evaluate(
      sessionId,
      `(() => {
        const select = document.querySelector("[data-sort-select]");
        select.value = "url_asc";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return document.querySelector("[data-page-row] .page-row-url")?.textContent?.trim() ?? "";
      })()`,
    );
    assert.equal(sortedUrlFirst, "https://developers.cloudflare.com/ai-crawl-control/");

    await cdp.evaluate(
      sessionId,
      `(() => {
        const select = document.querySelector("[data-sort-select]");
        select.value = "new_words_desc";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      })()`,
    );

    // Verify selecting a page via keyboard Enter updates the detail panel and focus.
    await cdp.evaluate(
      sessionId,
      `(() => {
        const rows = Array.from(document.querySelectorAll("[data-page-row]"));
        const overviewRow = rows.find(
          (row) => row.querySelector(".page-row-url")?.textContent?.trim() === "https://developers.cloudflare.com/ai-crawl-control/",
        );
        overviewRow.focus();
      })()`,
    );
    await cdp.send(
      "Input.dispatchKeyEvent",
      {
        type: "keyDown",
        key: "Enter",
        code: "Enter",
        windowsVirtualKeyCode: 13,
        text: "\r",
        unmodifiedText: "\r",
      },
      sessionId,
    );
    await cdp.send(
      "Input.dispatchKeyEvent",
      {
        type: "keyUp",
        key: "Enter",
        code: "Enter",
        windowsVirtualKeyCode: 13,
      },
      sessionId,
    );

    const selectedOverview = await cdp.evaluate(
      sessionId,
      `(() => ({
        detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
        detailWords: document.querySelector("[data-page-detail] .detail-word-count")?.textContent?.trim() ?? "",
        activeUrl: document.activeElement?.querySelector(".page-row-url")?.textContent?.trim() ?? "",
        links: Array.from(document.querySelectorAll("[data-page-detail] .captures-grid a")).map((a) => ({
          href: a.href,
          rel: a.rel,
          target: a.target,
        })),
      }))()`,
    );
    assert.equal(selectedOverview.detailUrl, "https://developers.cloudflare.com/ai-crawl-control/");
    assert.equal(selectedOverview.detailWords, "16 new words");
    assert.equal(selectedOverview.activeUrl, "https://developers.cloudflare.com/ai-crawl-control/");
    assert.equal(selectedOverview.links.length, 2);
    for (const link of selectedOverview.links) {
      assert.match(link.href, /^https:\/\/web\.archive\.org\//);
      assert.equal(link.target, "_blank");
      assert.equal(link.rel, "noopener noreferrer");
    }

    // Verify path traversal is blocked by the static server.
    const traversalRes = await fetch(`${baseUrl}/../pyproject.toml`);
    assert.ok(traversalRes.status === 403 || traversalRes.status === 404);

    // Verify status filter buttons.
    const incompleteState = await cdp.evaluate(
      sessionId,
      `(() => {
        document.querySelector('[data-status-filter="comparison_incomplete"]').click();
        return {
          pressed: document.querySelector('[data-status-filter="comparison_incomplete"]').getAttribute("aria-pressed"),
          matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
          emptyHidden: document.querySelector("[data-empty-list]")?.hidden,
          detailText: document.querySelector("[data-detail-body]")?.textContent?.trim() ?? "",
        };
      })()`,
    );
    assert.equal(incompleteState.pressed, "true");
    assert.equal(incompleteState.matchCount, "Showing 0 of 2 pages");
    assert.equal(incompleteState.emptyHidden, false);
    assert.ok(incompleteState.detailText.includes("No page selected"));

    const comparedState = await cdp.evaluate(
      sessionId,
      `(() => {
        document.querySelector('[data-status-filter="compared"]').click();
        return {
          pressed: document.querySelector('[data-status-filter="compared"]').getAttribute("aria-pressed"),
          matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
        };
      })()`,
    );
    assert.equal(comparedState.pressed, "true");
    assert.equal(comparedState.matchCount, "Showing 2 of 2 pages");

    await cdp.evaluate(
      sessionId,
      'document.querySelector(\'[data-status-filter="all"]\').click()',
    );

    // Verify search filter for "changelog".
    const changelogFiltered = await cdp.evaluate(
      sessionId,
      `(() => {
        const input = document.querySelector("[data-url-filter]");
        input.value = "changelog";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        return {
          matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
          urls: Array.from(document.querySelectorAll("[data-page-row] .page-row-url")).map((el) =>
            el.textContent.trim(),
          ),
          detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
          detailWords: document.querySelector("[data-page-detail] .detail-word-count")?.textContent?.trim() ?? "",
          links: Array.from(document.querySelectorAll("[data-page-detail] .captures-grid a")).map(
            (a) => a.href,
          ),
        };
      })()`,
    );
    assert.equal(changelogFiltered.matchCount, "Showing 1 of 2 pages");
    assert.deepEqual(changelogFiltered.urls, [
      "https://developers.cloudflare.com/ai-crawl-control/changelog/",
    ]);
    assert.equal(
      changelogFiltered.detailUrl,
      "https://developers.cloudflare.com/ai-crawl-control/changelog/",
    );
    assert.equal(changelogFiltered.detailWords, "1,342 new words");
    assert.equal(changelogFiltered.links.length, 2);
    for (const href of changelogFiltered.links) {
      assert.match(href, /^https:\/\/web\.archive\.org\//);
    }

    // Clear search and check provenance details block.
    const provenance = await cdp.evaluate(
      sessionId,
      `(() => {
        const input = document.querySelector("[data-url-filter]");
        input.value = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        const details = document.getElementById("reproduce-details");
        details.open = true;
        return {
          commit: document.querySelector("[data-producing-commit]")?.textContent?.trim() ?? "",
          sha256: document.querySelector("[data-manifest-sha256]")?.textContent?.trim() ?? "",
          demoCommand: document.querySelector("[data-demo-command]")?.textContent?.trim() ?? "",
          manifestHref: document.querySelector("[data-manifest-slot] a")?.href ?? "",
        };
      })()`,
    );
    assert.equal(provenance.commit, comparison.producing_commit);
    assert.equal(provenance.sha256, comparison.manifest_sha256);
    assert.equal(provenance.demoCommand, `git checkout ${comparison.producing_commit} && make demo`);
    assert.equal(
      provenance.manifestHref,
      `https://github.com/youzaina001/geocrawl/blob/${comparison.producing_commit}/fixtures/cloudflare-ai-crawl-control/manifest.json`,
    );

    // Collapse details again before measuring viewports, then check desktop/mobile/narrow geometry.
    await cdp.evaluate(sessionId, 'document.getElementById("reproduce-details").open = false');

    for (const viewport of VIEWPORTS) {
      await cdp.setViewport(sessionId, viewport);
      const layout = await cdp.evaluate(
        sessionId,
        `(() => {
          const selectors = [
            "header.site-header",
            "main#main-content",
            ".summary-section",
            "[data-reproduce-link]",
            ".explorer-section",
            ".controls-bar",
            ".page-list-card",
            "[data-page-detail]",
            "footer.site-footer",
          ];
          const boxes = selectors.map((selector) => {
            const el = document.querySelector(selector);
            const rect = el ? el.getBoundingClientRect() : null;
            return {
              selector,
              exists: Boolean(el),
              width: rect ? rect.width : 0,
              height: rect ? rect.height : 0,
              left: rect ? rect.left : 0,
              right: rect ? rect.right : 0,
            };
          });
          const kpiBoxes = Array.from(document.querySelectorAll(".kpi-card")).map((el, idx) => {
            const rect = el.getBoundingClientRect();
            return {
              selector: ".kpi-card[" + idx + "]",
              width: rect.width,
              height: rect.height,
              left: rect.left,
              right: rect.right,
            };
          });
          return {
            innerWidth: window.innerWidth,
            scrollWidth: document.documentElement.scrollWidth,
            boxes,
            kpiBoxes,
          };
        })()`,
      );

      assert.ok(
        layout.scrollWidth <= layout.innerWidth,
        `Horizontal overflow at ${viewport.name}: scrollWidth=${layout.scrollWidth} > innerWidth=${layout.innerWidth}`,
      );
      assert.equal(layout.kpiBoxes.length, 3, `Expected 3 KPI cards at ${viewport.name}`);
      for (const box of [...layout.boxes, ...layout.kpiBoxes]) {
        assert.ok(
          box.width > 0 && box.height > 0,
          `Zero bounding box at ${viewport.name} for ${box.selector}: ${JSON.stringify(box)}`,
        );
        assert.ok(
          box.left >= -1 && box.right <= layout.innerWidth + 1,
          `Element extends beyond viewport at ${viewport.name} for ${box.selector}: ${JSON.stringify(box)}`,
        );
      }
    }

    collector.assertClean("promoted Cloudflare explorer checks");
  } finally {
    collector.dispose();
  }
}

async function verifyTamperedAndMalformedFixtures(cdp, sessionId, tmpRoot) {
  const tamperedSiteDir = path.join(tmpRoot, "tampered-site");
  copyExplorerAssets(path.join(REPO_ROOT, "explorer"), tamperedSiteDir);

  const tamperedComparison = {
    schema_version: 1,
    sample_id: "cloudflare-ai-crawl-control",
    producing_commit: "a".repeat(40),
    manifest_sha256: "b".repeat(64),
    earlier_window: "2025-10",
    later_window: "2026-04",
    archive_host: "web.archive.org",
    attribution: {
      license: "CC BY 4.0",
      license_url: "https://creativecommons.org/licenses/by/4.0/",
      authors: "Cloudflare, Inc. and Cloudflare Documentation contributors",
      source_url: "https://github.com/cloudflare/cloudflare-docs#license-and-legal-notices",
      modifications: "Extracted main article HTML.",
    },
    summary: {
      compared_pages: 1,
      excluded_pages: 1,
      distinct_new_words: 42,
    },
    pages: [
      {
        url: "https://developers.cloudflare.com/ai-crawl-control/tampered/",
        status: "compared",
        new_words: 42,
        earlier_capture_url: "https://evil.example/x",
        later_capture_url:
          "https://web.archive.org:443/web/20260401000000/https://developers.cloudflare.com/ai-crawl-control/tampered/",
      },
      {
        url: "https://developers.cloudflare.com/ai-crawl-control/broken/",
        status: "comparison_incomplete",
        new_words: null,
        earlier_capture_url: null,
        later_capture_url: "https://evil.example/later",
      },
    ],
  };

  const comparisonPath = path.join(tamperedSiteDir, "comparison.json");
  fs.writeFileSync(comparisonPath, JSON.stringify(tamperedComparison, null, 2), "utf8");

  const serverHandle = await startStaticServer(tamperedSiteDir);
  const collector = attachErrorCollectors(cdp, sessionId);
  try {
    await cdp.setViewport(sessionId, VIEWPORTS[0]);
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-comparison-shell]").hidden && document.querySelectorAll("[data-page-row]").length === 2',
      "tampered fixture rendering",
    );

    const tamperedFirst = await cdp.evaluate(
      sessionId,
      `(() => ({
        errorHidden: document.querySelector("[data-error-banner]").hidden,
        summaryWords: document.querySelector("[data-summary-words]").textContent.trim(),
        comparedCount: document.querySelector("[data-compared-count]").textContent.trim(),
        excludedCount: document.querySelector("[data-excluded-count]").textContent.trim(),
        detailUrl: document.querySelector("[data-page-detail] .detail-url").textContent.trim(),
        detailWords: document.querySelector("[data-page-detail] .detail-word-count").textContent.trim(),
        detailStatus: document.querySelector("[data-page-detail] .badge").textContent.trim(),
        captureLinks: document.querySelectorAll("[data-page-detail] .captures-grid a").length,
        fallbacks: Array.from(document.querySelectorAll("[data-page-detail] [data-capture-fallback]")).map((el) =>
          el.textContent.trim(),
        ),
      }))()`,
    );

    assert.equal(tamperedFirst.errorHidden, true);
    assert.equal(tamperedFirst.summaryWords, "42");
    assert.equal(tamperedFirst.comparedCount, "1");
    assert.equal(tamperedFirst.excludedCount, "1");
    assert.equal(
      tamperedFirst.detailUrl,
      "https://developers.cloudflare.com/ai-crawl-control/tampered/",
    );
    assert.equal(tamperedFirst.detailWords, "42 new words");
    assert.equal(tamperedFirst.detailStatus, "Compared");
    assert.equal(
      tamperedFirst.captureLinks,
      0,
      "Disallowed host and explicit :443 port must not render clickable links",
    );
    assert.deepEqual(tamperedFirst.fallbacks, [
      "Capture link unavailable",
      "Capture link unavailable",
    ]);

    const incompleteDetail = await cdp.evaluate(
      sessionId,
      `(() => {
        const rows = Array.from(document.querySelectorAll("[data-page-row]"));
        const broken = rows.find((row) =>
          row.querySelector(".page-row-url").textContent.includes("/broken/"),
        );
        broken.click();
        return {
          detailUrl: document.querySelector("[data-page-detail] .detail-url").textContent.trim(),
          detailWords: document.querySelector("[data-page-detail] .detail-word-count").textContent.trim(),
          detailStatus: document.querySelector("[data-page-detail] .badge").textContent.trim(),
          captureLinks: document.querySelectorAll("[data-page-detail] .captures-grid a").length,
          emptySlots: Array.from(document.querySelectorAll("[data-page-detail] .capture-empty")).map((el) =>
            el.textContent.trim(),
          ),
          fallbacks: Array.from(document.querySelectorAll("[data-page-detail] [data-capture-fallback]")).map((el) =>
            el.textContent.trim(),
          ),
        };
      })()`,
    );

    assert.equal(
      incompleteDetail.detailUrl,
      "https://developers.cloudflare.com/ai-crawl-control/broken/",
    );
    assert.equal(incompleteDetail.detailWords, "Comparison incomplete");
    assert.equal(incompleteDetail.detailStatus, "Comparison incomplete");
    assert.equal(incompleteDetail.captureLinks, 0);
    assert.deepEqual(incompleteDetail.emptySlots, ["Not captured"]);
    assert.deepEqual(incompleteDetail.fallbacks, ["Capture link unavailable"]);

    // Overwrite comparison.json with malformed JSON and verify error banner.
    fs.writeFileSync(comparisonPath, "{not valid json", "utf8");
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-error-banner]").hidden',
      "visible error banner on malformed JSON",
    );

    const errorState = await cdp.evaluate(
      sessionId,
      `(() => {
        const banner = document.querySelector("[data-error-banner]");
        const rect = banner.getBoundingClientRect();
        return {
          bannerHidden: banner.hidden,
          display: getComputedStyle(banner).display,
          width: rect.width,
          height: rect.height,
          title: document.querySelector("[data-error-title]").textContent.trim(),
          message: document.querySelector("[data-error-message]").textContent.trim(),
          comparisonShellHidden: document.querySelector("[data-comparison-shell]").hidden,
          pagesShellHidden: document.querySelector("[data-pages-shell]").hidden,
        };
      })()`,
    );

    assert.equal(errorState.bannerHidden, false);
    assert.notEqual(errorState.display, "none");
    assert.ok(errorState.width > 0 && errorState.height > 0, "Error banner must have visible size");
    assert.match(errorState.title, /not valid JSON/i);
    assert.ok(errorState.message.length > 0);
    assert.equal(errorState.comparisonShellHidden, true);
    assert.equal(errorState.pagesShellHidden, true);

    collector.assertClean("tampered and malformed JSON fixture checks");
  } finally {
    collector.dispose();
    await serverHandle.close();
  }
}

async function main() {
  const { siteDir: providedSiteDir } = parseArgs(process.argv.slice(2));
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "geocrawl-browser-"));
  const chromeUserDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "geocrawl-chrome-"));

  let siteServer = null;
  let chromeProc = null;
  let cdp = null;

  try {
    const siteDir = providedSiteDir ?? buildPromotedDemoSite(tmpRoot);
    assert.ok(
      fs.existsSync(path.join(siteDir, "index.html")),
      `Site directory is missing index.html: ${siteDir}`,
    );
    const comparisonPath = path.join(siteDir, "comparison.json");
    assert.ok(
      fs.existsSync(comparisonPath),
      `Site directory is missing comparison.json: ${siteDir}`,
    );
    const comparison = JSON.parse(fs.readFileSync(comparisonPath, "utf8"));

    siteServer = await startStaticServer(siteDir);
    const launched = await launchChrome(chromeUserDataDir, {
      onSpawn: (proc) => {
        chromeProc = proc;
      },
    });
    chromeProc = launched.proc;
    cdp = await CdpClient.connect(launched.wsUrl);
    const { sessionId } = await cdp.createSession();

    await verifyPromotedCloudflareSite(cdp, sessionId, siteServer.baseUrl, comparison);
    await verifyTamperedAndMalformedFixtures(cdp, sessionId, tmpRoot);

    console.log(
      `Browser checks passed (${VIEWPORTS.map((v) => `${v.width}x${v.height}`).join(", ")}; promoted + tampered + malformed JSON).`,
    );
  } finally {
    await terminateChrome(chromeProc, cdp);
    if (siteServer) {
      await siteServer.close();
    }
    fs.rmSync(chromeUserDataDir, { recursive: true, force: true });
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack || err.message : String(err));
  process.exit(1);
});
