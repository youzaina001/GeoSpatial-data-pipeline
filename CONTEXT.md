# GeoPipeline

A GitHub portfolio pipeline that turns satellite imagery over an area of interest into field-level vegetation observations. The people who read and run it are the author and interviewers, not an operational farm.

## Language

**AOI**:
A named geographic rectangle (bounding box and CRS) that bounds which imagery and fields belong together.
_Avoid_: Region

**NDVI**:
The vegetation index `(NIR - Red) / (NIR + Red)` computed over the Field's geometry, used as the observation when a Field-day is observed.
_Avoid_: stats, the report

**Field**:
A persistent agricultural plot with a stable identity, geometry, crop type, and planting date. The same Field is observed across many dates.
_Avoid_: generated farm, random field

**Field master**:
The versioned set of Fields the pipeline reads. It lives as a checked-in fixture.
_Avoid_: field config, generated fields

**Field-day**:
The grain of the data product: one row per Field per calendar date. Status is decided in this order: ineligible if the date is before planting; else missing-scene if the Scene is missing; else cloudy if the Scene is cloudy; else observed, with NDVI. Only observed rows have NDVI.
_Avoid_: daily report, field result, stats

**Eligible**:
A Field whose planting date is on or before the Field-day date. Ineligible beats Scene status: a Field that was not planted is ineligible even if the Scene is missing or cloudy.
_Avoid_: active, ready

**Scene**:
The imagery, or the explicit lack of imagery, for the AOI on a calendar date. A Scene is present, cloudy, or missing. Cloud is a property of the Scene, not of a Field.
_Avoid_: tile, satellite data, aoi_raster

**Scene catalog**:
The date-keyed record of whether each date's Scene is present, cloudy, or missing.
_Avoid_: availability API

**Landing**:
The layer that holds Scenes and the Field master as stored for a run.
_Avoid_: bronze, raw

**Product**:
The layer that holds the Field-day table, stored as Parquet for local query and loaded into Databricks SQL for the warehouse demo.
_Avoid_: gold, processed-data, silver
