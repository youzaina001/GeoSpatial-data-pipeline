# GeoPipeline

## Navigation

- Read `CONTEXT.md` for domain glossary terms (`AOI`, `NDVI`, `Field`, `Field master`, `Field-day`, `Eligible`, `Scene`, `Scene catalog`, `Landing`, `Product`) and `docs/adr/` (`0001` through `0015`) for architectural boundaries.
- Pipeline code lives under `src/geopipeline/`, checked-in fixtures under `fixtures/`, Airflow DAG wrapper in `dags/field_days_dag.py`, tests under `tests/`, and optional Databricks SQL files under `databricks/`.

## Local verification

- `make check`: runs `pytest tests/` (`test`), `ruff check` (`lint` on `src/ dags/ tests/`), `mypy src/ dags/ tests/` (`typecheck`), and the DAG wrapper check (`validate`). Note `pytest` skips the live Airflow import test unless `--extra airflow` is installed.
- `make test-airflow`: verifies `dags/field_days_dag.py` imports under Airflow (`apache-airflow`).
- CI workflow lives in `.github/workflows/ci.yml` (`local-demo` and `airflow-dag-import` jobs).
