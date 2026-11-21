# Archive the satellite example

The repository now has one direction: crawl freshness with a public explorer ([ADR 0016](0016-compare-archived-crawls.md), [ADR 0017](0017-serve-precomputed-comparisons.md)). Keeping the satellite Field-day example in the supported build meant two installs, two demos and two glossaries for a first-time visitor, plus raster and Airflow dependencies the crawl pipeline never uses.

The satellite pipeline, its fixtures, the Airflow DAG, the Databricks bundle and their tests move to `archive/v1-satellite/`, beside the Kubernetes prior art in `archive/v0/`. The supported build drops `numpy`, `pyarrow`, `rasterio` and the `airflow` extra, the `run`, `query`, `validate`, `test-airflow` and `databricks` make targets, the `run` and `query` CLI commands, and the `airflow-dag-import` CI job.

The archive is a record, not a supported run. Its code still imports `geopipeline.pipeline` and is not tested or type checked. To run it, check out commit `ea030f1`, the last commit where it was supported.

ADRs 0002 to 0015 and 0020 stay in `docs/adr/` so their numbers and links keep working, each marked archived. ADR 0001 still applies: this is a portfolio, not an operational pipeline.
