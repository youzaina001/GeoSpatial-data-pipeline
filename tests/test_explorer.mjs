import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildReproduceInfo,
  filterAndSortPages,
  isAllowedArchiveUrl,
  validateAttributionLink,
  validateComparisonPayload,
} from "../explorer/lib.js";

const COMMIT_A = "a".repeat(40);
const SHA256_B = "b".repeat(64);

function makeCloudflareComparison(overrides = {}) {
  return {
    schema_version: 1,
    sample_id: "cloudflare-ai-crawl-control",
    producing_commit: COMMIT_A,
    manifest_sha256: SHA256_B,
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
      compared_pages: 2,
      excluded_pages: 0,
      distinct_new_words: 1358,
    },
    pages: [
      {
        url: "https://developers.cloudflare.com/ai-crawl-control/",
        status: "compared",
        new_words: 1000,
        earlier_capture_url:
          "https://web.archive.org/web/20251002000737/https://developers.cloudflare.com/ai-crawl-control/",
        later_capture_url:
          "https://web.archive.org/web/20260429223141/https://developers.cloudflare.com/ai-crawl-control/",
      },
      {
        url: "https://developers.cloudflare.com/ai-crawl-control/changelog/",
        status: "compared",
        new_words: 400,
        earlier_capture_url:
          "https://web.archive.org/web/20251012003851/https://developers.cloudflare.com/ai-crawl-control/changelog/",
        later_capture_url:
          "https://web.archive.org/web/20260411015127/https://developers.cloudflare.com/ai-crawl-control/changelog/",
      },
    ],
    ...overrides,
  };
}

function makeHandwrittenComparison(overrides = {}) {
  return {
    schema_version: 1,
    sample_id: "handwritten",
    producing_commit: COMMIT_A,
    manifest_sha256: SHA256_B,
    earlier_window: "synthetic-earlier",
    later_window: "synthetic-later",
    archive_host: null,
    attribution: null,
    summary: {
      compared_pages: 2,
      excluded_pages: 0,
      distinct_new_words: 1,
    },
    pages: [
      {
        url: "https://example.invalid/guide",
        status: "compared",
        new_words: 1,
        earlier_capture_url: null,
        later_capture_url: null,
      },
      {
        url: "https://example.invalid/reference",
        status: "compared",
        new_words: 1,
        earlier_capture_url: null,
        later_capture_url: null,
      },
    ],
    ...overrides,
  };
}

test("isAllowedArchiveUrl allows exact HTTPS host match and rejects unsafe authorities", () => {
  assert.equal(
    isAllowedArchiveUrl(
      "https://web.archive.org/web/20251002000737/https://developers.cloudflare.com/ai-crawl-control/",
      "web.archive.org",
    ),
    true,
  );
  assert.equal(isAllowedArchiveUrl("https://WEB.ARCHIVE.ORG/web/123?a=1#frag", "web.archive.org"), true);
  assert.equal(isAllowedArchiveUrl("https://web.archive.org/web/123", "WEB.ARCHIVE.ORG"), true);

  const rejectedUrls = [
    "http://web.archive.org/web/123",
    "https:web.archive.org/web/123",
    "https://web.archive.org:443/web/123",
    "https://web.archive.org:8443/web/123",
    "https://web.archive.org:/web/123",
    "https://web.archive.org:bad/web/123",
    "https://web.archive.org:99999/web/123",
    "https://user@web.archive.org/web/123",
    "https://user:pass@web.archive.org/web/123",
    "https://@web.archive.org/web/123",
    " https://web.archive.org/web/123",
    "https://web.archive.org/web/123 ",
    "https://web.archive.org/web/1 23",
    "https://web.archive.org/web/1\t23",
    "https://web.archive.org/web/1\n23",
    "https://[::1]/web/123",
    "https://[::1/web/123",
    "https://sub.web.archive.org/web/123",
    "https://web.archive.org./web/123",
    "https://web.archive.org\\web/123",
    "javascript:alert(1)",
    "",
  ];
  for (const url of rejectedUrls) {
    assert.equal(isAllowedArchiveUrl(url, "web.archive.org"), false, `Expected false for ${url}`);
  }

  for (const badHost of [null, undefined, "", "   ", 123, {}]) {
    assert.equal(isAllowedArchiveUrl("https://web.archive.org/web/123", badHost), false);
  }
  for (const badUrl of [null, undefined, 123, {}]) {
    assert.equal(isAllowedArchiveUrl(badUrl, "web.archive.org"), false);
  }
});

