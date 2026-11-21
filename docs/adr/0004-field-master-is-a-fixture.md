# The Field master is a checked-in fixture

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

Fields are not regenerated from a seed each run. A versioned GeoJSON/JSON in the repo is the system of record: stable IDs, geometry, crop, planting date. That keeps the $0 path cloneable and reviewable without a database.
