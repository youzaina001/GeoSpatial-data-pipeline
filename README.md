# GeoPipeline

Synthetic satellite Scenes over an AOI become a **Field-day** table (one row
per Field per date) with a real status and, when the Scene is usable,
polygon-masked NDVI.

See [`CONTEXT.md`](CONTEXT.md) for the glossary and [`docs/adr/`](docs/adr/)
for design decisions.

## What you get after a clone

Use Python 3.12 or newer, [uv](https://docs.astral.sh/uv/getting-started/installation/)
and Make. From a terminal:

```bash
git clone https://github.com/youzaina001/GeoSpatial-data-pipeline.git
cd GeoSpatial-data-pipeline
make install  # frozen dependencies, including development tools
make run      # 2024-04-01 → 2024-05-15 into data/
make query    # DuckDB over local Parquet
make test
make lint
```

No Minikube, no AWS account, no Databricks workspace. The same Python is what
the Airflow DAG calls; nobody has to start a scheduler.

The fixture season produces 45 Parquet partitions and 900 unique Field-days.
The status totals are 114 ineligible, 108 missing-scene, 122 cloudy and 556
observed. Only the observed rows have NDVI. The query prints counts by date
and status. Rerunning a date replaces that date's output.

## The product

Grain: `(field_id, date)`. Status, in this order:

1. **ineligible** — date is before the Field's planting date
2. **missing-scene** — no Scene for that date
3. **cloudy** — Scene is cloudy
4. **observed** — NDVI over the Field polygon

Only observed rows have NDVI. A rerun of a date overwrites that date's Product
(late Scene, not SCD2).

Checked-in fixtures, not a random seed:

- [`fixtures/field_master.geojson`](fixtures/field_master.geojson) — 20 Fields, stable IDs
- [`fixtures/scene_catalog.json`](fixtures/scene_catalog.json) — 45 calendar dates, present / cloudy / missing

## Layout

Local Landing and Product use S3-shaped keys on the filesystem
([ADR 0012](docs/adr/0012-filesystem-landing-and-product.md)):

```
data/landing/fields/field_master.geojson
data/landing/scenes/date=2024-04-16/scene.tif
data/landing/scenes/date=2024-04-16/scene.json
data/product/field_days/date=2024-04-16/part.parquet
```

Two layers, not bronze/silver/gold
([ADR 0005](docs/adr/0005-two-layers-not-medallion.md)).

## CLI

```bash
uv run geopipeline run --from 2024-04-01 --to 2024-05-15 --data-root data
uv run geopipeline query --data-root data
uv run geopipeline query --data-root data --sql "SELECT status, count(*) FROM field_days GROUP BY 1"
```

## Airflow

[`dags/field_days_dag.py`](dags/field_days_dag.py) is one DAG with one task:
`run_scheduled_date(ds)`. That function is unit-tested without a scheduler
(and the DAG file imports if you `uv sync --extra airflow`). It is not wired
to Databricks.

## Databricks Free Edition

Optional: `make databricks` runs the fixture-season backfill and then
`databricks bundle deploy`. That pushes the existing notebook/SQL plus the
gitignored local Product. It does not recompute rasters. Parquet is not in
git. Clone-default does not need the Databricks CLI. Local files and Free
Edition are two sandboxes, not one lake
([ADR 0003](docs/adr/0003-split-sandboxes.md),
[ADR 0011](docs/adr/0011-paid-glue-is-not-v1.md)).

## Out of v1

Paid S3↔Databricks glue, MWAA, EKS, real Sentinel/STAC, medallion layers,
always-on AWS. Kubernetes is prior art under [`archive/v0/`](archive/v0/)
— not a supported run
([ADR 0014](docs/adr/0014-kubernetes-is-prior-art.md),
[ADR 0015](docs/adr/0015-no-live-k8s-dag-as-code.md)).

## Tests

```bash
make test
```

Seams: `run()` (status order, backfill, Landing/Product, overwrite),
`ndvi_over_geometry` (polygon mask), CLI, DuckDB query, DAG wrap.

## Stack

| Piece        | Role                                      |
| ------------ | ----------------------------------------- |
| Python 3.12+ | Pipeline, CLI                             |
| rasterio     | Synthetic GeoTIFF + polygon mask          |
| PyArrow      | Field-day Parquet                         |
| DuckDB       | Local SQL over Product                    |
| Airflow 3    | Optional DAG that calls `run_date`        |
| Databricks   | SQL over an uploaded local Product        |
