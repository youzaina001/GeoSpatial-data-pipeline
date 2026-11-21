# GeoPipeline

## Navigation

- Read `GLOSSARY.md` for domain terms. The crawl freshness section defines new prose, new passages, visible prose, candidates and releases. The satellite section defines `AOI`, `NDVI`, `Field`, `Field master`, `Field-day`, `Eligible`, `Scene`, `Scene catalog`, `Landing` and `Product`.
- Read `docs/adr/` (`0001` through `0020`) for architectural boundaries. `0001` to `0015` cover the satellite pipeline. `0016` to `0019` cover crawl freshness: archived sources and offline fixtures (`0016`), build and promote publication (`0017`), the prose matching rule and DuckDB metrics (`0018`), and the manifest and output contracts (`0019`). `0020` limits `0008` to the satellite pipeline.
- Satellite pipeline code lives under `src/geopipeline/` (outside `crawl/`), checked-in fixtures under `fixtures/`, Airflow DAG wrapper in `dags/field_days_dag.py`, tests under `tests/`, and optional Databricks SQL files under `databricks/`.
- Crawl freshness code lives under `src/geopipeline/crawl/`: `manifest.py` (manifest loading, checksums, archive host allowlist), `extract.py` (visible prose), `matching.py` (word runs), `metrics.py` (DuckDB metrics and checks) and `publish.py` (commit stamping, build, promote, demo). Its fixtures are `fixtures/handwritten/` and `fixtures/cloudflare-ai-crawl-control/`, and its tests are `tests/test_crawl_*.py`.

## Local verification

- `make check`: runs `pytest tests/` (`test`), `ruff check` (`lint` on `src/ dags/ tests/`), `mypy src/ dags/ tests/` (`typecheck`), and the DAG wrapper check (`validate`). Note `pytest` skips the live Airflow import test unless `--extra airflow` is installed.
- `make crawl-demo`: builds offline candidate comparisons for the handwritten and Cloudflare fixtures under `data/crawl-demo/`. It refuses to run when either fixture folder has uncommitted changes.
- `make test-airflow`: verifies `dags/field_days_dag.py` imports under Airflow (`apache-airflow`).
- CI workflow lives in `.github/workflows/ci.yml` (`local-demo` and `airflow-dag-import` jobs).

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues. Use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context domain docs live in `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
