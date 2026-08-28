# A season of Field-days is produced by one CLI backfill

`run --from --to` (or equivalent) walks the fixture calendar, idempotent per date. That is the demo that fills the Product table. Airflow, if shown, wraps a single date of the same pipeline.
