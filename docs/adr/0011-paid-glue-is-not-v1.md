# The paid S3-to-Databricks path is not in this refactor

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

v1 is the $0 story: local Parquet (gitignored) plus a Free Edition notebook over a Product you upload after `make run`. Do not commit Parquet. A unified lake on AWS remains a documented later option, not a half-built Terraform target.
