# Local Landing and Product live on a filesystem with S3-shaped keys

The $0 data plane does not require MinIO or Minikube. Keys look like an object store (landing/…, product/field_days/date=…/) so DuckDB and a future S3 backend can share a layout. A second cluster backend is not in v1.
