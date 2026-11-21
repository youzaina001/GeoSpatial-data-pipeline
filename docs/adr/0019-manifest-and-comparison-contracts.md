# Shared input manifest and split comparison contracts

Both real archived samples (such as Cloudflare AI Crawl Control) and the synthetic handwritten check flow through one `manifest.json` input contract, one DuckDB-validated publication path, and two distinct JSON outputs: a minimal public `comparison.json` and a separate maintainer `run-summary.json`.

## Shared input manifest

Each sample directory contains a `manifest.json` declaring `sample_id`, `earlier_window`, `later_window`, `archive_host` (for example `"web.archive.org"`, or `null` for synthetic samples), optional `attribution` (license, authors, source link, and fixture modifications for CC BY 4.0 compliance), and lists of `earlier` and `later` capture entries.

Each capture entry is a JSON object and records `page_url`, `replay_url`, `captured_at` (UTC ISO-8601), and either:

* `file` and `sha256` for a bundled article HTML capture, or
* `load_error` (`failed_step` and `reason`) when a capture failed to load (`comparison_incomplete`).

Before prose extraction starts, the pipeline verifies every bundled HTML file against its recorded SHA-256 checksum and computes `manifest_sha256`. It keeps the verified bytes and extracts prose from them, so a file cannot change between the check and extraction. A bundled file must be UTF-8. Any malformed entry, missing file, checksum mismatch or decoding error fails the run before a candidate is written.

## Split public and maintainer outputs

* **Public `comparison.json`** carries `schema_version`, `sample_id`, `producing_commit`, `manifest_sha256`, `earlier_window`, `later_window`, `archive_host`, `attribution`, `summary` (`compared_pages`, `excluded_pages`, `distinct_new_words`), and `pages` (`url`, `status`, `new_words`, `earlier_capture_url`, `later_capture_url`). It never includes passage text, scraped HTML, or internal pipeline error messages.
* **Maintainer `run-summary.json`** stays out of the public site bundle. It records `run_id`, `status` (`succeeded` or `failed`), `producing_commit`, `manifest_sha256`, the candidate figures (both windows, pages compared and excluded, distinct new words) and excluded-page diagnostics (`url`, `captured_at`, `failed_step`, `reason`). A failed run records `error` (`failed_step` and `reason`) in place of candidate figures.

## Folder layout

* `crawl build --manifest <manifest> --runs-dir <runs>` writes `<runs>/<UTC time>-<commit>/comparison.json` and `run-summary.json`, for example under `data/crawl/runs/`. The UTC time has microsecond precision, so run folders sort by start time and never collide.
* `crawl promote <run> --publish-dir <site> --yes` copies the candidate to `<site>/releases/<commit>/` and then replaces `<site>/comparison.json`. A release folder can itself be promoted, which is how a rollback works. Promotion refuses a run without a valid `comparison.json`, such as a failed run, and refuses to overwrite a release folder that holds a different comparison for the same commit.

## Host allowlist and atomic publication

When `archive_host` is set (such as `"web.archive.org"`), every non-null capture link must parse as an absolute `https` URL with no userinfo, no explicit port and an exact `hostname == archive_host` match. A link that fails to parse, for example because of an invalid port or IPv6 literal, is disallowed. The pipeline enforces this check before writing a candidate, and the explorer enforces the same rule again before rendering clickable links (showing "Capture link unavailable" if malformed or disallowed).

`crawl build` writes each file in a run folder through a sibling temporary file and an atomic `os.replace`, only after DuckDB integrity checks pass. `crawl promote` writes the published `comparison.json` the same way. If any step fails, the previously published `comparison.json` remains intact.
