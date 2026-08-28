# Databricks Free Edition

Local Airflow (or the CLI) and this notebook are not one DAG. See
`docs/adr/0006-airflow-and-databricks-are-separate.md` and
`docs/adr/0011-paid-glue-is-not-v1.md`.

Workspace host and auth come from your Databricks CLI profile, not from
this repo. Clone-default remains `uv sync && make run && make query`.

## What to run

Needs the Databricks CLI and a local Field-day Product. The Product is
`data/product/field_days` after `make run` (2024-04-01 … 2024-05-15). That
directory is gitignored. Same grain as local DuckDB. A bundle deploy without
that directory is not a raster pipeline and will not invent Field-days.

From the repo root:

```
make databricks
```

That is `make run` then `databricks bundle deploy`. The bundle syncs
`query_field_days.py`, `query_field_days.sql`, and the local Product to
`/Workspace/Users/<you>/geopipeline/`. The notebook reads
`.../geopipeline/data/product/field_days`.

Do not recompute rasters in the workspace. Databricks Free Edition cannot mount
this repo's object storage as workspace storage.
