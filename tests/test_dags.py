# Tests for DAG Import/Parse
"""Test that DAGs can be imported without errors."""

import sys
import pytest


class TestDagImports:
    """Tests for DAG import/parse validation."""

    @pytest.fixture(autouse=True)
    def setup_path(self):
        """Add src and dags to path for imports."""
        sys.path.insert(0, "src")
        sys.path.insert(0, "dags")
        yield

    def test_satellite_ingestion_dag_imports(self):
        """Should import satellite_ingestion DAG without errors."""
        from satellite_ingestion_dag import dag

        assert dag is not None
        assert dag.dag_id == "satellite_ingestion"
        assert "check_satellite_availability" in dag.task_dict
        assert "generate_aoi_raster" in dag.task_dict
        assert "log_ingestion_summary" in dag.task_dict

    def test_field_processing_dag_imports(self):
        """Should import field_processing DAG without errors."""
        from field_processing_dag import dag

        assert dag is not None
        assert dag.dag_id == "field_processing"
        assert "wait_for_satellite_data" in dag.task_dict
        assert "discover_eligible_fields" in dag.task_dict
        assert "process_field" in dag.task_dict
        assert "generate_daily_report" in dag.task_dict

    def test_satellite_ingestion_dag_schedule(self):
        """Should have correct schedule configuration."""
        from satellite_ingestion_dag import dag

        assert dag.schedule == "@daily"
        assert dag.catchup is False

    def test_field_processing_dag_schedule(self):
        """Should have correct schedule configuration."""
        from field_processing_dag import dag

        assert dag.schedule == "@daily"
        assert dag.catchup is False
