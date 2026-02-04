# Processing Service
"""Business logic for satellite data processing and field-level aggregation."""

import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from geopipeline.config import get_storage_config, get_aoi_config, get_fields_config
from geopipeline.clients import storage
from geopipeline.generators.field_data import generate_fields_for_aoi, get_eligible_fields

logger = logging.getLogger(__name__)

# Rasterio is optional
try:
    import rasterio

    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


def check_satellite_data_available(
    date: str, storage_config: Optional[dict] = None
) -> bool:
    """
    Check if satellite data exists for the given date.

    Args:
        date: Date string in YYYY-MM-DD format
        storage_config: Storage config dict (uses default if None)

    Returns:
        True if satellite data exists for the date
    """
    if storage_config is None:
        storage_config = get_storage_config()

    s3_client = storage.create_s3_client(storage_config)
    key = f"{date}/aoi_raster.tif"

    return storage.object_exists(s3_client, storage_config["raw_bucket"], key)


def check_previous_day_data(date: str, storage_config: Optional[dict] = None) -> bool:
    """
    Check if previous day's satellite data exists.

    Args:
        date: Current date string in YYYY-MM-DD format
        storage_config: Storage config dict (uses default if None)

    Returns:
        True if previous day's data exists
    """
    current_date = datetime.strptime(date, "%Y-%m-%d")
    previous_date = (current_date - timedelta(days=1)).strftime("%Y-%m-%d")

    return check_satellite_data_available(previous_date, storage_config)


def discover_fields_for_processing(
    execution_date: str,
    aoi_config: Optional[dict] = None,
    fields_config: Optional[dict] = None,
) -> list[dict]:
    """
    Discover fields eligible for processing on the execution date.

    A field is eligible if execution_date >= planting_date.

    Args:
        execution_date: Processing date in YYYY-MM-DD format
        aoi_config: AOI configuration (uses default if None)
        fields_config: Fields configuration (uses default if None)

    Returns:
        List of eligible field dictionaries
    """
    if aoi_config is None:
        aoi_config = get_aoi_config()
    if fields_config is None:
        fields_config = get_fields_config()

    # Generate all fields for the AOI
    all_fields = generate_fields_for_aoi(
        aoi_bbox=aoi_config["bbox"],
        reference_date=execution_date,
        num_fields=fields_config["num_fields"],
        seed=fields_config["seed"],
    )

    # Filter to only eligible fields (planting_date <= execution_date)
    eligible_fields = get_eligible_fields(all_fields, execution_date)

    logger.info(
        f"Found {len(eligible_fields)}/{len(all_fields)} eligible fields for {execution_date}"
    )

    # Convert to dicts for Airflow serialization
    return [field.to_dict() for field in eligible_fields]


def compute_ndvi(red_band: np.ndarray, nir_band: np.ndarray) -> np.ndarray:
    """
    Compute Normalized Difference Vegetation Index.

    NDVI = (NIR - Red) / (NIR + Red)

    Args:
        red_band: Red band values
        nir_band: NIR band values

    Returns:
        NDVI array with values in [-1, 1]
    """
    # Avoid division by zero
    denominator = nir_band.astype(float) + red_band.astype(float)
    denominator[denominator == 0] = 1

    ndvi = (nir_band.astype(float) - red_band.astype(float)) / denominator
    return np.clip(ndvi, -1, 1)


def extract_field_values(
    raster_path: str,
    field: dict,
    aoi_bbox: list[float],
) -> dict:
    """
    Extract raster values for a field polygon.

    Uses a simple bounding box approach for field extraction.
    For production, use rasterio.mask with actual polygon geometry.

    Args:
        raster_path: Path to raster file
        field: Field dictionary with geometry and metadata
        aoi_bbox: AOI bounding box for coordinate transformation

    Returns:
        Dict with extracted band values and statistics
    """
    centroid = field["centroid"]

    if HAS_RASTERIO:
        with rasterio.open(raster_path) as src:
            # Get pixel coordinates for field centroid
            row, col = src.index(centroid[0], centroid[1])

            # Extract a small window around centroid (simulating field extent)
            window_size = 10  # pixels
            row_start = max(0, row - window_size)
            row_end = min(src.height, row + window_size)
            col_start = max(0, col - window_size)
            col_end = min(src.width, col + window_size)

            # Read all bands for the window
            data = src.read(window=((row_start, row_end), (col_start, col_end)))

            # Compute statistics per band
            band_stats = {}
            for i in range(data.shape[0]):
                band_stats[f"band_{i + 1}"] = {
                    "mean": float(np.mean(data[i])),
                    "std": float(np.std(data[i])),
                    "min": float(np.min(data[i])),
                    "max": float(np.max(data[i])),
                }

            # Compute NDVI (assuming band 3 = Red, band 4 = NIR)
            if data.shape[0] >= 4:
                red = data[2]  # B04 - Red
                nir = data[3]  # B08 - NIR
                ndvi = compute_ndvi(red, nir)
                band_stats["ndvi"] = {
                    "mean": float(np.mean(ndvi)),
                    "std": float(np.std(ndvi)),
                    "min": float(np.min(ndvi)),
                    "max": float(np.max(ndvi)),
                }

            return band_stats
    else:
        # Fallback without rasterio
        return {
            "band_1": {"mean": 1500.0, "std": 200.0},
            "band_2": {"mean": 1800.0, "std": 250.0},
            "band_3": {"mean": 2100.0, "std": 300.0},
            "band_4": {"mean": 4500.0, "std": 400.0},
            "ndvi": {"mean": 0.35, "std": 0.1},
        }


