#!/usr/bin/env node
// Headless Chrome DevTools verification for the geocrawl static comparison explorer.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  filterAndSortPages,
  isAllowedArchiveUrl,
  validateAttributionLink,
} from "../explorer/lib.js";
import {
  CdpClient,
  attachErrorCollectors,
  createShutdownManager,
  launchChrome,
  rawHttpGet,
  startStaticServer,
  terminateChrome,
} from "./cdp_driver.mjs";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900, mobile: false },
  { name: "mobile-390", width: 390, height: 844, mobile: true },
  { name: "narrow-320", width: 320, height: 720, mobile: true },
];
const NUMBER_FORMAT = new Intl.NumberFormat("en-US");

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

async function assertResponsiveGeometry(cdp, sessionId, detailsOpen, context) {
  await cdp.evaluate(
    sessionId,
    `document.getElementById("reproduce-details").open = ${detailsOpen ? "true" : "false"}`,
  );

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
          "#reproduce-details",
          ".explorer-section",
          ".controls-bar",
          ".page-list-card",
          "[data-page-detail]",
        ];
        const footer = document.querySelector("footer.site-footer");
        if (footer && !footer.hidden) {
          selectors.push("footer.site-footer");
        }
        const boxes = selectors.map((selector) => {
          const el = document.querySelector(selector);
          const rect = el ? el.getBoundingClientRect() : null;
          return {
            selector,
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
        const clippedChildren = [];
        for (const el of document.querySelectorAll("main *, footer *")) {
          if (el.closest("[hidden]")) {
            continue;
          }
          const style = getComputedStyle(el);
          if (style.display === "none") {
            continue;
          }
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 && rect.height === 0) {
            continue;
          }
          if (rect.left < -1 || rect.right > window.innerWidth + 1) {
            clippedChildren.push({
              tag: el.tagName.toLowerCase(),
              cls: el.className,
              left: rect.left,
              right: rect.right,
              innerWidth: window.innerWidth,
            });
          }
          if (el.scrollWidth > el.clientWidth + 1) {
            clippedChildren.push({
              tag: el.tagName.toLowerCase(),
              cls: el.className,
              scrollWidth: el.scrollWidth,
              clientWidth: el.clientWidth,
            });
          }
        }
        return {
          innerWidth: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          boxes,
          kpiBoxes,
          clippedChildren,
        };
      })()`,
    );

    const label = `${context} (detailsOpen=${detailsOpen}, ${viewport.name})`;
    assert.ok(
      layout.scrollWidth <= layout.innerWidth,
      `Horizontal overflow at ${label}: scrollWidth=${layout.scrollWidth} > innerWidth=${layout.innerWidth}`,
    );
    assert.equal(layout.kpiBoxes.length, 3, `Expected 3 KPI cards at ${label}`);
    for (const box of [...layout.boxes, ...layout.kpiBoxes]) {
      assert.ok(
        box.width > 0 && box.height > 0,
        `Zero bounding box at ${label} for ${box.selector}: ${JSON.stringify(box)}`,
      );
      assert.ok(
        box.left >= -1 && box.right <= layout.innerWidth + 1,
        `Element extends beyond viewport at ${label} for ${box.selector}: ${JSON.stringify(box)}`,
      );
    }
    assert.deepEqual(
      layout.clippedChildren,
      [],
      `Clipped children at ${label}: ${JSON.stringify(layout.clippedChildren)}`,
    );
  }
}

async function verifyPromotedSite(cdp, sessionId, baseUrl, comparison, { strictCloudflareDemo }) {
  const collector = attachErrorCollectors(cdp, sessionId);
  try {
    await cdp.navigate(sessionId, `${baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-comparison-shell]").hidden && document.querySelectorAll("[data-page-row]").length === ' +
        String(comparison.pages.length),
      "promoted explorer shells and page rows",
    );

    const firstScreen = await cdp.evaluate(
      sessionId,
      `(() => {
        const errorBanner = document.querySelector("[data-error-banner]");
        const footer = document.querySelector("[data-attribution-footer]");
        const reproduceLink = document.querySelector("[data-reproduce-link]");
        return {
          errorHidden: Boolean(errorBanner?.hidden),
          samplePill: document.querySelector("[data-sample-id]")?.textContent?.trim() ?? "",
          summaryWords: document.querySelector("[data-summary-words]")?.textContent?.trim() ?? "",
          windowRange: document.querySelector("[data-window-range]")?.textContent?.trim() ?? "",
          comparedCount: document.querySelector("[data-compared-count]")?.textContent?.trim() ?? "",
          excludedCount: document.querySelector("[data-excluded-count]")?.textContent?.trim() ?? "",
          reproduceText: reproduceLink?.textContent?.trim() ?? "",
          reproduceHref: reproduceLink?.getAttribute("href") ?? "",
          footerHidden: Boolean(footer?.hidden),
          footerText: footer?.textContent ?? "",
          footerLinks: Array.from(footer?.querySelectorAll("a") ?? []).map((a) => a.href),
          rows: Array.from(document.querySelectorAll("[data-page-row]")).map((btn) => ({
            url: btn.querySelector(".page-row-url")?.textContent?.trim() ?? "",
            selected: btn.getAttribute("aria-current"),
          })),
          detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
          detailWords: document.querySelector("[data-page-detail] .detail-word-count")?.textContent?.trim() ?? "",
          detailLinks: Array.from(document.querySelectorAll("[data-page-detail] .captures-grid a")).map(
            (a) => a.href,
          ),
        };
      })()`,
    );

    assert.equal(firstScreen.errorHidden, true, "Error banner must stay hidden for valid comparison");
    assert.equal(firstScreen.samplePill, comparison.sample_id);
    assert.equal(
      firstScreen.summaryWords,
      NUMBER_FORMAT.format(comparison.summary.distinct_new_words),
    );
    assert.ok(firstScreen.windowRange.includes(comparison.earlier_window));
    assert.ok(firstScreen.windowRange.includes(comparison.later_window));
    assert.equal(firstScreen.comparedCount, NUMBER_FORMAT.format(comparison.summary.compared_pages));
    assert.equal(firstScreen.excludedCount, NUMBER_FORMAT.format(comparison.summary.excluded_pages));
    assert.equal(firstScreen.reproduceText, "Reproduce this result");
    assert.equal(
      firstScreen.reproduceHref,
      `https://github.com/youzaina001/geocrawl/tree/${comparison.producing_commit}`,
    );

    if (comparison.attribution) {
      assert.equal(firstScreen.footerHidden, false, "Attribution footer must be visible");
      assert.ok(firstScreen.footerText.includes(comparison.attribution.license));
      assert.ok(firstScreen.footerText.includes(comparison.attribution.authors));
      if (validateAttributionLink(comparison.attribution.license_url)) {
        assert.ok(firstScreen.footerLinks.includes(comparison.attribution.license_url));
      }
    } else {
      assert.equal(firstScreen.footerHidden, true, "Attribution footer must be hidden when null");
    }

    const expectedDefault = filterAndSortPages(comparison.pages, { sortBy: "new_words_desc" });
    assert.deepEqual(
      firstScreen.rows.map((r) => r.url),
      expectedDefault.map((p) => p.url),
    );
    if (expectedDefault.length > 0) {
      assert.equal(firstScreen.rows[0].selected, "true");
      assert.equal(firstScreen.detailUrl, expectedDefault[0].url);
    }

    // Verify sort modes match filterAndSortPages.
    for (const sortBy of ["new_words_asc", "url_asc", "new_words_desc"]) {
      const actualUrls = await cdp.evaluate(
        sessionId,
        `(() => {
          const select = document.querySelector("[data-sort-select]");
          select.value = ${JSON.stringify(sortBy)};
          select.dispatchEvent(new Event("change", { bubbles: true }));
          return Array.from(document.querySelectorAll("[data-page-row] .page-row-url")).map((el) =>
            el.textContent.trim(),
          );
        })()`,
      );
      assert.deepEqual(
        actualUrls,
        filterAndSortPages(comparison.pages, { sortBy }).map((p) => p.url),
      );
    }

    // Verify row click preserves list DOM nodes (no rebuild) and keyboard Enter updates detail & keeps focus.
    if (expectedDefault.length > 1) {
      const targetPage = expectedDefault[1];
      const clickPreserved = await cdp.evaluate(
        sessionId,
        `(() => {
          const rows = Array.from(document.querySelectorAll("[data-page-row]"));
          const secondBtn = rows[1];
          window.__savedRowRef = secondBtn;
          secondBtn.click();
          const currentRows = Array.from(document.querySelectorAll("[data-page-row]"));
          return {
            sameNode: currentRows[1] === window.__savedRowRef,
            selected: currentRows[1].getAttribute("aria-current"),
            detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
          };
        })()`,
      );
      assert.equal(clickPreserved.sameNode, true, "Selecting a row must not rebuild the page list DOM");
      assert.equal(clickPreserved.selected, "true");
      assert.equal(clickPreserved.detailUrl, targetPage.url);

      // Focus and press Enter on the last row (or targetPage).
      await cdp.evaluate(
        sessionId,
        `(() => {
          const rows = Array.from(document.querySelectorAll("[data-page-row]"));
          rows[0].click();
          rows[1].focus();
        })()`,
      );
      await cdp.send(
        "Input.dispatchKeyEvent",
        { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" },
        sessionId,
      );
      await cdp.send(
        "Input.dispatchKeyEvent",
        { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 },
        sessionId,
      );

      const enterResult = await cdp.evaluate(
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
      assert.equal(enterResult.detailUrl, targetPage.url);
      assert.equal(enterResult.activeUrl, targetPage.url);
      const expectedWordsText =
        targetPage.status === "compared"
          ? `${NUMBER_FORMAT.format(targetPage.new_words)} new words`
          : "Comparison incomplete";
      assert.equal(enterResult.detailWords, expectedWordsText);
      const expectedAllowedLinks = [targetPage.earlier_capture_url, targetPage.later_capture_url].filter(
        (u) => u !== null && isAllowedArchiveUrl(u, comparison.archive_host),
      );
      assert.equal(enterResult.links.length, expectedAllowedLinks.length);
      for (const link of enterResult.links) {
        assert.equal(link.target, "_blank");
        assert.equal(link.rel, "noopener noreferrer");
      }
    }

    // Verify status filter buttons dynamically against comparison.pages.
    for (const statusFilter of ["comparison_incomplete", "compared", "all"]) {
      const expectedCount =
        statusFilter === "all"
          ? comparison.pages.length
          : comparison.pages.filter((p) => p.status === statusFilter).length;
      const statusState = await cdp.evaluate(
        sessionId,
        `(() => {
          document.querySelector('[data-status-filter="${statusFilter}"]').click();
          return {
            pressed: document.querySelector('[data-status-filter="${statusFilter}"]').getAttribute("aria-pressed"),
            matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
            emptyHidden: document.querySelector("[data-empty-list]")?.hidden,
            detailText: document.querySelector("[data-detail-body]")?.textContent?.trim() ?? "",
          };
        })()`,
      );
      assert.equal(statusState.pressed, "true");
      assert.equal(
        statusState.matchCount,
        `Showing ${NUMBER_FORMAT.format(expectedCount)} of ${NUMBER_FORMAT.format(comparison.pages.length)} pages`,
      );
      assert.equal(statusState.emptyHidden, expectedCount > 0);
      if (expectedCount === 0) {
        assert.ok(statusState.detailText.includes("No page selected"));
      }
    }

    // Verify search filter matching a known page and empty search state.
    if (expectedDefault.length > 0) {
      const searchTarget = expectedDefault[0];
      const token = new URL(searchTarget.url).pathname.split("/").filter(Boolean).pop() || searchTarget.url;
      const expectedMatches = filterAndSortPages(comparison.pages, { query: token });
      const searchState = await cdp.evaluate(
        sessionId,
        `(() => {
          const input = document.querySelector("[data-url-filter]");
          input.value = ${JSON.stringify(token)};
          input.dispatchEvent(new Event("input", { bubbles: true }));
          return {
            matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
            urls: Array.from(document.querySelectorAll("[data-page-row] .page-row-url")).map((el) =>
              el.textContent.trim(),
            ),
          };
        })()`,
      );
      assert.equal(
        searchState.matchCount,
        `Showing ${NUMBER_FORMAT.format(expectedMatches.length)} of ${NUMBER_FORMAT.format(comparison.pages.length)} pages`,
      );
      assert.deepEqual(searchState.urls, expectedMatches.map((p) => p.url));
    }

    const emptySearchState = await cdp.evaluate(
      sessionId,
      `(() => {
        const input = document.querySelector("[data-url-filter]");
        input.value = "no-such-page-match-xyzzy";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        const emptyEl = document.querySelector("[data-empty-list]");
        return {
          matchCount: document.querySelector("[data-match-count]")?.textContent?.trim() ?? "",
          emptyHidden: emptyEl?.hidden,
          emptyText: emptyEl?.textContent?.trim() ?? "",
          detailText: document.querySelector("[data-detail-body]")?.textContent?.trim() ?? "",
        };
      })()`,
    );
    assert.equal(
      emptySearchState.matchCount,
      `Showing 0 of ${NUMBER_FORMAT.format(comparison.pages.length)} pages`,
    );
    assert.equal(emptySearchState.emptyHidden, false);
    assert.match(emptySearchState.emptyText, /no pages match/i);
    assert.ok(emptySearchState.detailText.includes("No page selected"));

    // Reset filter and inspect provenance details.
    const provenance = await cdp.evaluate(
      sessionId,
      `(() => {
        const input = document.querySelector("[data-url-filter]");
        input.value = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
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
      `https://github.com/youzaina001/geocrawl/blob/${comparison.producing_commit}/fixtures/${comparison.sample_id}/manifest.json`,
    );

    if (strictCloudflareDemo) {
      assert.equal(comparison.sample_id, "cloudflare-ai-crawl-control");
      assert.equal(firstScreen.summaryWords.replace(/,/g, ""), "1358");
      assert.equal(comparison.earlier_window, "2025-10");
      assert.equal(comparison.later_window, "2026-04");
      assert.equal(firstScreen.comparedCount, "2");
      assert.equal(firstScreen.excludedCount, "0");
      assert.ok(firstScreen.footerText.includes("CC BY 4.0"));
      assert.equal(firstScreen.rows.length, 2);
      assert.ok(firstScreen.rows[0].url.endsWith("/changelog/"));
      assert.equal(firstScreen.detailWords, "1,342 new words");
      for (const href of firstScreen.detailLinks) {
        assert.match(href, /^https:\/\/web\.archive\.org\//);
      }
    }

    // Check raw HTTP path traversal returns 403.
    const traversalRes = await rawHttpGet(baseUrl, "/../pyproject.toml");
    assert.equal(traversalRes.status, 403, "Raw /../pyproject.toml must return 403 Forbidden");

    // Check responsive geometry across all 3 viewports with #reproduce-details closed AND open.
    await assertResponsiveGeometry(cdp, sessionId, false, "promoted site");
    await assertResponsiveGeometry(cdp, sessionId, true, "promoted site");

    collector.assertClean("promoted site checks");
  } finally {
    collector.dispose();
  }
}

async function verifyStaticServerSecurity(tmpRoot, shutdown) {
  const secDir = path.join(tmpRoot, "sec-site");
  const outsideDir = path.join(tmpRoot, "outside-secret");
  fs.mkdirSync(secDir, { recursive: true });
  fs.mkdirSync(outsideDir, { recursive: true });
  fs.writeFileSync(path.join(secDir, "index.html"), "<html>ok</html>\n", "utf8");
  fs.writeFileSync(path.join(outsideDir, "secret.txt"), "top-secret", "utf8");
  fs.symlinkSync(outsideDir, path.join(secDir, "escape-dir"));
  fs.symlinkSync(path.join(outsideDir, "secret.txt"), path.join(secDir, "escape.txt"));

  const server = await startStaticServer(secDir);
  shutdown.add(() => server.close());
  try {
    assert.equal((await rawHttpGet(server.baseUrl, "/../pyproject.toml")).status, 403);
    assert.equal((await rawHttpGet(server.baseUrl, "/escape-dir")).status, 403);
    assert.equal((await rawHttpGet(server.baseUrl, "/escape-dir/secret.txt")).status, 403);
    assert.equal((await rawHttpGet(server.baseUrl, "/escape.txt")).status, 403);
    assert.equal((await rawHttpGet(server.baseUrl, "/index.html")).status, 200);
  } finally {
    await server.close();
  }
}

async function verifyTamperedAndEdgeCaseFixtures(cdp, sessionId, tmpRoot, shutdown) {
  const tamperedSiteDir = path.join(tmpRoot, "tampered-site");
  copyExplorerAssets(path.join(REPO_ROOT, "explorer"), tamperedSiteDir);

  const xssUrl = 'https://developers.cloudflare.com/ai-crawl-control/<img src=x onerror="window.__xss=1">';
  const xssAuthor = '<img src=x onerror="window.__xss=2"> Authors';
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
      license_url: "javascript:alert(2)",
      authors: xssAuthor,
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
        url: xssUrl,
        status: "compared",
        new_words: 42,
        earlier_capture_url: "javascript:alert(1)",
        later_capture_url:
          "https://web.archive.org:443/web/20260401000000/https://developers.cloudflare.com/ai-crawl-control/",
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
  shutdown.add(() => serverHandle.close());
  const collector = attachErrorCollectors(cdp, sessionId);
  try {
    await cdp.setViewport(sessionId, VIEWPORTS[0]);
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-comparison-shell]").hidden && document.querySelectorAll("[data-page-row]").length === 2',
      "tampered fixture rendering",
    );

    const tamperedState = await cdp.evaluate(
      sessionId,
      `(() => ({
        xssFlag: window.__xss ?? null,
        injectedImgs: document.querySelectorAll("main img, footer img").length,
        jsLinks: document.querySelectorAll('a[href^="javascript:"]').length,
        footerText: document.querySelector("[data-attribution-footer]")?.textContent ?? "",
        detailUrl: document.querySelector("[data-page-detail] .detail-url")?.textContent?.trim() ?? "",
        captureLinks: document.querySelectorAll("[data-page-detail] .captures-grid a").length,
        fallbacks: Array.from(document.querySelectorAll("[data-page-detail] [data-capture-fallback]")).map((el) =>
          el.textContent.trim(),
        ),
      }))()`,
    );

    assert.equal(tamperedState.xssFlag, null, "HTML tags in JSON must never execute");
    assert.equal(tamperedState.injectedImgs, 0, "HTML tags in JSON must never create DOM elements");
    assert.equal(tamperedState.jsLinks, 0, "javascript: URLs must never render as clickable links");
    assert.equal(tamperedState.detailUrl, xssUrl);
    assert.ok(tamperedState.footerText.includes(xssAuthor));
    assert.equal(tamperedState.captureLinks, 0);
    assert.deepEqual(tamperedState.fallbacks, [
      "Capture link unavailable",
      "Capture link unavailable",
    ]);

    // Select incomplete page and test empty search state.
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
    assert.equal(incompleteDetail.detailUrl, "https://developers.cloudflare.com/ai-crawl-control/broken/");
    assert.equal(incompleteDetail.detailWords, "Comparison incomplete");
    assert.equal(incompleteDetail.captureLinks, 0);
    assert.deepEqual(incompleteDetail.emptySlots, ["Not captured"]);
    assert.deepEqual(incompleteDetail.fallbacks, ["Capture link unavailable"]);

    const noMatchesState = await cdp.evaluate(
      sessionId,
      `(() => {
        const input = document.querySelector("[data-url-filter]");
        input.value = "no-such-page-match";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        return {
          emptyHidden: document.querySelector("[data-empty-list]").hidden,
          emptyText: document.querySelector("[data-empty-list]").textContent.trim(),
        };
      })()`,
    );
    assert.equal(noMatchesState.emptyHidden, false);
    assert.match(noMatchesState.emptyText, /no pages match/i);

    // Null archive_host and null attribution hides footer and disables capture links.
    const nullHostComparison = {
      ...tamperedComparison,
      archive_host: null,
      attribution: null,
      summary: { compared_pages: 1, excluded_pages: 0, distinct_new_words: 5 },
      pages: [
        {
          url: "https://example.invalid/null-host",
          status: "compared",
          new_words: 5,
          earlier_capture_url: "https://web.archive.org/web/20251001000000/https://example.invalid/",
          later_capture_url: null,
        },
      ],
    };
    fs.writeFileSync(comparisonPath, JSON.stringify(nullHostComparison, null, 2), "utf8");
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-comparison-shell]").hidden && document.querySelectorAll("[data-page-row]").length === 1',
      "null archive_host and attribution rendering",
    );
    const nullHostState = await cdp.evaluate(
      sessionId,
      `(() => ({
        footerHidden: document.querySelector("[data-attribution-footer]").hidden,
        captureLinks: document.querySelectorAll("[data-page-detail] .captures-grid a").length,
        fallbacks: Array.from(document.querySelectorAll("[data-page-detail] [data-capture-fallback]")).map((el) =>
          el.textContent.trim(),
        ),
        emptySlots: Array.from(document.querySelectorAll("[data-page-detail] .capture-empty")).map((el) =>
          el.textContent.trim(),
        ),
      }))()`,
    );
    assert.equal(nullHostState.footerHidden, true);
    assert.equal(nullHostState.captureLinks, 0);
    assert.deepEqual(nullHostState.fallbacks, ["Capture link unavailable"]);
    assert.deepEqual(nullHostState.emptySlots, ["Not captured"]);
    collector.assertClean("tampered and null-host fixture checks");

    // Schema-invalid archive_host and attribution must show visible error banner without pageerrors.
    for (const [label, invalidPayload] of [
      ["empty archive_host", { ...nullHostComparison, archive_host: "" }],
      [
        "blank attribution.license",
        {
          ...nullHostComparison,
          attribution: { ...tamperedComparison.attribution, license: "   " },
        },
      ],
    ]) {
      fs.writeFileSync(comparisonPath, JSON.stringify(invalidPayload, null, 2), "utf8");
      await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
      await cdp.waitUntil(
        sessionId,
        '!document.querySelector("[data-error-banner]").hidden',
        `visible error banner on ${label}`,
      );
      const errBanner = await cdp.evaluate(
        sessionId,
        `(() => ({
          title: document.querySelector("[data-error-title]").textContent.trim(),
          comparisonHidden: document.querySelector("[data-comparison-shell]").hidden,
        }))()`,
      );
      assert.match(errBanner.title, /schema validation/i);
      assert.equal(errBanner.comparisonHidden, true);
    }
    collector.assertClean("schema-invalid comparison checks");

    // Malformed JSON shows error banner.
    fs.writeFileSync(comparisonPath, "{not valid json", "utf8");
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-error-banner]").hidden',
      "visible error banner on malformed JSON",
    );
    const jsonErr = await cdp.evaluate(
      sessionId,
      `(() => {
        const banner = document.querySelector("[data-error-banner]");
        const rect = banner.getBoundingClientRect();
        return {
          bannerHidden: banner.hidden,
          width: rect.width,
          height: rect.height,
          title: document.querySelector("[data-error-title]").textContent.trim(),
          comparisonHidden: document.querySelector("[data-comparison-shell]").hidden,
          pagesHidden: document.querySelector("[data-pages-shell]").hidden,
        };
      })()`,
    );
    assert.equal(jsonErr.bannerHidden, false);
    assert.ok(jsonErr.width > 0 && jsonErr.height > 0);
    assert.match(jsonErr.title, /not valid JSON/i);
    assert.equal(jsonErr.comparisonHidden, true);
    assert.equal(jsonErr.pagesHidden, true);
    collector.assertClean("malformed JSON fixture check");

    // HTTP 404 comparison.json shows error banner without uncaught JS exceptions.
    collector.reset();
    fs.unlinkSync(comparisonPath);
    await cdp.navigate(sessionId, `${serverHandle.baseUrl}/`);
    await cdp.waitUntil(
      sessionId,
      '!document.querySelector("[data-error-banner]").hidden',
      "visible error banner on HTTP 404",
    );
    const notFoundState = await cdp.evaluate(
      sessionId,
      `(() => ({
        title: document.querySelector("[data-error-title]").textContent.trim(),
        message: document.querySelector("[data-error-message]").textContent.trim(),
        comparisonHidden: document.querySelector("[data-comparison-shell]").hidden,
        pagesHidden: document.querySelector("[data-pages-shell]").hidden,
      }))()`,
    );
    assert.match(notFoundState.title, /HTTP 404/);
    assert.ok(notFoundState.message.length > 0);
    assert.equal(notFoundState.comparisonHidden, true);
    assert.equal(notFoundState.pagesHidden, true);
    collector.assertClean("HTTP 404 comparison check", { allowNetwork404: true });
  } finally {
    collector.dispose();
    await serverHandle.close();
  }
}

