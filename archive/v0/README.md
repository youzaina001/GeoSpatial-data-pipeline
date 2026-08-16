# v0 — Airflow on Minikube (prior art)

This directory is the previous portfolio demo: Terraform + Helm for Airflow and
MinIO on Minikube, two DAGs, and a tile-ingest / JSON-report path.

It is **not a supported run**. The cluster image did not install the Python
raster stack, Fields were regenerated from a seed, and the live product was a
JSON report rather than a Field-day table.

See `docs/adr/0014-kubernetes-is-prior-art.md` and
`docs/adr/0015-no-live-k8s-dag-as-code.md`. The current demo is the lakehouse
path in the repository root.
