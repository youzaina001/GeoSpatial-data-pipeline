# Polygon-mask NDVI
"""NDVI is the mean over pixels inside the Field geometry, not a centroid window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from geopipeline.ndvi import ndvi_over_geometry


def _write_raster(path: Path, red: np.ndarray, nir: np.ndarray) -> None:
    height, width = red.shape
    transform = from_bounds(0, 0, width, height, width, height)
    data = np.stack(
        [
            np.full_like(red, 1000),
            np.full_like(red, 1000),
            red,
            nir,
        ]
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=4,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data)


def test_ndvi_uses_pixels_inside_the_polygon_only(tmp_path: Path) -> None:
    # 10x10 raster: background NDVI = 0. A 3x3 block in the SW corner has
    # red=1000, nir=3000 → NDVI = 0.5. Whole-raster mean would be 0.045.
    red = np.full((10, 10), 1000, dtype=np.uint16)
    nir = np.full((10, 10), 1000, dtype=np.uint16)
    nir[7:10, 0:3] = 3000
    path = tmp_path / "scene.tif"
    _write_raster(path, red, nir)

    corner = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]]],
    }
    background = {
        "type": "Polygon",
        "coordinates": [[[6, 6], [9, 6], [9, 9], [6, 9], [6, 6]]],
    }

    assert ndvi_over_geometry(path, corner) == pytest.approx(0.5)
    assert ndvi_over_geometry(path, background) == pytest.approx(0.0)
