"""Validate Field master and Scene catalog inputs before writing dates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import inf
from pathlib import Path

type Bounds = tuple[float, float, float, float]

DEFAULT_RED = 2000
DEFAULT_NIR = 6000


@dataclass(frozen=True)
class Field:
    field_id: str
    crop_type: str
    planting_date: date
    geometry: dict[str, object]


@dataclass(frozen=True)
class FieldMaster:
    source: str
    bbox: Bounds
    fields: list[Field]


@dataclass(frozen=True)
class Scene:
    status: str
    red: int = DEFAULT_RED
    nir: int = DEFAULT_NIR


MISSING_SCENE = Scene("missing")


def load_field_master(path: Path) -> FieldMaster:
    source, payload = _read_json(path)
    bbox = _load_bbox(payload.get("bbox"))
    crs = payload.get("crs")
    if crs is not None:
        properties = _object(
            _object(crs, "AOI crs").get("properties"), "AOI crs properties"
        )
        name = properties.get("name")
        if not isinstance(name, str) or name.upper() not in {
            "EPSG:4326",
            "OGC:CRS84",
            "URN:OGC:DEF:CRS:OGC:1.3:CRS84",
            "URN:OGC:DEF:CRS:EPSG::4326",
        }:
            raise ValueError("AOI crs must describe WGS 84")

    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("Field master features must be an array")
    fields: list[Field] = []
    seen: set[str] = set()
    for index, value in enumerate(features, start=1):
        feature = _object(value, f"Field master feature {index}")
        props = _object(
            feature.get("properties"), f"Field master feature {index} properties"
        )
        field_id = props.get("field_id")
        if not isinstance(field_id, str) or not field_id.strip():
            raise ValueError(
                f"Field master feature {index} requires a nonempty field_id"
            )
        if field_id in seen:
            raise ValueError(f"duplicate Field ID {field_id!r}")
        seen.add(field_id)

        planting_date = _parse_date(
            props.get("planting_date"), f"Field {field_id!r} planting_date"
        )
        crop_type = props.get("crop_type")
        if not isinstance(crop_type, str):
            raise ValueError(f"Field {field_id!r} crop_type must be a string")
        geometry = _load_geometry(feature.get("geometry"), field_id, bbox)
        fields.append(Field(field_id, crop_type, planting_date, geometry))
    return FieldMaster(source, bbox, fields)


def load_scene_catalog(path: Path) -> dict[date, Scene]:
    _, payload = _read_json(path)
    catalog: dict[date, Scene] = {}
    for key, value in payload.items():
        day = _parse_date(key, "Scene catalog date")
        if day.isoformat() != key:
            raise ValueError(f"Scene catalog date {key!r} must use YYYY-MM-DD")
        entry = _object(value, f"Scene for {day}")
        status = entry.get("status")
        if not isinstance(status, str) or status not in (
            "present",
            "cloudy",
            "missing",
        ):
            raise ValueError(f"unknown Scene status {status!r} for {day}")
        red = _band_value(entry.get("red", DEFAULT_RED), "red", day)
        nir = _band_value(entry.get("nir", DEFAULT_NIR), "nir", day)
        catalog[day] = Scene(status, red, nir)
    return catalog


def _read_json(path: Path) -> tuple[str, dict[str, object]]:
    source = path.read_text(encoding="utf-8")
    try:
        return source, _object(json.loads(source), str(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _parse_date(value: object, label: str) -> date:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{label} must be a valid ISO date, got {value!r}"
            ) from exc
    raise ValueError(f"{label} must be a valid ISO date, got {value!r}")


def _band_value(value: object, band: str, day: date) -> int:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ValueError(f"Scene {day} {band} must be a UInt16 integer, got {value!r}")
    return value


def _in_range(value: object, lower: float, upper: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and -inf < value < inf
        and lower <= value <= upper
    )


def _load_bbox(value: object) -> Bounds:
    if isinstance(value, list) and len(value) == 4:
        west, south, east, north = value
        if (
            _in_range(west, -180, 180)
            and _in_range(east, -180, 180)
            and _in_range(south, -90, 90)
            and _in_range(north, -90, 90)
            and west < east
            and south < north
        ):
            return west, south, east, north
    raise ValueError(
        "AOI bbox must be [west, south, east, north] in WGS 84 with positive extent"
    )


def _load_geometry(value: object, field_id: str, bbox: Bounds) -> dict[str, object]:
    label = f"Field {field_id!r} geometry"
    geometry = _object(value, label)
    kind = geometry.get("type")
    if kind not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"{label} must be a Polygon or MultiPolygon")
    coordinates = geometry.get("coordinates")
    polygons = [coordinates] if kind == "Polygon" else coordinates
    # shortcut: checks ring structure and bounds, use a geometry engine for arbitrary GIS topology.
    if (
        not isinstance(polygons, list)
        or not polygons
        or not all(
            isinstance(polygon, list)
            and polygon
            and all(_valid_ring(ring, bbox) for ring in polygon)
            for polygon in polygons
        )
    ):
        raise ValueError(
            f"{label} must have closed, nondegenerate rings inside the AOI bbox"
        )
    return geometry


def _valid_ring(value: object, bbox: Bounds) -> bool:
    if not isinstance(value, list) or len(value) < 4 or value[0] != value[-1]:
        return False
    west, south, east, north = bbox
    points: list[tuple[float, float]] = []
    for position in value:
        if (
            not isinstance(position, list)
            or len(position) not in (2, 3)
            or not _in_range(position[0], west, east)
            or not _in_range(position[1], south, north)
            or (len(position) == 3 and not _in_range(position[2], -inf, inf))
        ):
            return False
        points.append((position[0], position[1]))
    x0, y0 = points[0]
    return (
        sum(
            (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            for (x1, y1), (x2, y2) in zip(points, points[1:])
        )
        != 0
    )
