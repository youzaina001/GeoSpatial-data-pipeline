# Local Airflow and the Databricks notebook are not one DAG

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

The $0 path is Airflow (or a local CLI) writing Landing and Product against MinIO, plus a separate Databricks Free Edition notebook that loads the Field-day table for SQL. Coupling Airflow to Databricks is the optional paid glue path, not the clone default.
