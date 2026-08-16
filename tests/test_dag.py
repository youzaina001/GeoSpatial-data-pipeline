# DAG wrap
"""The live DAG calls run_date. Importing it is optional; the source is the contract."""

from __future__ import annotations

from pathlib import Path

import pytest

DAG_PATH = Path(__file__).resolve().parents[1] / "dags" / "field_days_dag.py"


def test_dag_source_calls_the_same_pipeline() -> None:
    text = DAG_PATH.read_text()
    assert "from geopipeline.pipeline import run_scheduled_date" in text
    assert 'dag_id="field_days"' in text
    assert "run_scheduled_date(" in text
    assert "satellite_ingestion" not in text
    assert "PokeReturnValue" not in text


def test_field_days_dag_imports_when_airflow_is_installed() -> None:
    pytest.importorskip("airflow")
    import sys

    sys.path.insert(0, str(DAG_PATH.parent))
    from field_days_dag import dag

    assert dag.dag_id == "field_days"
    assert "run_field_days" in dag.task_dict
    assert dag.catchup is False
