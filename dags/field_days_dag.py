# Field-day DAG
"""One Airflow DAG that wraps the same Python pipeline as the CLI. No scheduler required."""

from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.decorators import task

from geopipeline.pipeline import run_scheduled_date

default_args = {
    "owner": "geopipeline",
    "depends_on_past": False,
}


with DAG(
    dag_id="field_days",
    default_args=default_args,
    description="Build Landing and Field-day Product for the execution date",
    schedule="@daily",
    start_date=datetime(2024, 4, 1),
    catchup=False,
    tags=["geopipeline", "field-days"],
) as dag:

    @task
    def run_field_days(**context) -> str:
        return run_scheduled_date(context["ds"])

    run_field_days()
