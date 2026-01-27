# S3/MinIO Storage Client
"""Client for interacting with S3-compatible object storage (MinIO)."""

import json
import os

import boto3
from botocore.exceptions import ClientError


def create_s3_client(config: dict):
    """
    Create a boto3 S3 client configured for MinIO.

    Args:
        config: Dict with 'endpoint', 'access_key', 'secret_key', 'secure'

    Returns:
        boto3 S3 client
    """
    endpoint_url = (
        f"{'https' if config.get('secure') else 'http'}://{config['endpoint']}"
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name="us-east-1",  # MinIO default
    )


def ensure_bucket_exists(client, bucket: str) -> None:
    """Create bucket if it doesn't exist."""
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def upload_file(client, local_path: str, bucket: str, key: str) -> str:
    """
    Upload a file to S3/MinIO.

    Args:
        client: boto3 S3 client
        local_path: Path to local file
        bucket: Target bucket name
        key: Object key (path in bucket)

    Returns:
        The S3 URI of the uploaded object
    """
    ensure_bucket_exists(client, bucket)
    client.upload_file(local_path, bucket, key)
    return f"s3://{bucket}/{key}"


def upload_json(client, data: dict, bucket: str, key: str) -> str:
    """
    Upload a JSON object to S3/MinIO.

    Args:
        client: boto3 S3 client
        data: Dictionary to serialize as JSON
        bucket: Target bucket name
        key: Object key (path in bucket)

    Returns:
        The S3 URI of the uploaded object
    """
    ensure_bucket_exists(client, bucket)
    body = json.dumps(data, indent=2, default=str)
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    return f"s3://{bucket}/{key}"


def download_file(client, bucket: str, key: str, local_path: str) -> str:
    """
    Download a file from S3/MinIO.

    Args:
        client: boto3 S3 client
        bucket: Source bucket name
        key: Object key (path in bucket)
        local_path: Local path to save file

    Returns:
        Path to the downloaded file
    """
    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
    client.download_file(bucket, key, local_path)
    return local_path


def list_objects(client, bucket: str, prefix: str = "") -> list:
    """
    List objects in a bucket with optional prefix filter.

    Args:
        client: boto3 S3 client
        bucket: Bucket name
        prefix: Key prefix to filter by

    Returns:
        List of object keys

    Raises:
        ClientError: For auth/permission errors (non-404 errors)
    """
    try:
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("NoSuchBucket", "NoSuchKey", "404"):
            return []
        raise  # Re-raise auth/permission errors


def object_exists(client, bucket: str, key: str) -> bool:
    """
    Check if an object exists in S3/MinIO.

    Raises:
        ClientError: For auth/permission errors (non-404 errors)
    """
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise  # Re-raise auth/permission errors


def count_objects(client, bucket: str, prefix: str = "") -> int:
    """Count objects in a bucket with optional prefix filter."""
    return len(list_objects(client, bucket, prefix))
