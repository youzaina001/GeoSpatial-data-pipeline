# ADR 0008 applies to the satellite pipeline only

[ADR 0008](0008-local-parquet-is-the-product.md) says the Product is local Parquet and that JSON reports are not the product. That decision was made for the satellite Field-day pipeline, where Parquet partitions are the data product and a JSON report would be a second, competing contract.

The crawl freshness pipeline publishes a static `comparison.json` that the visitor's browser loads ([ADR 0017](0017-serve-precomputed-comparisons.md), [ADR 0019](0019-manifest-and-comparison-contracts.md)). That file is the crawl freshness product. It is not a report about a Parquet product.

ADR 0008 therefore governs the satellite pipeline only: `Field-day` Parquet under `data/product/` and its Databricks SQL load. It does not restrict the crawl freshness outputs, which are `comparison.json` for visitors and `run-summary.json` for maintainers. The crawl freshness pipeline uses DuckDB in memory to validate and aggregate, and it writes no Parquet.
