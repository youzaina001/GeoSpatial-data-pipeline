# A season of Field-days is produced by one CLI backfill

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

`run --from --to` (or equivalent) walks the fixture calendar, idempotent per date. That is the demo that fills the Product table. Airflow, if shown, wraps a single date of the same pipeline.