test("validateAttributionLink permits http/https without userinfo or whitespace", () => {
  assert.equal(validateAttributionLink("https://creativecommons.org/licenses/by/4.0/"), true);
  assert.equal(validateAttributionLink("http://example.org/docs?v=1#top"), true);
  assert.equal(validateAttributionLink("http://localhost:8000/license"), true);

  for (const bad of [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "ftp://example.com/file",
    "https:example.com/docs",
    "https://user@example.com/docs",
    "https://@example.com/docs",
    " https://example.com/docs",
    "https://example.com/docs ",
    "https://example.com/a b",
    "https://example.com/a\nb",
    "",
    null,
    undefined,
    42,
  ]) {
    assert.equal(validateAttributionLink(bad), false, `Expected false for ${String(bad)}`);
  }
});

test("validateComparisonPayload accepts valid Cloudflare, handwritten, and incomplete payloads", () => {
  const cf = validateComparisonPayload(makeCloudflareComparison());
  assert.equal(cf.sample_id, "cloudflare-ai-crawl-control");
  assert.equal(cf.summary.distinct_new_words, 1358);

  const hw = validateComparisonPayload(makeHandwrittenComparison());
  assert.equal(hw.archive_host, null);
  assert.equal(hw.attribution, null);

  const withIncompleteAndStrayLink = validateComparisonPayload(
    makeCloudflareComparison({
      summary: { compared_pages: 1, excluded_pages: 1, distinct_new_words: 10 },
      pages: [
        {
          url: "https://developers.cloudflare.com/ai-crawl-control/",
          status: "compared",
          new_words: 10,
          earlier_capture_url: "https://evil.example/x",
          later_capture_url: "https://web.archive.org:443/web/123",
        },
        {
          url: "https://developers.cloudflare.com/ai-crawl-control/broken/",
          status: "comparison_incomplete",
          new_words: null,
          earlier_capture_url: null,
          later_capture_url: null,
        },
      ],
    }),
  );
  assert.equal(withIncompleteAndStrayLink.pages.length, 2);
});

