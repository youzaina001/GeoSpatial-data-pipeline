# Local Airflow and the Databricks notebook are not one DAG

The $0 path is Airflow (or a local CLI) writing Landing and Product against MinIO, plus a separate Databricks Free Edition notebook that loads the Field-day table for SQL. Coupling Airflow to Databricks is the optional paid glue path, not the clone default.
