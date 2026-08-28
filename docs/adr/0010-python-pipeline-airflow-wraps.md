# The unit of work is a Python pipeline; Airflow only wraps it

Landing and Product for a date are built by a CLI/module that tests can call. One Airflow DAG invokes that same pipeline. Two DAGs plus a poke sensor are not the architecture. Databricks does not recompute rasters; it loads a Product snapshot for SQL.
