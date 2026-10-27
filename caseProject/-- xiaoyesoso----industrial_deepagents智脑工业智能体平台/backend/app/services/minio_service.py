"""MinIO object storage service; SDK is imported lazily for test monkeypatching."""
from __future__ import annotations

import io

from ..config import Settings, get_settings


class MinioService:
    _ensured_buckets: set[tuple[str, str]] = set()

    def __init__(self, settings: Settings | None = None, client=None):
        self.settings = settings or get_settings()
        if client is not None:
            self.client = client
        else:
            try:
                from minio import Minio
            except ImportError as exc:
                raise RuntimeError("MinIO SDK is not installed") from exc
            self.client = Minio(
                self.settings.minio_endpoint,
                access_key=self.settings.minio_access_key,
                secret_key=self.settings.minio_secret_key,
                secure=self.settings.minio_secure,
            )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        key = (self.settings.minio_endpoint, self.settings.minio_bucket)
        if key in self._ensured_buckets:
            return
        if not self.client.bucket_exists(self.settings.minio_bucket):
            self.client.make_bucket(self.settings.minio_bucket)
        self._ensured_buckets.add(key)

    def put(self, object_name: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            self.settings.minio_bucket,
            object_name,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    def get(self, object_name: str) -> bytes:
        response = self.client.get_object(self.settings.minio_bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
