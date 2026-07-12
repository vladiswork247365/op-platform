"""Хранилище файлов. R2 (S3-совместимое) с локальным фолбэком.

Абстракция одна: put_file / put_bytes → возвращают публичный URL.
Если R2-креды не заданы — пишем на диск и отдаём file://-URL (для локального прогона).
"""
from __future__ import annotations

import mimetypes
import os
import shutil
from pathlib import Path

from .config import settings


class Storage:
    def put_file(self, local_path: str, key: str) -> str:  # pragma: no cover - интерфейс
        raise NotImplementedError

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:  # pragma: no cover
        raise NotImplementedError


class LocalStorage(Storage):
    """Фолбэк: складывает файлы в LOCAL_STORAGE_DIR, отдаёт file:// URL."""

    def __init__(self, base_dir: str):
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _dest(self, key: str) -> Path:
        dest = self.base / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def put_file(self, local_path: str, key: str) -> str:
        dest = self._dest(key)
        if Path(local_path).resolve() != dest:
            shutil.copyfile(local_path, dest)
        return dest.as_uri()

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        dest = self._dest(key)
        dest.write_bytes(data)
        return dest.as_uri()


class R2Storage(Storage):
    """Cloudflare R2 через boto3 (S3 API)."""

    def __init__(self):
        import boto3  # локальный импорт: не тянем boto3 в локальном фолбэке

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        self.bucket = settings.R2_BUCKET

    def _url(self, key: str) -> str:
        if settings.R2_PUBLIC_BASE_URL:
            return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
        # Пресайн на скачивание (7 дней) — когда публичного домена нет.
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=7 * 24 * 3600
        )

    def put_file(self, local_path: str, key: str) -> str:
        ctype = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
        self.client.upload_file(local_path, self.bucket, key, ExtraArgs={"ContentType": ctype})
        return self._url(key)

    def put_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self._url(key)


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = R2Storage() if settings.r2_enabled else LocalStorage(settings.LOCAL_STORAGE_DIR)
    return _storage
