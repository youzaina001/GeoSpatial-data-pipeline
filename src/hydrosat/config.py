# Hydrosat Pipeline Configuration
"""Configuration management using environment variables."""

import os


def get_storage_config() -> dict:
    """Get MinIO/S3 storage configuration."""
    return {
        "endpoint": os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        "access_key": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        "secret_key": os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        "secure": os.getenv("MINIO_SECURE", "false").lower() == "true",
        "raw_bucket": os.getenv("RAW_BUCKET", "raw-imagery"),
        "processed_bucket": os.getenv("PROCESSED_BUCKET", "processed-data"),
    }


def get_aoi_config() -> dict:
    """
    Get Area of Interest (AOI) configuration.

    The AOI defines the rectangular extent for satellite data processing.
    """
    return {
        "name": os.getenv("AOI_NAME", "europe-sample"),
        "bbox": [
            float(os.getenv("AOI_LON_MIN", "2.0")),
            float(os.getenv("AOI_LAT_MIN", "48.0")),
            float(os.getenv("AOI_LON_MAX", "3.0")),
            float(os.getenv("AOI_LAT_MAX", "49.0")),
        ],
        "crs": os.getenv("AOI_CRS", "EPSG:4326"),
    }


def get_fields_config() -> dict:
    """
    Get field generation configuration.

    Controls how synthetic agricultural fields are generated.
    """
    return {
        "num_fields": int(os.getenv("NUM_FIELDS", "6")),
        "seed": int(os.getenv("RANDOM_SEED", "42")),
    }


def get_generator_config() -> dict:
    """Get synthetic data generator configuration."""
    return {
        "bands": ["B02", "B03", "B04", "B08"],  # Blue, Green, Red, NIR
        "band_names": {
            "B02": "Blue",
            "B03": "Green",
            "B04": "Red",
            "B08": "NIR",
        },
        "raster_size": int(os.getenv("RASTER_SIZE", "512")),  # pixels for AOI
        "seed": int(os.getenv("RANDOM_SEED", "42")),
    }


# Keep for backwards compatibility
def get_region_config() -> dict:
    """Get target region configuration (deprecated, use get_aoi_config)."""
    aoi = get_aoi_config()
    return {
        "name": aoi["name"],
        "bbox": aoi["bbox"],
        "tile_size": float(os.getenv("TILE_SIZE", "0.5")),
    }
