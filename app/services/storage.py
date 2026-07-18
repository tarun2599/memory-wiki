"""Object storage abstraction for the memory file tree."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class ObjectStorage:
    """S3-compatible object storage client."""

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        self.prefix = settings.memory_prefix.rstrip("/") + "/"
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4"),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except ClientError as exc:
                logger.warning("Could not create bucket: %s", exc)

    def _full_key(self, path: str) -> str:
        normalized = path.strip("/")
        if not normalized:
            return self.prefix
        return f"{self.prefix}{normalized}"

    def _relative_path(self, key: str) -> str:
        if key.startswith(self.prefix):
            return key[len(self.prefix) :].rstrip("/")
        return key.rstrip("/")

    def list_objects(self, directory: str = "") -> list[dict[str, Any]]:
        """List immediate children of a directory path."""
        prefix = self._full_key(directory)
        if prefix != self.prefix and not prefix.endswith("/"):
            prefix += "/"

        paginator = self._client.get_paginator("list_objects_v2")
        entries: dict[str, dict[str, Any]] = {}

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            for common_prefix in page.get("CommonPrefixes", []):
                child_prefix = common_prefix["Prefix"]
                name = child_prefix[len(prefix) :].rstrip("/")
                if name:
                    entries[name] = {
                        "name": name,
                        "path": self._relative_path(child_prefix.rstrip("/")),
                        "type": "directory",
                    }

            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix or key.endswith("/"):
                    continue
                name = key[len(prefix) :]
                if "/" in name:
                    continue
                entries[name] = {
                    "name": name,
                    "path": self._relative_path(key),
                    "type": "file",
                    "size": obj.get("Size"),
                    "last_modified": obj.get("LastModified"),
                }

        return sorted(entries.values(), key=lambda e: (e["type"] != "directory", e["name"]))

    def get_object(self, path: str) -> tuple[str, dict[str, Any] | None, datetime | None]:
        """Return (content, metadata, last_modified) for a file path."""
        key = self._full_key(path)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(path) from exc
            raise

        body = response["Body"].read().decode("utf-8")
        metadata = response.get("Metadata") or None
        last_modified = response.get("LastModified")
        return body, metadata, last_modified

    def put_object(
        self,
        path: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Write a file at path. Returns the storage key."""
        key = self._full_key(path)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            Metadata=metadata or {},
        )
        return key

    def object_exists(self, path: str) -> bool:
        key = self._full_key(path)
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_all_files(self, directory: str = "") -> list[str]:
        """Recursively list all file paths under a directory."""
        prefix = self._full_key(directory)
        if prefix != self.prefix and not prefix.endswith("/"):
            prefix += "/"

        paths: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                paths.append(self._relative_path(key))
        return paths

    def put_index(self, index_data: dict[str, Any]) -> None:
        self.put_object("_index/manifest.json", json.dumps(index_data, indent=2, default=str))

    def get_index(self) -> dict[str, Any] | None:
        try:
            content, _, _ = self.get_object("_index/manifest.json")
            return json.loads(content)
        except FileNotFoundError:
            return None