async function main() {
  const { siteDir: providedSiteDir } = parseArgs(process.argv.slice(2));
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "geocrawl-browser-"));
  const chromeUserDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "geocrawl-chrome-"));

  const shutdown = createShutdownManager();
  let siteServer = null;
  let chromeProc = null;
  let cdp = null;

  shutdown.add(() => fs.rmSync(tmpRoot, { recursive: true, force: true }));
  shutdown.add(() => fs.rmSync(chromeUserDataDir, { recursive: true, force: true }));
  shutdown.add(() => terminateChrome(chromeProc, cdp));

  const unregisterSignals = shutdown.registerSignals();

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
    shutdown.add(() => siteServer.close());

    const launched = await launchChrome(chromeUserDataDir, {
      onSpawn: (proc) => {
        chromeProc = proc;
      },
    });
    chromeProc = launched.proc;
    cdp = await CdpClient.connect(launched.wsUrl);
    const { sessionId } = await cdp.createSession();

    await verifyPromotedSite(cdp, sessionId, siteServer.baseUrl, comparison, {
      strictCloudflareDemo: !providedSiteDir,
    });
    await verifyStaticServerSecurity(tmpRoot, shutdown);
    await verifyTamperedAndEdgeCaseFixtures(cdp, sessionId, tmpRoot, shutdown);

    console.log(
      `Browser checks passed (${VIEWPORTS.map((v) => `${v.width}x${v.height}`).join(", ")}; promoted + security + tampered + 404).`,
    );
  } finally {
    unregisterSignals();
    await shutdown.cleanup();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack || err.message : String(err));
  process.exit(1);
});
