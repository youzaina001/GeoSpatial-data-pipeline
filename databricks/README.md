# Databricks Free Edition

Local Airflow (or the CLI) and this notebook are not one DAG. See
`docs/adr/0006-airflow-and-databricks-are-separate.md` and
`docs/adr/0011-paid-glue-is-not-v1.md`.

## What to upload

`data/product/field_days` after `make run` (2024-04-01 … 2024-05-15).
That directory is gitignored. Same grain as local DuckDB.

## What to run

1. `make run`
2. Upload `data/product/field_days` to DBFS (`/FileStore/field_days`) or a
   volume, or deploy it with a Databricks bundle.
3. Import `query_field_days.py` as a workspace notebook, or paste
   `query_field_days.sql` into a SQL editor.
4. Point `product_path` / the `parquet.\`…\`` path at the upload.

Do not recompute rasters in the workspace. Databricks Free Edition cannot mount
this repo's object storage as workspace storage.
