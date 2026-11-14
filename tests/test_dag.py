# DAG wrap
"""The live DAG calls run_date. Importing it is optional; the source is the contract."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DAG_PATH = REPO / "dags" / "field_days_dag.py"


def test_dag_source_calls_the_same_pipeline() -> None:
    text = DAG_PATH.read_text()
    assert "from geopipeline.pipeline import run_scheduled_date" in text
    assert 'dag_id="field_days"' in text
    assert "run_scheduled_date(" in text
    assert "satellite_ingestion" not in text
    assert "PokeReturnValue" not in text


def test_field_days_dag_imports_when_airflow_is_installed() -> None:
    if os.environ.get("GEOPIPELINE_REQUIRE_AIRFLOW") != "1":
        pytest.importorskip("airflow")
    import sys

    sys.path.insert(0, str(DAG_PATH.parent))
    from field_days_dag import dag

    assert dag.dag_id == "field_days"
    assert "run_field_days" in dag.task_dict
    assert dag.catchup is False


def test_ci_and_makefile_wire_airflow_dag_import() -> None:
    makefile = (REPO / "Makefile").read_text()
    ci_workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text()

    def _recipe(target: str) -> str:
        match = re.search(rf"(?m)^{re.escape(target)}:\n((?:\t.*\n?)+)", makefile)
        assert match is not None, f"make target {target} missing"
        return match.group(1)

    install_recipe = _recipe("install")
    assert "--extra dev" in install_recipe
    assert "--extra airflow" not in install_recipe

    airflow_recipe = _recipe("test-airflow")
    assert "--extra airflow" in airflow_recipe
    assert "--frozen" in airflow_recipe
    assert "GEOPIPELINE_REQUIRE_AIRFLOW=1" in airflow_recipe
    assert "tests/test_dag.py" in airflow_recipe

    assert "test-airflow" in _recipe("help")
    assert "make test-airflow" in ci_workflow
