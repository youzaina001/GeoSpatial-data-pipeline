# GeoPipeline

GeoPipeline is a portfolio project demonstrating full-stack data engineering
and software engineering. A reviewer can follow an analytical question across
the data lifecycle, from ingestion to serving analytics, and inspect the
decisions and tests that make the answer trustworthy. The question guides
the choice of data.

The next project in this repository will measure crawl freshness for AI
training data. Its guiding question is how much [new prose](GLOSSARY.md#crawl-freshness) a later web
crawl adds to a candidate training corpus. The first release will compare
[October 2025 and April 2026 archive samples of Cloudflare's AI Crawl Control documentation](docs/adr/0016-compare-archived-crawls.md).
Visitors will [explore a comparison published by a maintainer](docs/adr/0017-serve-precomputed-comparisons.md).
A reviewer will be able to run the pipeline locally without cloud credentials.
One command will ingest two small, fixed archived samples, compare their prose,
and write the same file format the public explorer reads.
The [processing stack decision](docs/adr/0018-python-and-duckdb.md) describes how Python and DuckDB share that work.
Whether to rename this repository to reflect its crawl freshness focus is an open decision.

In the current example, synthetic satellite Scenes over an AOI become a **Field-day** table (one row
per Field per date) with a real status and, when the Scene is usable,
polygon-masked NDVI.

See [`GLOSSARY.md`](GLOSSARY.md) for the glossary and [`docs/adr/`](docs/adr/)
for design decisions.

## Crawl freshness

The crawl freshness pipeline compares two archived samples of one
documentation site and counts the [new prose](GLOSSARY.md#crawl-freshness)
in the later sample. It runs offline from bundled fixtures:

```bash
make install
make crawl-demo   # handwritten check plus four Cloudflare captures
```

`make crawl-demo` writes one candidate run per sample under
`data/crawl-demo/<sample>/runs/<UTC time>-<commit>/`, each with a public
`comparison.json` and a maintainer `run-summary.json`. The handwritten
sample must give one new word on each page and one distinct new word across
the crawl, or the demo fails before writing anything.

The demo and `crawl build` record the Git commit that produced the result.
They refuse to run when the fixture folder has uncommitted changes, so commit
any fixture edit first.

A maintainer publishes in two steps
([ADR 0017](docs/adr/0017-serve-precomputed-comparisons.md)):

```bash
uv run geopipeline crawl build --manifest fixtures/cloudflare-ai-crawl-control/manifest.json --runs-dir data/crawl/runs
uv run geopipeline crawl promote data/crawl/runs/<run> --publish-dir data/crawl/site          # preview only
uv run geopipeline crawl promote data/crawl/runs/<run> --publish-dir data/crawl/site --yes    # publish
```

`crawl promote` prints the candidate beside the current public figures (or
"first release") and replaces `comparison.json` only with `--yes`. Each
promoted comparison is kept under `releases/<commit>/`. To roll back, promote
an older release folder.

How prose is selected and matched is described in
[ADR 0018](docs/adr/0018-python-and-duckdb.md). File formats are in
[ADR 0019](docs/adr/0019-manifest-and-comparison-contracts.md).

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
(and `make test-airflow` verifies the real DAG import using `--extra airflow`).
It is not wired to Databricks.

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
make test-airflow  # verifies real Airflow 3 DAG import with --extra airflow
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
