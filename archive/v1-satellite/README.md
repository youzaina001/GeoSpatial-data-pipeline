# v1: satellite Field-day example (archived)

This directory holds the satellite example that this repository supported until
November 2026: synthetic satellite Scenes over an AOI became a Field-day table
(one row per Field per date) with polygon-masked NDVI, local Parquet, DuckDB
queries, a one-task Airflow 3 DAG and an optional Databricks Free Edition bundle.

It is **not a supported run**. The code here is not installed, tested or type
checked, and the supported build no longer ships `numpy`, `pyarrow`,
`rasterio` or Airflow. See
[ADR 0021](../../docs/adr/0021-archive-the-satellite-example.md).

To run it as it last worked, check out commit `ea030f1`:

```bash
git switch --detach ea030f1
make install
make run query
```

- Design decisions: ADRs 0002 to 0015 and 0020 in [`docs/adr/`](../../docs/adr/).
- Domain terms: [`GLOSSARY.md`](GLOSSARY.md).
- The earlier Kubernetes version is in [`archive/v0/`](../v0/).
