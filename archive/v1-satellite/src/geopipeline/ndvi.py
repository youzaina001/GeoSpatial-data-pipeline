# NDVI over a Field geometry
"""Mean NDVI of raster pixels that fall inside a polygon."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.features import geometry_mask

RED_BAND = 3
NIR_BAND = 4


def ndvi_over_geometry(raster_path: str | Path, geometry: dict[str, Any]) -> float:
    """Return mean NDVI for pixels inside geometry. (NIR - Red) / (NIR + Red)."""
    with rasterio.open(raster_path) as src:
        inside = geometry_mask(
            [geometry],
            out_shape=(src.height, src.width),
            transform=src.transform,
            invert=True,
        )
        red = src.read(RED_BAND).astype(np.float64)
        nir = src.read(NIR_BAND).astype(np.float64)

    if not np.any(inside):
        raise ValueError(f"geometry covers no pixels in {raster_path}")

    red_m = red[inside]
    nir_m = nir[inside]
    denom = nir_m + red_m
    valid = denom != 0
    if not np.any(valid):
        return 0.0
    return float(np.mean((nir_m[valid] - red_m[valid]) / denom[valid]))
