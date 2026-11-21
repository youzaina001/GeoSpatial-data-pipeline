# Local MinIO and Databricks Free Edition are not one lake

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

Databricks Free Edition cannot use our object storage as workspace storage and restricts outbound internet. The $0 path is local Airflow plus MinIO, and a separate Free Edition SQL table loaded for the demo. An optional paid script may glue S3 to a real workspace for one run, then tear down. Diagrams must not show a unified bronze-to-silver lake unless that paid path actually ran.
