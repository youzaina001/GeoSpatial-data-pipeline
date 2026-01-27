# Synthetic Satellite Data Generator
"""Generate synthetic satellite tile metadata and raster files."""

import hashlib
import json
import os
import random
import tempfile
from typing import Optional

import numpy as np

# Rasterio is optional for environments without GDAL
try:
    import rasterio
    from rasterio.transform import from_bounds

    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


def generate_tile_id(lon: float, lat: float, date: str) -> str:
    """Generate a deterministic tile ID based on coordinates and date."""
    raw = f"{lon:.2f}_{lat:.2f}_{date}"
    return f"T{hashlib.md5(raw.encode()).hexdigest()[:8].upper()}"


def generate_tile_metadata(region: dict, date: str, seed: Optional[int] = None) -> list:
    """
    Generate realistic satellite tile metadata for a region and date.

    Args:
        region: Dict with 'bbox' [lon_min, lat_min, lon_max, lat_max] and 'tile_size'
        date: Date string in YYYY-MM-DD format
        seed: Random seed for reproducibility

    Returns:
        List of tile metadata dictionaries
    """
    if seed is not None:
        random.seed(seed)

    tiles = []
    bbox = region["bbox"]
    tile_size = region["tile_size"]

    lon = bbox[0]
    while lon < bbox[2]:
        lat = bbox[1]
        while lat < bbox[3]:
            tile_id = generate_tile_id(lon, lat, date)
            tiles.append(
                {
                    "tile_id": tile_id,
                    "date": date,
                    "bbox": [lon, lat, lon + tile_size, lat + tile_size],
                    "cloud_coverage": round(random.uniform(0, 100), 2),
                    "bands": ["B02", "B03", "B04", "B08"],
                    "crs": "EPSG:4326",
                }
            )
            lat += tile_size
        lon += tile_size

    return tiles


def generate_raster_data(
    bands: int, height: int, width: int, seed: Optional[int] = None
) -> np.ndarray:
    """
    Generate synthetic raster data simulating satellite imagery.

    Args:
        bands: Number of spectral bands
        height: Raster height in pixels
        width: Raster width in pixels
        seed: Random seed for reproducibility

    Returns:
        numpy array of shape (bands, height, width) with uint16 values
    """
    if seed is not None:
        np.random.seed(seed)

    # Simulate realistic satellite reflectance values (0-10000 range)
    data = np.random.randint(100, 8000, (bands, height, width), dtype=np.uint16)

    # Add some spatial correlation (simple smoothing effect)
    for b in range(bands):
        # Create a gradient pattern to simulate land features
        gradient = np.linspace(0.8, 1.2, width)
        data[b] = (data[b] * gradient).astype(np.uint16)

    return data


def generate_raster_file(
    tile: dict, output_dir: str, raster_size: int = 256, seed: Optional[int] = None
) -> str:
    """
    Generate a synthetic GeoTIFF raster file for a tile.

    Args:
        tile: Tile metadata dictionary with 'tile_id', 'bbox', 'bands'
        output_dir: Directory to save the raster file
        raster_size: Size of the raster in pixels (width=height)
        seed: Random seed for reproducibility

    Returns:
        Path to the generated raster file
    """
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{tile['tile_id']}_{tile['date']}.tif"
    output_path = os.path.join(output_dir, filename)

    num_bands = len(tile["bands"])
    data = generate_raster_data(num_bands, raster_size, raster_size, seed)

    if HAS_RASTERIO:
        # Write proper GeoTIFF with georeferencing
        bbox = tile["bbox"]
        transform = from_bounds(
            bbox[0], bbox[1], bbox[2], bbox[3], raster_size, raster_size
        )

        with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            height=raster_size,
            width=raster_size,
            count=num_bands,
            dtype=data.dtype,
            crs=tile.get("crs", "EPSG:4326"),
            transform=transform,
        ) as dst:
            dst.write(data)
    else:
        # Fallback: save as numpy binary with metadata sidecar
        np.save(output_path.replace(".tif", ".npy"), data)
        with open(output_path.replace(".tif", "_meta.json"), "w") as f:
            json.dump(tile, f)
        output_path = output_path.replace(".tif", ".npy")

    return output_path


def generate_tiles_for_date(
    region: dict,
    date: str,
    output_dir: Optional[str] = None,
    seed: Optional[int] = None,
) -> list:
    """
    Generate all tiles (metadata + raster files) for a region and date.

    Args:
        region: Region configuration dict
        date: Date string in YYYY-MM-DD format
        output_dir: Directory for raster files (uses temp dir if None)
        seed: Random seed for reproducibility

    Returns:
        List of tile metadata dicts with 'local_path' added
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="hydrosat_")

    tiles = generate_tile_metadata(region, date, seed)

    for tile in tiles:
        tile_seed = (
            seed + int(hashlib.md5(tile["tile_id"].encode()).hexdigest(), 16) % 1000
            if seed
            else None
        )
        tile["local_path"] = generate_raster_file(tile, output_dir, seed=tile_seed)

    return tiles
