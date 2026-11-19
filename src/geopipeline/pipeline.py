# Field-day pipeline
"""Build Landing and the Field-day Product for a date range."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from rasterio.transform import from_bounds

from geopipeline.inputs import (
    MISSING_SCENE,
    Bounds,
    Field,
    Scene,
    load_field_master,
    load_scene_catalog,
)
from geopipeline.ndvi import ScenePixels

RASTER_SIZE = 32
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_FIELD_MASTER = Path("fixtures/field_master.geojson")
DEFAULT_SCENE_CATALOG = Path("fixtures/scene_catalog.json")


def run(
    start: str | date,
    end: str | date,
    *,
    data_root: str | Path,
    field_master: str | Path,
    scene_catalog: str | Path,
) -> None:
    """Backfill Field-days from start to end inclusive. Overwrites each date's Product."""
    start_day = _as_date(start)
    end_day = _as_date(end)
    if start_day > end_day:
        raise ValueError(f"start {start_day} is after end {end_day}")

    data_root = Path(data_root)
    master = load_field_master(Path(field_master))
    catalog = load_scene_catalog(Path(scene_catalog))

    landing_fields = data_root / "landing" / "fields"
    landing_fields.mkdir(parents=True, exist_ok=True)
    (landing_fields / "field_master.geojson").write_text(
        master.source, encoding="utf-8"
    )

    day = start_day
    while day <= end_day:
        scene = catalog.get(day, MISSING_SCENE)
        _write_scene(data_root, day, master.bbox, scene)
        _write_field_days(data_root, day, master.fields, scene)
        day += timedelta(days=1)


def run_date(
    day: str | date,
    *,
    data_root: str | Path,
    field_master: str | Path,
    scene_catalog: str | Path,
) -> None:
    """Build Landing and Product for a single date."""
    run(
        day,
        day,
        data_root=data_root,
        field_master=field_master,
        scene_catalog=scene_catalog,
    )


def run_scheduled_date(
    day: str | date, *, environ: Mapping[str, str] | None = None
) -> str:
    """Same as run_date, with CLI/DAG path defaults and optional env overrides."""
    env = os.environ if environ is None else environ
    iso = day if isinstance(day, str) else day.isoformat()
    run_date(
        iso,
        data_root=env.get("GEOPIPELINE_DATA_ROOT", str(DEFAULT_DATA_ROOT)),
        field_master=env.get("GEOPIPELINE_FIELD_MASTER", str(DEFAULT_FIELD_MASTER)),
        scene_catalog=env.get("GEOPIPELINE_SCENE_CATALOG", str(DEFAULT_SCENE_CATALOG)),
    )
    return iso


def _as_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _field_day_status(planting_date: date, day: date, scene_status: str) -> str:
    if day < planting_date:
        return "ineligible"
    if scene_status == "missing":
        return "missing-scene"
    if scene_status == "cloudy":
        return "cloudy"
    return "observed"


def _write_scene(
    data_root: Path,
    day: date,
    bbox: Bounds,
    scene: Scene,
) -> None:
    out_dir = data_root / "landing" / "scenes" / f"date={day.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, str | int] = {"date": day.isoformat(), "status": scene.status}
    if scene.status != "missing":
        record["red"] = scene.red
        record["nir"] = scene.nir
        _write_scene_raster(out_dir / "scene.tif", bbox, scene.red, scene.nir)
    (out_dir / "scene.json").write_text(json.dumps(record, indent=2))


def _write_scene_raster(
    path: Path, bbox: Bounds, red: int, nir: int, size: int = RASTER_SIZE
) -> None:
    west, south, east, north = bbox
    transform = from_bounds(west, south, east, north, size, size)
    data = np.zeros((4, size, size), dtype=np.uint16)
    data[0] = 1200
    data[1] = 1400
    data[2] = red
    data[3] = nir
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=4,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)
        dst.descriptions = ("B02", "B03", "B04", "B08")


def _write_field_days(
    data_root: Path,
    day: date,
    fields: list[Field],
    scene: Scene,
) -> None:
    raster_path = (
        data_root / "landing" / "scenes" / f"date={day.isoformat()}" / "scene.tif"
    )
    pixels = None
    rows: dict[str, list[Any]] = {
        "field_id": [],
        "date": [],
        "status": [],
        "ndvi": [],
        "crop_type": [],
        "planting_date": [],
    }
    for field in fields:
        status = _field_day_status(field.planting_date, day, scene.status)
        ndvi = None
        if status == "observed":
            if pixels is None:
                pixels = ScenePixels.read(raster_path)
            try:
                ndvi = pixels.mean_ndvi(field.geometry)
            except ValueError as exc:
                raise ValueError(f"{day} Field {field.field_id!r}: {exc}") from exc
        rows["field_id"].append(field.field_id)
        rows["date"].append(day)
        rows["status"].append(status)
        rows["ndvi"].append(ndvi)
        rows["crop_type"].append(field.crop_type)
        rows["planting_date"].append(field.planting_date)

    table = pa.table(
        {
            "field_id": pa.array(rows["field_id"], type=pa.string()),
            "date": pa.array(rows["date"], type=pa.date32()),
            "status": pa.array(rows["status"], type=pa.string()),
            "ndvi": pa.array(rows["ndvi"], type=pa.float64()),
            "crop_type": pa.array(rows["crop_type"], type=pa.string()),
            "planting_date": pa.array(rows["planting_date"], type=pa.date32()),
        }
    )
    out_dir = data_root / "product" / "field_days" / f"date={day.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_dir / "part.parquet")
