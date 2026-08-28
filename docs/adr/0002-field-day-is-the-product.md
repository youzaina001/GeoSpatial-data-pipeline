# The data product is a Field-day table

Interviewers look at a queryable table (one row per Field per date), not a MinIO JSON report. Databricks SQL exists because this table exists. Fields therefore need stable identities across dates; regenerating farms from a seed each run is incompatible with the product.
