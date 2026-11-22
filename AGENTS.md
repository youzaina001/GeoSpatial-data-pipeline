# geocrawl

## Navigation

- Read `GLOSSARY.md` for domain terms: new prose, new passages, visible prose, candidates and releases.
- Read `docs/adr/` for architectural boundaries: `0001-portfolio-not-operations.md` (portfolio, not operations), `0016-compare-archived-crawls.md` (archived sources and offline fixtures), `0017-serve-precomputed-comparisons.md` (build and promote publication), `0018-python-and-duckdb.md` (prose matching rule and DuckDB metrics), `0019-manifest-and-comparison-contracts.md` (manifest and output contracts), `0021-archive-the-satellite-example.md` (archives the satellite example), `0022-name-the-project-geocrawl.md` (names the project `geocrawl`), and `0023-static-explorer-and-release-bundle.md` (static explorer and unified release bundle). `0002` to `0015` and `0020` are archived with the satellite example.
- The archived satellite example (code, fixtures, Airflow DAG, Databricks bundle, tests, glossary) lives under `archive/v1-satellite/`, and the Kubernetes prior art under `archive/v0/`. Neither is installed, tested or type checked.
- Crawl freshness code lives under `src/geocrawl/`: `cli.py` (`geocrawl build`, `promote` and `demo`), `manifest.py` (manifest loading, checksums, archive host allowlist), `extract.py` (visible prose), `matching.py` (word runs), `metrics.py` (DuckDB metrics and checks) and `publish.py` (commit stamping, build, promote, demo). Its fixtures are `fixtures/handwritten/` and `fixtures/cloudflare-ai-crawl-control/`, and its Python tests are `tests/test_crawl_*.py`.
- The static comparison explorer lives under `explorer/` (`index.html`, `styles.css`, `theme.css`, `app.js`, `lib.js`: zero-build HTML, CSS and ES modules; `theme.css` is an empty slot a hosting site replaces). Its Node unit tests live in `tests/test_explorer.mjs` and its headless Chrome DevTools suite in `tests/browser_check.mjs` (backed by `tests/cdp_driver.mjs`).

## Local verification

- `make check`: runs `pytest tests/` (`test`), `ruff check` (`lint` on `src/ tests/`), `mypy src/ tests/` (`typecheck`) and `test-explorer` (when `node` is on `PATH`).
- `make test-explorer`: runs `node --check` on `explorer/app.js`, `explorer/lib.js`, `tests/cdp_driver.mjs`, `tests/browser_check.mjs`, plus `node --test tests/test_explorer.mjs` when `node` is on `PATH`.
- `make test-browser`: runs `node tests/browser_check.mjs` against headless Google Chrome (requires Node >= 22 for global `WebSocket`).
- `make demo`: builds offline candidate comparisons for the handwritten and Cloudflare fixtures under `data/demo/`. It refuses to run when either fixture folder has uncommitted changes.
- `make preview`: builds the offline demo, promotes the latest Cloudflare candidate into `data/site/`, and serves it locally via `python -m http.server`.
- Use `uv run python` (or `uv run pytest`, `uv run geocrawl`) for ad-hoc Python one-liners instead of bare `python3`, which can resolve to a parent workspace virtualenv without project dependencies.
- CI workflow lives in `.github/workflows/ci.yml` (`local-demo` job: install, check, crawl demo, headless Chrome browser checks).

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context domain docs live in `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
