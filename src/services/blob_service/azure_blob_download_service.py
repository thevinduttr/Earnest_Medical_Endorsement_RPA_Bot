from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from azure.storage.blob import BlobServiceClient


_BLOB_ENV_PATH = Path("config/env/blob.env")
_BLOB_ENV_LOADED = False


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def load_blob_environment(env_path: Path = _BLOB_ENV_PATH) -> None:
    global _BLOB_ENV_LOADED
    if _BLOB_ENV_LOADED:
        return

    _load_env_file(env_path)
    _BLOB_ENV_LOADED = True


def get_blob_connection_string() -> str:
    load_blob_environment()

    for key in (
        "AZURE_STORAGE_CONNECTION_STRING",
        "BLOB_CONNECTION_STRING",
        "AZURE_BLOB_CONNECTION_STRING",
    ):
        connection_string = str(os.getenv(key) or "").strip()
        if connection_string:
            return connection_string

    raise ValueError(
        "Blob storage connection string is missing. Set one of: "
        "AZURE_STORAGE_CONNECTION_STRING, BLOB_CONNECTION_STRING, AZURE_BLOB_CONNECTION_STRING"
    )


class AzureBlobDownloadService:
    def __init__(self, logger=None):
        self.logger = logger
        self.blob_service_client = BlobServiceClient.from_connection_string(get_blob_connection_string())
        if self.logger:
            self.logger.info("[Blob] Connected to Azure Blob Storage.")

    def download_blob(
        self,
        container_name: str,
        blob_path: str,
        output_path: Path,
    ) -> Path:
        container_name = str(container_name or "").strip()
        blob_path = str(blob_path or "").strip().lstrip("/")
        if not container_name or not blob_path:
            raise ValueError("container_name and blob_path are required for blob download")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        blob_client = self.blob_service_client.get_blob_client(container=container_name, blob=blob_path)
        with output_path.open("wb") as handle:
            data = blob_client.download_blob()
            data.readinto(handle)

        if self.logger:
            self.logger.info(f"[Blob] Downloaded: {container_name}/{blob_path} -> {output_path}")

        return output_path


def extension_from_content_type(content_type: Optional[str]) -> str:
    value = str(content_type or "").strip().lower()
    if value == "image/jpeg":
        return ".jpg"
    if value == "image/png":
        return ".png"
    if value == "application/pdf":
        return ".pdf"
    return ""
