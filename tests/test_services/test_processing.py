# Tests for Processing Service
"""Tests for geopipeline.services.processing module."""

import pytest
from unittest.mock import patch
import numpy as np

from geopipeline.services.processing import (
    compute_ndvi,
    aggregate_field_results,
    discover_fields_for_processing,
)


class TestComputeNdvi:
    """Tests for NDVI computation."""

    def test_computes_correct_ndvi(self):
        """NDVI should be computed correctly."""
        red = np.array([[100, 200], [300, 400]], dtype=np.uint16)
        nir = np.array([[500, 600], [700, 800]], dtype=np.uint16)

        ndvi = compute_ndvi(red, nir)

        # NDVI = (NIR - Red) / (NIR + Red)
        # For first pixel: (500 - 100) / (500 + 100) = 400/600 = 0.667
        assert ndvi.shape == (2, 2)
        assert pytest.approx(ndvi[0, 0], rel=0.01) == 0.667

    def test_handles_zero_denominator(self):
        """Should handle division by zero gracefully."""
        red = np.array([[0]], dtype=np.uint16)
        nir = np.array([[0]], dtype=np.uint16)

        ndvi = compute_ndvi(red, nir)

        # Should not raise, should return 0
        assert ndvi[0, 0] == 0.0

    def test_clips_to_valid_range(self):
        """NDVI should be clipped to [-1, 1]."""
        red = np.array([[1000]], dtype=np.uint16)
        nir = np.array([[100]], dtype=np.uint16)

        ndvi = compute_ndvi(red, nir)

        assert ndvi[0, 0] >= -1
        assert ndvi[0, 0] <= 1


class TestAggregateFieldResults:
    """Tests for field result aggregation."""

    def test_counts_successful_and_failed(self):
        """Should correctly count successful and failed fields."""
        results = [
            {
                "field_id": "F1",
                "status": "processed",
                "statistics": {"ndvi": {"mean": 0.5}},
            },
            {
                "field_id": "F2",
                "status": "processed",
                "statistics": {"ndvi": {"mean": 0.6}},
            },
            {"field_id": "F3", "status": "failed", "error": "Some error"},
        ]

        summary = aggregate_field_results(results, "2024-06-01")

        assert summary["total_fields"] == 3
        assert summary["successful"] == 2
        assert summary["failed"] == 1

    def test_computes_average_ndvi(self):
        """Should compute average NDVI across successful fields."""
        results = [
            {
                "field_id": "F1",
                "status": "processed",
                "statistics": {"ndvi": {"mean": 0.4}},
            },
            {
                "field_id": "F2",
                "status": "processed",
                "statistics": {"ndvi": {"mean": 0.6}},
            },
        ]

        summary = aggregate_field_results(results, "2024-06-01")

        assert summary["average_ndvi"] == pytest.approx(0.5, rel=0.01)

    def test_counts_by_crop_type(self):
        """Should count fields by crop type."""
        results = [
            {
                "field_id": "F1",
                "status": "processed",
                "crop_type": "wheat",
                "statistics": {},
            },
            {
                "field_id": "F2",
                "status": "processed",
                "crop_type": "wheat",
                "statistics": {},
            },
            {
                "field_id": "F3",
                "status": "processed",
                "crop_type": "corn",
                "statistics": {},
            },
        ]

        summary = aggregate_field_results(results, "2024-06-01")

        assert summary["fields_by_crop"]["wheat"] == 2
        assert summary["fields_by_crop"]["corn"] == 1

    def test_handles_empty_results(self):
        """Should handle empty results list."""
        summary = aggregate_field_results([], "2024-06-01")

        assert summary["total_fields"] == 0
        assert summary["successful"] == 0
        assert summary["average_ndvi"] is None


class TestDiscoverFieldsForProcessing:
    """Tests for field discovery."""

    @patch("geopipeline.services.processing.get_aoi_config")
    @patch("geopipeline.services.processing.get_fields_config")
    def test_returns_list_of_dicts(self, mock_fields_config, mock_aoi_config):
        """Should return list of field dictionaries."""
        mock_aoi_config.return_value = {
            "name": "test-aoi",
            "bbox": [2.0, 48.0, 3.0, 49.0],
        }
        mock_fields_config.return_value = {
            "num_fields": 3,
            "seed": 42,
        }

        fields = discover_fields_for_processing("2024-06-01")

        assert isinstance(fields, list)
        for field in fields:
            assert isinstance(field, dict)
            assert "field_id" in field
            assert "planting_date" in field

    @patch("geopipeline.services.processing.get_aoi_config")
    @patch("geopipeline.services.processing.get_fields_config")
    def test_filters_by_execution_date(self, mock_fields_config, mock_aoi_config):
        """Should only return fields eligible for the execution date."""
        mock_aoi_config.return_value = {
            "name": "test-aoi",
            "bbox": [2.0, 48.0, 3.0, 49.0],
        }
        mock_fields_config.return_value = {
            "num_fields": 6,
            "seed": 42,
        }

        # Early date should have fewer eligible fields
        early_fields = discover_fields_for_processing("2024-01-01")
        # Later date should have more eligible fields
        later_fields = discover_fields_for_processing("2024-06-01")

        # Later date should have >= eligible fields
        assert len(later_fields) >= len(early_fields)
