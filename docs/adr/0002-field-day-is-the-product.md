# The data product is a Field-day table

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

Interviewers look at a queryable table (one row per Field per date), not a MinIO JSON report. Databricks SQL exists because this table exists. Fields therefore need stable identities across dates; regenerating farms from a seed each run is incompatible with the product.
