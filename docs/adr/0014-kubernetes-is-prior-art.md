# Kubernetes is prior art, not a v1 demo

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

The interview opener is the lakehouse path (CLI backfill, local Parquet, DuckDB, Databricks SQL). Airflow-on-Minikube was the old hero. We will not build a production image or keep Helm as a supported run in this refactor; the README bullet can mention that history. A two-backend cluster path is out of scope until someone owns an image.
