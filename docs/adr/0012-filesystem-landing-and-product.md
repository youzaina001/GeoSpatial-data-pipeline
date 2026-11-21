# Local Landing and Product live on a filesystem with S3-shaped keys

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

The $0 data plane does not require MinIO or Minikube. Keys look like an object store (landing/…, product/field_days/date=…/) so DuckDB and a future S3 backend can share a layout. A second cluster backend is not in v1.