test("validateComparisonPayload rejects malformed roots, commits, counts, statuses, and duplicates", () => {
  assert.throws(() => validateComparisonPayload(null), /object/i);
  assert.throws(() => validateComparisonPayload([]), /object/i);

  const missingKey = makeCloudflareComparison();
  delete missingKey.pages;
  assert.throws(() => validateComparisonPayload(missingKey), /root keys/i);

  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ extra: 1 })),
    /root keys/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ schema_version: 2 })),
    /schema_version/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ schema_version: true })),
    /schema_version/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ producing_commit: "abc" })),
    /producing_commit/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ producing_commit: "A".repeat(40) })),
    /producing_commit/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ manifest_sha256: "short" })),
    /manifest_sha256/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ archive_host: "" })),
    /archive_host/i,
  );
  assert.throws(
    () => validateComparisonPayload(makeCloudflareComparison({ attribution: "CC BY 4.0" })),
    /attribution/i,
  );
  assert.throws(
    () =>
      validateComparisonPayload(
        makeCloudflareComparison({
          summary: { compared_pages: true, excluded_pages: 0, distinct_new_words: 1358 },
        }),
      ),
    /compared_pages/i,
  );
  assert.throws(
    () =>
      validateComparisonPayload(
        makeCloudflareComparison({
          summary: { compared_pages: 2, excluded_pages: 0, distinct_new_words: 999 },
        }),
      ),
    /distinct_new_words/i,
  );
  assert.throws(
    () =>
      validateComparisonPayload(
        makeCloudflareComparison({
          summary: { compared_pages: 2, excluded_pages: 0, distinct_new_words: 1401 },
        }),
      ),
    /distinct_new_words/i,
  );

  const dupPages = makeHandwrittenComparison();
  dupPages.pages[1].url = dupPages.pages[0].url;
  assert.throws(() => validateComparisonPayload(dupPages), /url/i);

  const negativeWords = makeHandwrittenComparison({
    summary: { compared_pages: 2, excluded_pages: 0, distinct_new_words: 0 },
  });
  negativeWords.pages[0].new_words = -1;
  assert.throws(() => validateComparisonPayload(negativeWords), /new_words/i);

  const incompleteWithNumber = makeHandwrittenComparison({
    summary: { compared_pages: 1, excluded_pages: 1, distinct_new_words: 1 },
  });
  incompleteWithNumber.pages[1].status = "comparison_incomplete";
  incompleteWithNumber.pages[1].new_words = 0;
  assert.throws(() => validateComparisonPayload(incompleteWithNumber), /new_words/i);

  const badStatus = makeHandwrittenComparison();
  badStatus.pages[0].status = "ok";
  assert.throws(() => validateComparisonPayload(badStatus), /status/i);

  const badCaptureType = makeHandwrittenComparison();
  badCaptureType.pages[0].earlier_capture_url = 123;
  assert.throws(() => validateComparisonPayload(badCaptureType), /earlier_capture_url/i);
});

test("filterAndSortPages filters by query and status and sorts deterministically", () => {
  const pages = [
    { url: "https://example.invalid/z-zero", status: "compared", new_words: 0, earlier_capture_url: null, later_capture_url: null },
    { url: "https://example.invalid/b-incomplete", status: "comparison_incomplete", new_words: null, earlier_capture_url: null, later_capture_url: null },
    { url: "https://example.invalid/b-tie", status: "compared", new_words: 5, earlier_capture_url: null, later_capture_url: null },
    { url: "https://example.invalid/a-tie", status: "compared", new_words: 5, earlier_capture_url: null, later_capture_url: null },
    { url: "https://example.invalid/a-incomplete", status: "comparison_incomplete", new_words: null, earlier_capture_url: null, later_capture_url: null },
    { url: "https://example.invalid/top", status: "compared", new_words: 42, earlier_capture_url: null, later_capture_url: null },
  ];
  const snapshot = pages.map((p) => p.url);

  const desc = filterAndSortPages(pages, { sortBy: "new_words_desc" });
  assert.deepEqual(
    desc.map((p) => p.url),
    [
      "https://example.invalid/top",
      "https://example.invalid/a-tie",
      "https://example.invalid/b-tie",
      "https://example.invalid/z-zero",
      "https://example.invalid/a-incomplete",
      "https://example.invalid/b-incomplete",
    ],
  );

  const asc = filterAndSortPages(pages, { sortBy: "new_words_asc" });
  assert.deepEqual(
    asc.map((p) => p.url),
    [
      "https://example.invalid/z-zero",
      "https://example.invalid/a-tie",
      "https://example.invalid/b-tie",
      "https://example.invalid/top",
      "https://example.invalid/a-incomplete",
      "https://example.invalid/b-incomplete",
    ],
  );

  const byUrl = filterAndSortPages(pages, { sortBy: "url_asc" });
  assert.deepEqual(
    byUrl.map((p) => p.url),
    [
      "https://example.invalid/a-incomplete",
      "https://example.invalid/a-tie",
      "https://example.invalid/b-incomplete",
      "https://example.invalid/b-tie",
      "https://example.invalid/top",
      "https://example.invalid/z-zero",
    ],
  );

  const onlyTieQuery = filterAndSortPages(pages, { query: " TIE ", statusFilter: "compared" });
  assert.deepEqual(
    onlyTieQuery.map((p) => p.url),
    ["https://example.invalid/a-tie", "https://example.invalid/b-tie"],
  );

  const onlyIncomplete = filterAndSortPages(pages, { statusFilter: "comparison_incomplete" });
  assert.deepEqual(
    onlyIncomplete.map((p) => p.url),
    ["https://example.invalid/a-incomplete", "https://example.invalid/b-incomplete"],
  );

  assert.deepEqual(
    pages.map((p) => p.url),
    snapshot,
    "filterAndSortPages must not mutate the input array",
  );
});

