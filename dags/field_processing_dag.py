# Field Processing DAG
"""
DAG 2: Daily field-level processing with dynamic task generation.

This DAG demonstrates:
- Sensor pattern to wait for satellite data availability
- Dynamic task mapping using expand() to create one task per field
- Planting-date-aware processing (fields only processed after planting)
- Per-field NDVI and statistics computation
- Day-over-day dependency pattern
"""

import logging
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.sensors.base import PokeReturnValue

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
    dag_id="field_processing",
    default_args=default_args,
    description="Process satellite data for each field with dynamic task generation",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["hydrosat", "processing", "fields", "dynamic"],
) as dag:

    @task.sensor(poke_interval=60, timeout=3600, mode="poke")
    def wait_for_satellite_data(**context) -> PokeReturnValue:
        """
        Sensor that waits for the current day's satellite data to be available.

        Creates a dependency: field processing can only run after satellite ingestion.
        """
        from hydrosat.services.processing import check_satellite_data_available

        execution_date = context["ds"]
        is_ready = check_satellite_data_available(execution_date)

        if is_ready:
            logger.info(
                f"Satellite data available for {execution_date}, proceeding with field processing"
            )
        else:
            logger.info(f"Waiting for satellite data for {execution_date}...")

        return PokeReturnValue(is_done=is_ready)

    @task
    def discover_eligible_fields(**context) -> list:
        """
        Discover all fields eligible for processing on the execution date.

        A field is eligible if execution_date >= planting_date.
        Returns list of field dicts that will be mapped to parallel tasks.
        """
        from hydrosat.services.processing import discover_fields_for_processing

        execution_date = context["ds"]
        logger.info(f"Discovering eligible fields for {execution_date}")

        fields = discover_fields_for_processing(execution_date)

        logger.info(f"Found {len(fields)} eligible fields for processing")
        for field in fields:
            logger.info(
                f"  - {field['name']} ({field['crop_type']}): "
                f"planted {field['planting_date']}"
            )

        return fields

    @task
    def process_field(field: dict, **context) -> dict:
        """
        Process a single field - this task is dynamically mapped.

        One instance of this task runs for each eligible field.
        Computes NDVI and band statistics for the field polygon.
        """
        from hydrosat.services.processing import process_single_field

        execution_date = context["ds"]
        field_id = field["field_id"]

        logger.info(f"Processing field {field_id} ({field['name']})")
        logger.info(f"  Crop: {field['crop_type']}, Planted: {field['planting_date']}")

        result = process_single_field(field, execution_date)

        if result.get("status") == "processed":
            ndvi = result.get("statistics", {}).get("ndvi", {}).get("mean", "N/A")
            days = result.get("days_since_planting", 0)
            ndvi_str = f"{ndvi:.3f}" if isinstance(ndvi, (int, float)) else str(ndvi)
            logger.info(f"  Processed: NDVI={ndvi_str}, Days since planting={days}")
        else:
            logger.error(f"  Failed: {result.get('error', 'Unknown error')}")

        return result

    @task
    def generate_daily_report(results: list, **context) -> dict:
        """
        Aggregate results and generate the daily processing report.

        Collects results from all dynamically mapped process_field tasks.
        """
        from hydrosat.services.processing import generate_daily_report

        execution_date = context["ds"]

        successful = [r for r in results if r.get("status") == "processed"]
        failed = [r for r in results if r.get("status") != "processed"]

        logger.info(f"Field processing complete for {execution_date}")
        logger.info(f"  Processed: {len(successful)}/{len(results)} fields")

        if failed:
            logger.warning(f"  Failed fields: {[r['field_id'] for r in failed]}")

        # Compute average NDVI across all fields
        ndvi_values = [
            r.get("statistics", {}).get("ndvi", {}).get("mean")
            for r in successful
            if r.get("statistics", {}).get("ndvi", {}).get("mean") is not None
        ]

        if ndvi_values:
            avg_ndvi = sum(ndvi_values) / len(ndvi_values)
            logger.info(f"  Average NDVI: {avg_ndvi:.4f}")

        # Generate and store the report
        report_uri = generate_daily_report(execution_date, results)
        logger.info(f"  Report saved to: {report_uri}")

        # Summary by crop type
        crop_counts = {}
        for r in successful:
            crop = r.get("crop_type", "unknown")
            crop_counts[crop] = crop_counts.get(crop, 0) + 1

        return {
            "date": execution_date,
            "total_fields": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "average_ndvi": avg_ndvi if ndvi_values else None,
            "fields_by_crop": crop_counts,
            "report_uri": report_uri,
        }

    # DAG flow with dynamic task mapping:
    # 1. Sensor waits for satellite data to be available
    # 2. Discover fields eligible for processing (planting_date <= execution_date)
    # 3. process_field.expand() creates N parallel tasks (one per field)
    # 4. Generate daily report aggregating all field results

    wait_for_satellite_data()
    fields = discover_eligible_fields()
    field_results = process_field.expand(field=fields)
    generate_daily_report(field_results)
