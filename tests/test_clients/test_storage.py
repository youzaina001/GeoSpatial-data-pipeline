# Tests for Storage Client
"""Unit tests for the S3/MinIO storage client."""

import json
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from geopipeline.clients import storage


class TestCreateS3Client:
    """Tests for create_s3_client function."""

    @patch("geopipeline.clients.storage.boto3")
    def test_creates_client_with_correct_endpoint(self, mock_boto3):
        """Should create client with configured endpoint."""
        config = {
            "endpoint": "localhost:9000",
            "access_key": "test_access",
            "secret_key": "test_secret",
            "secure": False,
        }
        storage.create_s3_client(config)

        mock_boto3.client.assert_called_once()
        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"] == "http://localhost:9000"
        assert call_kwargs["aws_access_key_id"] == "test_access"
        assert call_kwargs["aws_secret_access_key"] == "test_secret"

    @patch("geopipeline.clients.storage.boto3")
    def test_uses_https_when_secure(self, mock_boto3):
        """Should use HTTPS when secure=True."""
        config = {
            "endpoint": "minio.example.com:9000",
            "access_key": "test",
            "secret_key": "test",
            "secure": True,
        }
        storage.create_s3_client(config)

        call_kwargs = mock_boto3.client.call_args[1]
        assert call_kwargs["endpoint_url"].startswith("https://")


class TestEnsureBucketExists:
    """Tests for ensure_bucket_exists function."""

    def test_does_not_create_if_exists(self):
        """Should not create bucket if it already exists."""
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}  # Bucket exists

        storage.ensure_bucket_exists(mock_client, "existing-bucket")

        mock_client.create_bucket.assert_not_called()

    def test_creates_bucket_if_not_exists(self):
        """Should create bucket if it doesn't exist."""
        mock_client = MagicMock()
        mock_client.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_bucket"
        )

        storage.ensure_bucket_exists(mock_client, "new-bucket")

        mock_client.create_bucket.assert_called_once_with(Bucket="new-bucket")


class TestUploadFile:
    """Tests for upload_file function."""

    def test_returns_s3_uri(self):
        """Should return S3 URI of uploaded object."""
        mock_client = MagicMock()

        result = storage.upload_file(
            mock_client,
            "/tmp/test.tif",
            "raw-imagery",
            "2024-01-15/tile.tif",
        )

        assert result == "s3://raw-imagery/2024-01-15/tile.tif"

    def test_calls_upload_file(self):
        """Should call boto3 upload_file method."""
        mock_client = MagicMock()

        storage.upload_file(
            mock_client,
            "/tmp/test.tif",
            "raw-imagery",
            "2024-01-15/tile.tif",
        )

        mock_client.upload_file.assert_called_once_with(
            "/tmp/test.tif",
            "raw-imagery",
            "2024-01-15/tile.tif",
        )


class TestUploadJson:
    """Tests for upload_json function."""

    def test_serializes_and_uploads_json(self):
        """Should serialize dict to JSON and upload."""
        mock_client = MagicMock()
        data = {"key": "value", "number": 42}

        storage.upload_json(mock_client, data, "test-bucket", "data.json")

        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "data.json"
        assert call_kwargs["ContentType"] == "application/json"

        # Verify JSON content
        uploaded_data = json.loads(call_kwargs["Body"])
        assert uploaded_data == data


class TestListObjects:
    """Tests for list_objects function."""

    def test_returns_list_of_keys(self):
        """Should return list of object keys."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "2024-01-15/tile1.tif"},
                {"Key": "2024-01-15/tile2.tif"},
            ]
        }

        result = storage.list_objects(mock_client, "raw-imagery", "2024-01-15/")

        assert len(result) == 2
        assert "2024-01-15/tile1.tif" in result
        assert "2024-01-15/tile2.tif" in result

    def test_returns_empty_list_on_error(self):
        """Should return empty list if bucket doesn't exist."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket"}}, "list_objects_v2"
        )

        result = storage.list_objects(mock_client, "nonexistent", "prefix/")

        assert result == []

    def test_raises_on_auth_error(self):
        """Should raise ClientError for auth/permission errors."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "list_objects_v2"
        )

        with pytest.raises(ClientError):
            storage.list_objects(mock_client, "bucket", "prefix/")


class TestObjectExists:
    """Tests for object_exists function."""

    def test_returns_true_if_exists(self):
        """Should return True if object exists."""
        mock_client = MagicMock()
        mock_client.head_object.return_value = {}

        assert storage.object_exists(mock_client, "bucket", "key") is True

    def test_returns_false_if_not_exists(self):
        """Should return False if object doesn't exist."""
        mock_client = MagicMock()
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "head_object"
        )

        assert storage.object_exists(mock_client, "bucket", "key") is False

    def test_raises_on_auth_error(self):
        """Should raise ClientError for auth/permission errors."""
        mock_client = MagicMock()
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "head_object"
        )

        with pytest.raises(ClientError):
            storage.object_exists(mock_client, "bucket", "key")
