# Tests for Ingestion Service
"""Unit tests for the ingestion service."""

from unittest.mock import patch, MagicMock

from hydrosat.services import ingestion


class TestDiscoverTilesForDate:
    """Tests for discover_tiles_for_date function."""

    @patch("hydrosat.services.ingestion.get_region_config")
    @patch("hydrosat.services.ingestion.get_generator_config")
    @patch("hydrosat.services.ingestion.satellite_data")
    def test_uses_default_region_if_none(
        self, mock_sat_data, mock_gen_config, mock_region_config
    ):
        """Should use default region config when not provided."""
        mock_region_config.return_value = {"bbox": [0, 0, 1, 1], "tile_size": 0.5}
        mock_gen_config.return_value = {"seed": 42}
        mock_sat_data.generate_tile_metadata.return_value = []

        ingestion.discover_tiles_for_date("2024-01-15")

        mock_region_config.assert_called_once()
        mock_sat_data.generate_tile_metadata.assert_called_once()

    @patch("hydrosat.services.ingestion.get_generator_config")
    @patch("hydrosat.services.ingestion.satellite_data")
    def test_uses_provided_region(self, mock_sat_data, mock_gen_config):
        """Should use provided region config."""
        custom_region = {"bbox": [5, 5, 6, 6], "tile_size": 1.0}
        mock_gen_config.return_value = {"seed": 42}
        mock_sat_data.generate_tile_metadata.return_value = []

        ingestion.discover_tiles_for_date("2024-01-15", region=custom_region)

        mock_sat_data.generate_tile_metadata.assert_called_once_with(
            custom_region, "2024-01-15", seed=42
        )


class TestIngestSingleTile:
    """Tests for ingest_single_tile function."""

    @patch("hydrosat.services.ingestion.get_storage_config")
    @patch("hydrosat.services.ingestion.get_generator_config")
    @patch("hydrosat.services.ingestion.satellite_data")
    @patch("hydrosat.services.ingestion.storage")
    def test_returns_ingestion_result(
        self, mock_storage, mock_sat_data, mock_gen_config, mock_storage_config
    ):
        """Should return dict with tile_id, s3_uri, and status."""
        mock_storage_config.return_value = {
            "endpoint": "localhost:9000",
            "access_key": "test",
            "secret_key": "test",
            "secure": False,
            "raw_bucket": "raw-imagery",
        }
        mock_gen_config.return_value = {"seed": 42, "raster_size": 64}
        mock_sat_data.generate_raster_file.return_value = "/tmp/tile.tif"
        mock_storage.create_s3_client.return_value = MagicMock()
        mock_storage.upload_file.return_value = (
            "s3://raw-imagery/2024-01-15/TEST001.tif"
        )
        mock_storage.upload_json.return_value = (
            "s3://raw-imagery/2024-01-15/TEST001_metadata.json"
        )

        tile = {
            "tile_id": "TEST001",
            "date": "2024-01-15",
            "bbox": [0, 0, 0.5, 0.5],
            "bands": ["B02", "B03", "B04", "B08"],
        }

        result = ingestion.ingest_single_tile(tile)

        assert result["tile_id"] == "TEST001"
        assert result["date"] == "2024-01-15"
        assert result["status"] == "ingested"
        assert "s3_uri" in result


class TestGetIngestedTileCount:
    """Tests for get_ingested_tile_count function."""

    @patch("hydrosat.services.ingestion.get_storage_config")
    @patch("hydrosat.services.ingestion.storage")
    def test_counts_raster_files_not_metadata(self, mock_storage, mock_storage_config):
        """Should count raster files (.tif and .npy), not metadata."""
        mock_storage_config.return_value = {
            "endpoint": "localhost:9000",
            "access_key": "test",
            "secret_key": "test",
            "secure": False,
            "raw_bucket": "raw-imagery",
        }
        mock_storage.create_s3_client.return_value = MagicMock()
        mock_storage.list_objects.return_value = [
            "2024-01-15/tile1.tif",
            "2024-01-15/tile1_metadata.json",
            "2024-01-15/tile2.tif",
            "2024-01-15/tile2_metadata.json",
        ]

        count = ingestion.get_ingested_tile_count("2024-01-15")

        assert count == 2

    @patch("hydrosat.services.ingestion.get_storage_config")
    @patch("hydrosat.services.ingestion.storage")
    def test_counts_npy_files_when_rasterio_missing(
        self, mock_storage, mock_storage_config
    ):
        """Should count .npy files when rasterio is not available."""
        mock_storage_config.return_value = {
            "endpoint": "localhost:9000",
            "access_key": "test",
            "secret_key": "test",
            "secure": False,
            "raw_bucket": "raw-imagery",
        }
        mock_storage.create_s3_client.return_value = MagicMock()
        mock_storage.list_objects.return_value = [
            "2024-01-15/tile1.npy",
            "2024-01-15/tile1_meta.json",
            "2024-01-15/tile2.npy",
            "2024-01-15/tile2_meta.json",
        ]

        count = ingestion.get_ingested_tile_count("2024-01-15")

        assert count == 2
