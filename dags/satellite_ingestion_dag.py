# Satellite Data Ingestion DAG
"""
DAG 1: Daily satellite data ingestion.

This DAG demonstrates:
- Scheduled daily satellite data acquisition
- Synthetic satellite raster generation for the AOI
- Storage in MinIO S3-compatible buckets
- Preparation for downstream field-level processing
"""

import hashlib
import logging
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task

# Default arguments for the DAG
default_args = {
    "owner": "hydrosat",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

logger = logging.getLogger("airflow.task")

with DAG(
    dag_id="satellite_ingestion",
    default_args=default_args,
    description="Ingest daily satellite imagery",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["hydrosat", "ingestion", "satellite", "aoi"],
) as dag:

    @task
    def check_satellite_availability(**context) -> dict:
        """
        Check if satellite data is available for the execution date.

        In production, this would query a satellite data API.
        For this demo, we always return available.
        """
        from hydrosat.config import get_aoi_config

        execution_date = context["ds"]
        aoi_config = get_aoi_config()

        logger.info(f"Checking satellite availability for {execution_date}")
        logger.info(f"AOI: {aoi_config['name']} - bbox: {aoi_config['bbox']}")

        # In production: query Sentinel Hub, Planet, etc.
        # For demo: always available
        return {
            "date": execution_date,
            "aoi": aoi_config["name"],
            "available": True,
            "satellite": "Sentinel-2",
            "cloud_coverage": 15.0,  # Simulated
        }

    @task
    def generate_aoi_raster(availability: dict) -> dict:
        """
        Generate or download satellite raster for the AOI.

        Creates a synthetic multi-band raster covering the entire AOI.
        In production, this would download real satellite imagery.
        """
        import os
        import tempfile
        from hydrosat.config import (
            get_aoi_config,
            get_generator_config,
            get_storage_config,
        )
        from hydrosat.generators import satellite_data
        from hydrosat.clients import storage

        execution_date = availability["date"]
        aoi_config = get_aoi_config()
        gen_config = get_generator_config()
        storage_config = get_storage_config()

        logger.info(f"Generating AOI raster for {execution_date}")

        # Create a tile-like structure for the entire AOI
        aoi_tile = {
            "tile_id": f"AOI_{aoi_config['name']}",
            "date": execution_date,
            "bbox": aoi_config["bbox"],
            "bands": gen_config["bands"],
            "crs": aoi_config.get("crs", "EPSG:4326"),
            "cloud_coverage": availability.get("cloud_coverage", 0),
        }

        with tempfile.TemporaryDirectory(prefix="hydrosat_aoi_") as temp_dir:
            # Generate synthetic raster
            local_path = satellite_data.generate_raster_file(
                aoi_tile,
                temp_dir,
                raster_size=gen_config["raster_size"],
                seed=gen_config["seed"]
                + int(hashlib.md5(execution_date.encode()).hexdigest(), 16) % 10000,
            )

            # Upload to MinIO
            s3_client = storage.create_s3_client(storage_config)
            ext = os.path.splitext(local_path)[1]
            s3_key = f"{execution_date}/aoi_raster{ext}"

            s3_uri = storage.upload_file(
                s3_client,
                local_path,
                storage_config["raw_bucket"],
                s3_key,
            )

            # Also store metadata
            metadata_key = f"{execution_date}/aoi_metadata.json"
            storage.upload_json(
                s3_client, aoi_tile, storage_config["raw_bucket"], metadata_key
            )

        logger.info(f"Uploaded AOI raster to {s3_uri}")

        return {
            "date": execution_date,
            "s3_uri": s3_uri,
            "bands": gen_config["bands"],
            "raster_size": gen_config["raster_size"],
            "status": "ingested",
        }

    @task
    def log_ingestion_summary(result: dict) -> dict:
        """
        Log a summary of the ingestion run.
        """
        logger.info(f"Ingestion complete for {result['date']}")
        logger.info(f"  S3 URI: {result['s3_uri']}")
        logger.info(f"  Bands: {result['bands']}")
        logger.info(f"  Raster size: {result['raster_size']}px")

        return {
            "date": result["date"],
            "status": "success",
            "s3_uri": result["s3_uri"],
        }

    # DAG flow:
    # 1. Check if satellite data is available
    # 2. Generate/download AOI raster
    # 3. Log summary

    availability = check_satellite_availability()
    raster_result = generate_aoi_raster(availability)
    log_ingestion_summary(raster_result)
