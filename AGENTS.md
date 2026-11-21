# geocrawl

## Navigation

- Read `GLOSSARY.md` for domain terms: new prose, new passages, visible prose, candidates and releases.
- Read `docs/adr/` for architectural boundaries. `0016` to `0019` cover crawl freshness: archived sources and offline fixtures (`0016`), build and promote publication (`0017`), the prose matching rule and DuckDB metrics (`0018`), and the manifest and output contracts (`0019`). `0021` archives the satellite example and `0022` names the project `geocrawl`. `0001` (portfolio, not operations) still applies. `0002` to `0015` and `0020` are archived with the satellite example.
- The archived satellite example (code, fixtures, Airflow DAG, Databricks bundle, tests, glossary) lives under `archive/v1-satellite/`, and the Kubernetes prior art under `archive/v0/`. Neither is installed, tested or type checked.
- Crawl freshness code lives under `src/geocrawl/`: `cli.py` (`geocrawl build`, `promote` and `demo`), `manifest.py` (manifest loading, checksums, archive host allowlist), `extract.py` (visible prose), `matching.py` (word runs), `metrics.py` (DuckDB metrics and checks) and `publish.py` (commit stamping, build, promote, demo). Its fixtures are `fixtures/handwritten/` and `fixtures/cloudflare-ai-crawl-control/`, and its tests are `tests/test_crawl_*.py`.

## Local verification

- `make check`: runs `pytest tests/` (`test`), `ruff check` (`lint` on `src/ tests/`) and `mypy src/ tests/` (`typecheck`).
- `make demo`: builds offline candidate comparisons for the handwritten and Cloudflare fixtures under `data/demo/`. It refuses to run when either fixture folder has uncommitted changes.
- CI workflow lives in `.github/workflows/ci.yml` (`local-demo` job: install, check, crawl demo).

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context domain docs live in `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
