# The Product is local Parquet; Databricks SQL is a demo load of the same grain

An interviewer with no cloud account queries Field-days via a local command (DuckDB or equivalent) over Parquet. Databricks Free Edition gets a table with that same grain for the SQL demo. JSON reports are not the product. The leftover tile-ingest path and Region config are deleted so there is one Landing contract.
