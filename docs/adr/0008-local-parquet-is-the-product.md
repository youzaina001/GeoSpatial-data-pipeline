# The Product is local Parquet; Databricks SQL is a demo load of the same grain

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

An interviewer with no cloud account queries Field-days via a local command (DuckDB or equivalent) over Parquet. Databricks Free Edition gets a table with that same grain for the SQL demo. JSON reports are not the product. The leftover tile-ingest path and Region config are deleted so there is one Landing contract.
