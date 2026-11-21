# Scenes stay synthetic but some dates are absent or cloudy

_Status: archived 2026-11-21 with the satellite example ([ADR 0021](0021-archive-the-satellite-example.md)). It describes code under `archive/v1-satellite/`, not the supported build._

The $0 path does not call Sentinel or STAC. A date-keyed scene catalog (or a deterministic function of the date) decides whether a Scene is present, cloudy, or missing so Field-day statuses are not fake columns. Real imagery can appear later as an adapter, not as the clone default.