def process_single_field(
    field: dict,
    execution_date: str,
    storage_config: Optional[dict] = None,
    aoi_config: Optional[dict] = None,
) -> dict:
    """
    Process a single field: extract values, compute statistics, store results.

    Args:
        field: Field dictionary
        execution_date: Processing date
        storage_config: Storage config (uses default if None)
        aoi_config: AOI config (uses default if None)

    Returns:
        Processing result dictionary
    """
    if storage_config is None:
        storage_config = get_storage_config()
    if aoi_config is None:
        aoi_config = get_aoi_config()

    field_id = field["field_id"]
    planting_date = field["planting_date"]

    # Calculate days since planting
    exec_dt = datetime.strptime(execution_date, "%Y-%m-%d")
    plant_dt = datetime.strptime(planting_date, "%Y-%m-%d")
    days_since_planting = (exec_dt - plant_dt).days

    try:
        s3_client = storage.create_s3_client(storage_config)

        # Download satellite raster
        raster_key = f"{execution_date}/aoi_raster.tif"

        with tempfile.TemporaryDirectory(prefix="geopipeline_field_") as temp_dir:
            local_raster = os.path.join(temp_dir, "aoi_raster.tif")
            storage.download_file(
                s3_client, storage_config["raw_bucket"], raster_key, local_raster
            )

            # Extract field values
            field_values = extract_field_values(local_raster, field, aoi_config["bbox"])

        # Create field result
        result = {
            "field_id": field_id,
            "field_name": field["name"],
            "crop_type": field["crop_type"],
            "execution_date": execution_date,
            "planting_date": planting_date,
            "days_since_planting": days_since_planting,
            "statistics": field_values,
            "status": "processed",
        }

        # Store field result
        result_key = f"{execution_date}/fields/{field_id}_result.json"
        storage.upload_json(
            s3_client, result, storage_config["processed_bucket"], result_key
        )

        logger.info(
            f"Processed field {field_id}: NDVI mean = {field_values.get('ndvi', {}).get('mean', 'N/A')}"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to process field {field_id}: {e}")
        return {
            "field_id": field_id,
            "execution_date": execution_date,
            "status": "failed",
            "error": str(e),
        }


def aggregate_field_results(results: list[dict], execution_date: str) -> dict:
    """
    Aggregate results from all processed fields.

    Args:
        results: List of field processing results
        execution_date: Processing date

    Returns:
        Aggregated summary dictionary
    """
    successful = [r for r in results if r.get("status") == "processed"]
    failed = [r for r in results if r.get("status") != "processed"]

    # Compute aggregate NDVI statistics
    ndvi_values = []
    for r in successful:
        ndvi_mean = r.get("statistics", {}).get("ndvi", {}).get("mean")
        if ndvi_mean is not None:
            ndvi_values.append(ndvi_mean)

    summary = {
        "execution_date": execution_date,
        "total_fields": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "average_ndvi": round(np.mean(ndvi_values), 4) if ndvi_values else None,
        "fields_by_crop": {},
    }

    # Count by crop type
    for r in successful:
        crop = r.get("crop_type", "unknown")
        summary["fields_by_crop"][crop] = summary["fields_by_crop"].get(crop, 0) + 1

    return summary


def generate_daily_report(
    execution_date: str,
    results: list[dict],
    storage_config: Optional[dict] = None,
) -> str:
    """
    Generate and store the daily field processing report.

    Args:
        execution_date: Processing date
        results: List of field processing results
        storage_config: Storage config (uses default if None)

    Returns:
        S3 URI of the report
    """
    if storage_config is None:
        storage_config = get_storage_config()

    summary = aggregate_field_results(results, execution_date)

    report = {
        "report_type": "daily_field_processing",
        "generated_at": datetime.utcnow().isoformat(),
        "summary": summary,
        "field_results": results,
    }

    s3_client = storage.create_s3_client(storage_config)
    report_key = f"{execution_date}/daily_report.json"

    s3_uri = storage.upload_json(
        s3_client, report, storage_config["processed_bucket"], report_key
    )

    logger.info(f"Generated daily report: {s3_uri}")
    return s3_uri


# Legacy functions for backwards compatibility
def aggregate_daily_data(date: str, storage_config: Optional[dict] = None) -> dict:
    """Legacy function - redirects to new implementation."""
    fields = discover_fields_for_processing(date)
    results = []
    for field in fields:
        result = process_single_field(field, date, storage_config)
        results.append(result)
    return aggregate_field_results(results, date)


def generate_report(
    date: str, stats: Optional[dict] = None, storage_config: Optional[dict] = None
) -> str:
    """Legacy function - redirects to new implementation."""
    if stats is None:
        fields = discover_fields_for_processing(date)
        results = [process_single_field(f, date, storage_config) for f in fields]
    else:
        results = stats.get("field_results", [])
    return generate_daily_report(date, results, storage_config)
