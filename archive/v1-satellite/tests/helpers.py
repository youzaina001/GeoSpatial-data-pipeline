# Shared test fixtures
"""Tiny Field master + Scene catalog used at the pipeline seam."""

from __future__ import annotations

import json
from pathlib import Path

TINY_FIELDS = {
    "type": "FeatureCollection",
    "name": "tiny-aoi",
    "bbox": [2.0, 48.0, 2.4, 48.4],
    "features": [
        {
            "type": "Feature",
            "properties": {
                "field_id": "F001",
                "crop_type": "wheat",
                "planting_date": "2024-04-10",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [2.05, 48.05],
                        [2.15, 48.05],
                        [2.15, 48.15],
                        [2.05, 48.15],
                        [2.05, 48.05],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "field_id": "F002",
                "crop_type": "corn",
                "planting_date": "2024-03-01",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [2.25, 48.25],
                        [2.35, 48.25],
                        [2.35, 48.35],
                        [2.25, 48.35],
                        [2.25, 48.25],
                    ]
                ],
            },
        },
    ],
}

TINY_CATALOG = {
    "2024-04-05": {"status": "present", "red": 2000, "nir": 6000},
    "2024-04-12": {"status": "missing"},
    "2024-04-15": {"status": "cloudy", "red": 2000, "nir": 6000},
    "2024-04-16": {"status": "present", "red": 2000, "nir": 6000},
}


def write_tiny_fixtures(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    field_master = directory / "field_master.geojson"
    catalog = directory / "scene_catalog.json"
    field_master.write_text(json.dumps(TINY_FIELDS))
    catalog.write_text(json.dumps(TINY_CATALOG))
    return field_master, catalog
