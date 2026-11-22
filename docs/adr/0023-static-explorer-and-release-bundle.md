# Static explorer and unified release bundle

Portfolio visitors browse the published comparison in a zero-build static explorer under `explorer/`, and `geocrawl promote` packages and rolls back those explorer assets alongside `comparison.json` as one release unit ([ADR 0017](0017-serve-precomputed-comparisons.md), [ADR 0019](0019-manifest-and-comparison-contracts.md)).

## Zero-build static explorer

The explorer lives under `explorer/` (`index.html`, `styles.css`, `app.js`, and a DOM-free ES module `lib.js`). `index.html` also loads `theme.css` after `styles.css`. It ships without rules, so a site that hosts the explorer can replace that one file to restyle the page while every other file stays identical to the release. Picking plain HTML, CSS, and vanilla ES modules over a bundler toolchain (such as Vite or Astro) keeps `geocrawl` a single `uv` install with no `npm` build step and zero external CDN stylesheets, scripts, or web fonts.

At runtime, `app.js` fetches `./comparison.json` with `cache: "no-store"`, validates the root schema, counts, statuses, and hexadecimal identifiers through `validateComparisonPayload` (`schema_version == 1`), and builds every element with `document.createElement` and `textContent` rather than `innerHTML`.

* **First screen and provenance**: Shows `summary.distinct_new_words`, `earlier_window`, `later_window`, `compared_pages`, `excluded_pages`, a `"Reproduce this result"` link pointing to `producing_commit`, the manifest checksum and link, the local `make demo` command, and source attribution (such as CC BY 4.0) when present.
* **Interactive drill-down and allowlist enforcement**: Visitors can filter pages by URL substring, filter by comparison status, sort deterministically, and select a page to inspect its new word count and archive links. `isAllowedArchiveUrl` checks raw authority substrings before browser `URL` normalization so non-`https:` schemes, userinfo, whitespace, disallowed hosts, and explicit ports (including `:443`) are rejected and displayed as `"Capture link unavailable"`, while `null` captures display `"Not captured"`. Malformed or missing `comparison.json` displays a visible alert banner without throwing uncaught page errors.

## Unified release bundle and rollback

`geocrawl promote <run> --publish-dir <site> [--explorer-dir <dir>] [--yes]` writes the explorer bundle and `comparison.json` into `<site>/releases/<commit>/` first, then swaps both atomically into `<site>/`:

1. Each release directory records managed relative explorer file paths inside a hidden `.bundle-manifest.json`, keeping `<site>/` root free of bundle metadata. Symlinks, special files, missing or empty `index.html`, and reserved root names (`comparison.json`, `run-summary.json`, `releases`) are rejected before any published file is touched.
2. Re-promoting the same commit verifies byte-for-byte equality across `comparison.json` and every file in the release bundle, aborting on any mismatch.
3. Rolling back by promoting `<site>/releases/<old-commit>` defaults `--explorer-dir` to that release directory, restoring the matching interface and `comparison.json` together. If updating `comparison.json` fails, modified active files are restored; obsolete managed files from the prior release are removed only after `comparison.json` swaps successfully, leaving unmanaged files (such as `robots.txt`) untouched.

## Verification split

Pure logic in `explorer/lib.js` and static bundle guarantees are unit-tested with Node's built-in test runner (`node --test tests/test_explorer.mjs`, via `make test-explorer`, included in `make check` when `node` is on `PATH` and invoked explicitly in CI).

End-to-end browser behavior is verified in headless Google Chrome over WebSocket DevTools (`tests/browser_check.mjs`, via `make test-browser`) using Node built-in modules only. It checks a promoted Cloudflare demo bundle, keyboard selection, search, status and sort controls, tampered capture links, malformed JSON error handling, and zero horizontal overflow across `1440x900`, `390x844`, and `320x720` viewports.

## Local preview and deployment boundary

`make preview` builds the offline demo (`make demo`), promotes the latest Cloudflare candidate into `data/site/`, and serves it locally on `127.0.0.1` via `python -m http.server` for maintainer inspection.

For public hosting (such as manual upload to Cloudflare Pages with `wrangler pages deploy`), copy only the active files from `<site>/` excluding `<site>/releases/` into a staging directory so release history remains in the maintainer workspace rather than on the public edge. Provisioning a live Cloudflare Pages project and automated cloud deployment remain out of scope.
