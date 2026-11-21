# The unit of work is a Python pipeline; Airflow only wraps it

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

Landing and Product for a date are built by a CLI/module that tests can call. One Airflow DAG invokes that same pipeline. Two DAGs plus a poke sensor are not the architecture. Databricks does not recompute rasters; it loads a Product snapshot for SQL.
