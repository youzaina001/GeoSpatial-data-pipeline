# NDVI over a Field geometry
"""Mean NDVI of raster pixels that fall inside a polygon."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.transform import Affine

RED_BAND = 3
NIR_BAND = 4


@dataclass(frozen=True)
class ScenePixels:
    red: NDArray[np.float64]
    nir: NDArray[np.float64]
    transform: Affine

    @classmethod
    def read(cls, raster_path: str | Path) -> ScenePixels:
        with rasterio.open(raster_path) as src:
            red, nir = src.read([RED_BAND, NIR_BAND], out_dtype="float64")
            return cls(red, nir, src.transform)

    def mean_ndvi(self, geometry: Mapping[str, object]) -> float:
        inside = geometry_mask(
            [geometry],
            out_shape=self.red.shape,
            transform=self.transform,
            invert=True,
        )
        red = self.red[inside]
        nir = self.nir[inside]
        denom = nir + red
        valid = denom != 0
        if not np.any(valid):
            raise ValueError("no usable NDVI pixels")
        return float(np.mean((nir[valid] - red[valid]) / denom[valid]))


def ndvi_over_geometry(
    raster_path: str | Path, geometry: Mapping[str, object]
) -> float:
    """Return mean NDVI for usable pixels inside geometry."""
    return ScenePixels.read(raster_path).mean_ndvi(geometry)
