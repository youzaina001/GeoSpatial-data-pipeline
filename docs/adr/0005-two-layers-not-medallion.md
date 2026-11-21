# Name two layers, Landing and Product, not bronze/silver/gold

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

At this scale a silver layer would be a rename. Landing holds rasters and the Field master; Product holds the Field-day table. Medallion vocabulary is reserved for a future transform that earns a name.
