# Ingestion Service
"""Business logic for satellite data ingestion."""

import hashlib
import logging
import os
import tempfile
from typing import Optional

from geopipeline.config import get_storage_config, get_region_config, get_generator_config
from geopipeline.generators import satellite_data
from geopipeline.clients import storage

logger = logging.getLogger(__name__)


def discover_tiles_for_date(date: str, region: Optional[dict] = None) -> list:
    """
    Discover all tiles available for a given date and region.

    Args:
        date: Date string in YYYY-MM-DD format
        region: Region config dict (uses default if None)

    Returns:
        List of tile metadata dictionaries
    """
    if region is None:
        region = get_region_config()

    logger.info(f"Discovering tiles for date={date}, region={region.get('name')}")
    generator_config = get_generator_config()
    tiles = satellite_data.generate_tile_metadata(
        region, date, seed=generator_config["seed"]
    )
    logger.debug(f"Found {len(tiles)} tiles")
    return tiles


def ingest_single_tile(tile: dict, storage_config: Optional[dict] = None) -> dict:
    """
    Generate and store a single tile in MinIO.

    Args:
        tile: Tile metadata dictionary
        storage_config: Storage config dict (uses default if None)

    Returns:
        Dict with tile_id, s3_uri, and status
    """
    if storage_config is None:
        storage_config = get_storage_config()

    generator_config = get_generator_config()
    tile_id = tile["tile_id"]

    try:
        # Create temp directory for raster file
        with tempfile.TemporaryDirectory(prefix="geopipeline_tile_") as temp_dir:
            # Generate synthetic raster
            tile_seed = (
                generator_config["seed"]
                + int(hashlib.md5(tile_id.encode()).hexdigest(), 16) % 10000
            )
            local_path = satellite_data.generate_raster_file(
                tile,
                temp_dir,
                raster_size=generator_config["raster_size"],
                seed=tile_seed,
            )

            # Upload to MinIO
            s3_client = storage.create_s3_client(storage_config)
            ext = os.path.splitext(local_path)[1]
            s3_key = f"{tile['date']}/{tile_id}{ext}"

            logger.info(
                f"Uploading tile {tile_id} to {storage_config['raw_bucket']}/{s3_key}"
            )
            s3_uri = storage.upload_file(
                s3_client,
                local_path,
                storage_config["raw_bucket"],
                s3_key,
            )

            # Also store tile metadata
            metadata_key = f"{tile['date']}/{tile_id}_metadata.json"
            storage.upload_json(
                s3_client, tile, storage_config["raw_bucket"], metadata_key
            )

        return {
            "tile_id": tile_id,
            "date": tile["date"],
            "s3_uri": s3_uri,
            "status": "ingested",
        }

    except Exception as e:
        logger.error(f"Failed to ingest tile {tile_id}: {str(e)}", exc_info=True)
        return {
            "tile_id": tile_id,
            "date": tile["date"],
            "s3_uri": None,
            "status": "failed",
            "error": str(e),
        }


def ingest_all_tiles(date: str, region: Optional[dict] = None) -> list:
    """
    Discover and ingest all tiles for a date (sequential version).

    Args:
        date: Date string in YYYY-MM-DD format
        region: Region config dict (uses default if None)

    Returns:
        List of ingestion results
    """
    logger.info(f"Starting sequential ingestion for date={date}")
    tiles = discover_tiles_for_date(date, region)
    results = []

    for tile in tiles:
        result = ingest_single_tile(tile)
        results.append(result)

    logger.info(f"Completed ingestion for {len(results)} tiles")
    return results


def get_ingested_tile_count(date: str, storage_config: Optional[dict] = None) -> int:
    """
    Count how many tiles have been ingested for a date.

    Args:
        date: Date string in YYYY-MM-DD format
        storage_config: Storage config dict (uses default if None)

    Returns:
        Number of ingested tiles
    """
    if storage_config is None:
        storage_config = get_storage_config()

    try:
        s3_client = storage.create_s3_client(storage_config)
        objects = storage.list_objects(
            s3_client, storage_config["raw_bucket"], prefix=f"{date}/"
        )

        # Count raster files (exclude metadata files) - both .tif and .npy supported
        count = len([obj for obj in objects if obj.endswith((".tif", ".npy"))])
        logger.debug(f"Found {count} ingested tiles for {date}")
        return count
    except Exception as e:
        logger.error(f"Failed to count ingested tiles: {str(e)}")
        return 0
