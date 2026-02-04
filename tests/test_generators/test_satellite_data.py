# Tests for Satellite Data Generator
"""Unit tests for the synthetic satellite data generator."""

import os
import tempfile
import numpy as np

from geopipeline.generators import satellite_data


class TestGenerateTileMetadata:
    """Tests for generate_tile_metadata function."""

    def test_generates_correct_number_of_tiles(self):
        """Should generate tiles based on region size and tile_size."""
        region = {
            "name": "test",
            "bbox": [0.0, 0.0, 1.0, 1.0],  # 1x1 degree
            "tile_size": 0.5,  # 4 tiles expected (2x2 grid)
        }
        tiles = satellite_data.generate_tile_metadata(region, "2024-01-15")
        assert len(tiles) == 4

    def test_tile_has_required_fields(self):
        """Each tile should have all required metadata fields."""
        region = {"bbox": [0.0, 0.0, 0.5, 0.5], "tile_size": 0.5}
        tiles = satellite_data.generate_tile_metadata(region, "2024-01-15")

        tile = tiles[0]
        assert "tile_id" in tile
        assert "date" in tile
        assert "bbox" in tile
        assert "cloud_coverage" in tile
        assert "bands" in tile
        assert "crs" in tile

    def test_tile_id_is_deterministic(self):
        """Same inputs should produce same tile_id."""
        region = {"bbox": [0.0, 0.0, 0.5, 0.5], "tile_size": 0.5}
        tiles1 = satellite_data.generate_tile_metadata(region, "2024-01-15", seed=42)
        tiles2 = satellite_data.generate_tile_metadata(region, "2024-01-15", seed=42)

        assert tiles1[0]["tile_id"] == tiles2[0]["tile_id"]

    def test_cloud_coverage_in_valid_range(self):
        """Cloud coverage should be between 0 and 100."""
        region = {"bbox": [0.0, 0.0, 2.0, 2.0], "tile_size": 0.5}
        tiles = satellite_data.generate_tile_metadata(region, "2024-01-15")

        for tile in tiles:
            assert 0 <= tile["cloud_coverage"] <= 100


class TestGenerateRasterData:
    """Tests for generate_raster_data function."""

    def test_returns_correct_shape(self):
        """Raster data should have correct dimensions."""
        data = satellite_data.generate_raster_data(bands=4, height=256, width=256)
        assert data.shape == (4, 256, 256)

    def test_returns_uint16_dtype(self):
        """Data should be uint16 for satellite imagery."""
        data = satellite_data.generate_raster_data(bands=4, height=64, width=64)
        assert data.dtype == np.uint16

    def test_values_in_expected_range(self):
        """Pixel values should simulate realistic reflectance."""
        data = satellite_data.generate_raster_data(bands=4, height=64, width=64)
        assert data.min() >= 0
        assert data.max() <= 65535  # uint16 max

    def test_reproducible_with_seed(self):
        """Same seed should produce same data."""
        data1 = satellite_data.generate_raster_data(4, 64, 64, seed=42)
        data2 = satellite_data.generate_raster_data(4, 64, 64, seed=42)
        np.testing.assert_array_equal(data1, data2)


class TestGenerateRasterFile:
    """Tests for generate_raster_file function."""

    def test_creates_file(self):
        """Should create a raster file in the output directory."""
        tile = {
            "tile_id": "TEST001",
            "date": "2024-01-15",
            "bbox": [0.0, 0.0, 0.5, 0.5],
            "bands": ["B02", "B03", "B04", "B08"],
            "crs": "EPSG:4326",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = satellite_data.generate_raster_file(
                tile, temp_dir, raster_size=64
            )
            assert os.path.exists(output_path)

    def test_file_has_expected_name(self):
        """Output file should follow naming convention."""
        tile = {
            "tile_id": "TEST001",
            "date": "2024-01-15",
            "bbox": [0.0, 0.0, 0.5, 0.5],
            "bands": ["B02", "B03", "B04", "B08"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = satellite_data.generate_raster_file(tile, temp_dir)
            filename = os.path.basename(output_path)
            assert "TEST001" in filename
            assert "2024-01-15" in filename


class TestGenerateTileId:
    """Tests for generate_tile_id function."""

    def test_deterministic(self):
        """Same inputs should produce same ID."""
        id1 = satellite_data.generate_tile_id(10.5, 45.0, "2024-01-15")
        id2 = satellite_data.generate_tile_id(10.5, 45.0, "2024-01-15")
        assert id1 == id2

    def test_different_for_different_coordinates(self):
        """Different coordinates should produce different IDs."""
        id1 = satellite_data.generate_tile_id(10.5, 45.0, "2024-01-15")
        id2 = satellite_data.generate_tile_id(11.0, 45.0, "2024-01-15")
        assert id1 != id2

    def test_starts_with_t(self):
        """Tile ID should start with 'T' prefix."""
        tile_id = satellite_data.generate_tile_id(10.5, 45.0, "2024-01-15")
        assert tile_id.startswith("T")