test("buildReproduceInfo formats GitHub links and guards unsafe sample_id values", () => {
  const info = buildReproduceInfo(makeCloudflareComparison());
  assert.equal(info.repoUrl, "https://github.com/youzaina001/geocrawl");
  assert.equal(info.treeUrl, `https://github.com/youzaina001/geocrawl/tree/${COMMIT_A}`);
  assert.equal(
    info.manifestUrl,
    `https://github.com/youzaina001/geocrawl/blob/${COMMIT_A}/fixtures/cloudflare-ai-crawl-control/manifest.json`,
  );
  assert.equal(info.shortCommit, COMMIT_A.slice(0, 12));
  assert.equal(info.demoCommand, `git checkout ${COMMIT_A} && make demo`);

  for (const unsafeId of ["../secret", "a/b", "Bad_Id", "", "x..y"]) {
    const unsafeInfo = buildReproduceInfo(
      makeCloudflareComparison({ sample_id: unsafeId }),
      "https://github.com/youzaina001/geocrawl/",
    );
    assert.equal(unsafeInfo.manifestUrl, null, `Expected null manifestUrl for ${unsafeId}`);
    assert.equal(unsafeInfo.repoUrl, "https://github.com/youzaina001/geocrawl");
  }

  assert.throws(
    () => buildReproduceInfo(makeCloudflareComparison({ producing_commit: "bad" })),
    /producing_commit/i,
  );
  assert.throws(
    () => buildReproduceInfo(makeCloudflareComparison(), "javascript:alert(1)"),
    /repoBaseUrl/i,
  );
});

test("static explorer assets are self-contained, free of innerHTML, and expose required hooks", () => {
  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const explorerDir = path.join(repoRoot, "explorer");
  const htmlPath = path.join(explorerDir, "index.html");
  const cssPath = path.join(explorerDir, "styles.css");
  const jsPath = path.join(explorerDir, "app.js");

  const html = fs.readFileSync(htmlPath, "utf8");
  const css = fs.readFileSync(cssPath, "utf8");
  const js = fs.readFileSync(jsPath, "utf8");

  assert.match(html, /<link\b[^>]*href=["']\.\/styles\.css["'][^>]*>/i);
  assert.match(html, /<script\b[^>]*src=["']\.\/app\.js["'][^>]*>/i);

  assert.doesNotMatch(html, /<(script|link|img|iframe)\b[^>]*\b(src|href)=["']https?:\/\//i);
  assert.doesNotMatch(css, /@import\s+(?:url\()?["']?https?:\/\//i);
  assert.doesNotMatch(css, /url\(["']?https?:\/\//i);
  assert.doesNotMatch(js, /https?:\/\//i);

  assert.doesNotMatch(js, /\.innerHTML\s*=/);
  assert.doesNotMatch(js, /\binsertAdjacentHTML\b/);
  assert.doesNotMatch(js, /\bdocument\.write\b/);

  for (const attr of [
    "data-summary-words",
    "data-window-range",
    "data-compared-count",
    "data-excluded-count",
    "data-reproduce-link",
    "data-page-detail",
    "data-error-banner",
  ]) {
    assert.ok(html.includes(attr), `index.html missing required attribute ${attr}`);
  }

  for (const attr of ["data-page-row", "data-capture-fallback"]) {
    assert.ok(
      html.includes(attr) || js.includes(attr),
      `explorer UI missing required attribute ${attr}`,
    );
  }

  assert.match(html, /aria-live=["']polite["']/i);
  assert.doesNotMatch(html + css + js, /[\u2013\u2014]/, "UI files must not use em or en dashes");
});
