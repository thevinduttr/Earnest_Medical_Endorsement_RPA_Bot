from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import urlparse
import zipfile

from src.services.blob_service.azure_blob_download_service import (
    AzureBlobDownloadService,
    extension_from_content_type,
)
from src.services.census_service.sukoon.addition_census import build_addition_census_file
from src.services.census_service.sukoon.deletion_census import build_deletion_census_file
from src.services.db_service.azure_db_connection import AzureSQLConnection
from src.services.db_service.sukoon.member_data_loader import load_process_selector_by_request_id
from src.utils.upload_file_paths import get_upload_paths


STATUS_TABLE = "[dbo].[EndorsementRequestStatus]"
DOCUMENT_TABLE = "[dbo].[EndorsementDocuments]"

_STATUS_ALIASES = {
    "INPROGRESS": "INPROCESS",
    "INPROCESS": "INPROCESS",
    "COMPLETED": "SUCCESS",
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED",
    "PENDING": "PENDING",
}


@dataclass(frozen=True)
class RequestPreparationSummary:
    total_requests: int
    completed_requests: int
    failed_requests: int
    skipped_requests: int


@dataclass(frozen=True)
class ClaimedRequest:
    request_id: str
    user_ids: List[str]


def _make_run_id() -> str:
    return datetime.now().strftime("run_%Y-%m-%d_%H-%M-%S")


def _normalize_request_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _build_run_log_dir(run_id: str, request_id: str | None) -> Path:
    normalized_request_id = _normalize_request_id(request_id)
    if normalized_request_id:
        return Path("data/logs") / f"request_{normalized_request_id}" / run_id
    return Path("data/logs") / run_id


def _init_logger(
    run_id: str,
    request_id: str | None = None,
    logger_name: str = "preportal",
) -> logging.Logger:
    run_dir = _build_run_log_dir(run_id=run_id, request_id=request_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(run_dir / "sukoon_preportal.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _sanitize_name(value: str, fallback: str = "DOCUMENT") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", _normalize_text(value).upper()).strip("_")
    return cleaned or fallback


def _clear_folder_contents(folder_path: Path, logger: logging.Logger) -> None:
    folder_path = Path(folder_path)
    folder_path.mkdir(parents=True, exist_ok=True)

    removed_files = 0
    removed_dirs = 0

    for item in folder_path.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink(missing_ok=True)
            removed_files += 1
        elif item.is_dir():
            shutil.rmtree(item, ignore_errors=False)
            removed_dirs += 1

    logger.info(
        f"Cleared process attachment folder: {folder_path} | "
        f"FilesRemoved={removed_files} | DirsRemoved={removed_dirs}"
    )


def _fetch_pending_requests(
    connection,
    target_request_id: str | None,
) -> Dict[str, List[str]]:
    where_sql = """
UPPER(ISNULL(EmailStatus, '')) = 'SUCCESS'
  AND UPPER(ISNULL(OcrStatus, '')) = 'SUCCESS'
  AND UPPER(ISNULL(ValidationStatus, '')) = 'SUCCESS'
  AND UPPER(ISNULL(PortalStatus, '')) = 'PENDING'
"""
    params: List[Any] = []
    if target_request_id:
        where_sql += "\n  AND RequestId = ?"
        params.append(target_request_id)

    query = f"""
SELECT RequestId, UserId
FROM {STATUS_TABLE}
WHERE {where_sql}
ORDER BY RequestId ASC, UserId ASC
"""

    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    finally:
        cursor.close()

    grouped: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        request_id = _normalize_text(row[0])
        user_id = _normalize_text(row[1])
        if not request_id or not user_id:
            continue
        if user_id not in grouped[request_id]:
            grouped[request_id].append(user_id)

    return dict(grouped)


def fetch_pending_requests(
    *,
    target_request_id: str | None = None,
    target_user_id: str | None = None,
    logger=None,
) -> Dict[str, List[str]]:
    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        grouped = _fetch_pending_requests(connection=connection, target_request_id=target_request_id)

    target_user_id_text = str(target_user_id or "").strip()
    if target_user_id_text:
        filtered: Dict[str, List[str]] = {}
        for request_id, user_ids in grouped.items():
            if target_user_id_text in user_ids:
                filtered[request_id] = [target_user_id_text]
        return filtered

    return grouped


def _claim_next_pending_request(
    connection,
    target_request_id: str | None = None,
    target_user_id: str | None = None,
) -> ClaimedRequest | None:
    target_request_id_text = _normalize_text(target_request_id)
    target_user_id_text = _normalize_text(target_user_id)

    next_request_conditions = [
        "UPPER(ISNULL(EmailStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(OcrStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(ValidationStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(PortalStatus, '')) = 'PENDING'",
    ]
    query_params: List[Any] = []

    if target_request_id_text:
        next_request_conditions.append("RequestId = ?")
        query_params.append(target_request_id_text)

    if target_user_id_text:
        next_request_conditions.append("UserId = ?")
        query_params.append(target_user_id_text)

    update_conditions = [
        "UPPER(ISNULL(status_rows.EmailStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(status_rows.OcrStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(status_rows.ValidationStatus, '')) = 'SUCCESS'",
        "UPPER(ISNULL(status_rows.PortalStatus, '')) = 'PENDING'",
    ]
    if target_user_id_text:
        update_conditions.append("status_rows.UserId = ?")
        query_params.append(target_user_id_text)

    next_request_where_sql = "\n      AND ".join(next_request_conditions)
    update_where_sql = "\n  AND ".join(update_conditions)

    query = f"""
WITH NextRequest AS (
    SELECT TOP (1) RequestId
    FROM {STATUS_TABLE} WITH (UPDLOCK, READPAST, ROWLOCK)
    WHERE {next_request_where_sql}
    GROUP BY RequestId
    ORDER BY RequestId ASC
)
UPDATE status_rows
SET PortalStatus = 'INPROCESS',
    PortalFailureReason = NULL,
    UpdatedAt = SYSUTCDATETIME()
OUTPUT inserted.RequestId, inserted.UserId
FROM {STATUS_TABLE} AS status_rows
INNER JOIN NextRequest AS next_request
    ON status_rows.RequestId = next_request.RequestId
WHERE {update_where_sql}
"""

    cursor = connection.cursor()
    try:
        cursor.execute(query, query_params)
        rows = cursor.fetchall()
        connection.commit()
    finally:
        cursor.close()

    if not rows:
        return None

    request_id = _normalize_text(rows[0][0])
    user_ids: List[str] = []
    for row in rows:
        user_id = _normalize_text(row[1])
        if user_id and user_id not in user_ids:
            user_ids.append(user_id)

    if not request_id or not user_ids:
        return None

    return ClaimedRequest(request_id=request_id, user_ids=user_ids)


def claim_next_pending_request(
    *,
    target_request_id: str | None = None,
    target_user_id: str | None = None,
    logger=None,
) -> ClaimedRequest | None:
    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        return _claim_next_pending_request(
            connection=connection,
            target_request_id=target_request_id,
            target_user_id=target_user_id,
        )


def update_portal_status_for_users(
    *,
    request_id: str,
    user_ids: Iterable[str],
    status: str,
    failure_reason: str | None,
    logger=None,
) -> None:
    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        _update_portal_status_for_users(
            connection=connection,
            request_id=request_id,
            user_ids=user_ids,
            status=status,
            failure_reason=failure_reason,
        )


def _update_portal_status_for_users(
    connection,
    request_id: str,
    user_ids: Iterable[str],
    status: str,
    failure_reason: str | None,
) -> None:
    user_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not user_ids:
        return

    normalized_status = _STATUS_ALIASES.get(str(status or "").strip().upper())
    if not normalized_status:
        raise ValueError(f"Unsupported PortalStatus value requested: {status}")

    placeholders = ", ".join("?" for _ in user_ids)
    query = f"""
UPDATE {STATUS_TABLE}
SET PortalStatus = ?,
    PortalFailureReason = ?,
    UpdatedAt = SYSUTCDATETIME()
WHERE RequestId = ?
  AND UserId IN ({placeholders})
"""

    normalized_reason = None if not _normalize_text(failure_reason) else str(failure_reason)
    params = [normalized_status, normalized_reason, request_id, *user_ids]
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        connection.commit()
    finally:
        cursor.close()


def _fetch_request_documents(connection, request_id: str) -> List[Dict[str, Any]]:
    query = f"""
SELECT DocumentId, RequestId, UserId, DocumentType, BlobUrl, BlobContainer, BlobPath,
       FileName, ContentType, FileSizeBytes, UploadedAt
FROM {DOCUMENT_TABLE}
WHERE RequestId = ?
  AND ISNULL(IsDeleted, 0) = 0
ORDER BY UserId ASC, UploadedAt ASC, DocumentId ASC
"""

    cursor = connection.cursor()
    try:
        cursor.execute(query, [request_id])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
    finally:
        cursor.close()

    return [
        {columns[index]: row[index] for index in range(len(columns))}
        for row in rows
    ]


def _fetch_request_documents_for_users(
    connection,
    request_id: str,
    user_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    normalized_user_ids = [str(user_id).strip() for user_id in user_ids if str(user_id).strip()]
    if not normalized_user_ids:
        return []

    placeholders = ", ".join("?" for _ in normalized_user_ids)
    query = f"""
SELECT DocumentId, RequestId, UserId, DocumentType, BlobUrl, BlobContainer, BlobPath,
       FileName, ContentType, FileSizeBytes, UploadedAt
FROM {DOCUMENT_TABLE}
WHERE RequestId = ?
  AND ISNULL(IsDeleted, 0) = 0
  AND UserId IN ({placeholders})
ORDER BY UserId ASC, UploadedAt ASC, DocumentId ASC
"""

    cursor = connection.cursor()
    try:
        cursor.execute(query, [request_id, *normalized_user_ids])
        rows = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
    finally:
        cursor.close()

    return [
        {columns[index]: row[index] for index in range(len(columns))}
        for row in rows
    ]


def _resolve_blob_location(document: Dict[str, Any]) -> Tuple[str, str]:
    container = _normalize_text(document.get("BlobContainer"))
    blob_path = _normalize_text(document.get("BlobPath")).lstrip("/")

    if container and blob_path:
        return container, blob_path

    blob_url = _normalize_text(document.get("BlobUrl"))
    if not blob_url:
        raise ValueError("BlobContainer/BlobPath and BlobUrl are both missing")

    parsed = urlparse(blob_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError(f"Unable to parse BlobUrl: {blob_url}")

    container = path_parts[0]
    blob_path = "/".join(path_parts[1:])
    return container, blob_path


def _resolve_extension(document: Dict[str, Any], blob_path: str) -> str:
    for raw_value in (document.get("FileName"), blob_path):
        text = _normalize_text(raw_value)
        suffix = Path(text).suffix
        if suffix:
            return suffix

    from_content_type = extension_from_content_type(document.get("ContentType"))
    if from_content_type:
        return from_content_type
    return ".bin"


def _download_documents_user_wise(
    blob_service: AzureBlobDownloadService,
    request_documents: List[Dict[str, Any]],
    destination_root: Path,
    logger: logging.Logger,
) -> Tuple[Dict[str, List[Path]], Dict[str, List[str]], List[Path]]:
    downloaded_by_user: Dict[str, List[Path]] = defaultdict(list)
    errors_by_user: Dict[str, List[str]] = defaultdict(list)
    all_downloaded: List[Path] = []
    duplicate_counter: Dict[Tuple[str, str], int] = defaultdict(int)

    for document in request_documents:
        user_id = _normalize_text(document.get("UserId"))
        if not user_id:
            continue

        document_type = _sanitize_name(document.get("DocumentType"), fallback="DOCUMENT")
        try:
            container_name, blob_path = _resolve_blob_location(document)
            extension = _resolve_extension(document, blob_path)

            duplicate_counter[(user_id, document_type)] += 1
            doc_index = duplicate_counter[(user_id, document_type)]
            suffix = "" if doc_index == 1 else f"_{doc_index}"
            output_name = f"{document_type}{suffix}{extension}"

            output_path = destination_root / f"user_{user_id}" / output_name
            downloaded_path = blob_service.download_blob(
                container_name=container_name,
                blob_path=blob_path,
                output_path=output_path,
            )

            downloaded_by_user[user_id].append(downloaded_path)
            all_downloaded.append(downloaded_path)
        except Exception as exc:
            errors_by_user[user_id].append(
                f"DocumentId={_normalize_text(document.get('DocumentId')) or 'UNKNOWN'}: {exc}"
            )
            logger.error(
                "Document download failed | "
                f"RequestId={_normalize_text(document.get('RequestId'))} | "
                f"UserId={user_id} | Error={exc}"
            )

    return dict(downloaded_by_user), dict(errors_by_user), all_downloaded


def _build_bulk_supporting_zip(
    downloaded_files: List[Path],
    destination_root: Path,
    zip_output_path: Path,
    logger: logging.Logger,
) -> Path:
    zip_output_path = Path(zip_output_path)
    if zip_output_path.suffix.lower() != ".zip":
        zip_output_path = zip_output_path.with_suffix(".zip")
    zip_output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in downloaded_files:
            file_path = Path(file_path)
            arcname = file_path.relative_to(destination_root).as_posix()
            zip_file.write(file_path, arcname=arcname)

    logger.info(f"Bulk supporting zip created: {zip_output_path}")
    return zip_output_path


def _resolve_process_folder(upload_paths: Dict[str, str]) -> Path:
    if not upload_paths:
        raise ValueError("Upload paths are empty for resolved process")

    preferred_keys = (
        "batch_member_file",
        "batch_delete_member_file",
        "supporting_file_1",
        "delete_supporting_file_1",
        "batch_supporting_document",
        "batch_delete_supporting_document_1",
    )

    for key in preferred_keys:
        value = upload_paths.get(key)
        if value:
            return Path(value).resolve().parent

    first_value = next(iter(upload_paths.values()))
    return Path(first_value).resolve().parent


def _build_batch_census_for_request(
    request_id: str,
    request_type: str,
    request_user_ids: List[str],
    upload_paths: Dict[str, str],
    logger: logging.Logger,
) -> None:
    output_key = "batch_member_file" if request_type == "ADD" else "batch_delete_member_file"
    output_path = upload_paths.get(output_key)
    if not output_path:
        raise ValueError(f"Batch census output path missing for key: {output_key}")

    if request_type == "ADD":
        result = build_addition_census_file(
            request_id=request_id,
            output_path=output_path,
            portal_name="SUKOON",
            include_user_ids=request_user_ids,
            logger=logger,
        )
    else:
        result = build_deletion_census_file(
            request_id=request_id,
            output_path=output_path,
            portal_name="SUKOON",
            include_user_ids=request_user_ids,
            logger=logger,
        )
    logger.info(
        "Batch census generated for request | "
        f"RequestId={result.request_id} | Members={result.members_count} | "
        f"EligibleUsers={len(request_user_ids)} | Output={result.output_path}"
    )


def _prepare_request_without_portal(
    connection,
    blob_service: AzureBlobDownloadService,
    request_id: str,
    request_user_ids: List[str],
    logger: logging.Logger,
) -> Tuple[bool, str]:
    selector = load_process_selector_by_request_id(request_id=request_id, logger=logger)
    portal_name = selector["PortalName"]
    request_type = selector["RequestType"]
    action_type = selector["ActionType"]

    if portal_name != "SUKOON":
        raise ValueError(f"Unsupported PortalName for pre-portal mode: {portal_name}")

    if action_type in {"MANUAL", "INDIVIDUAL"}:
        normalized_action = "INDIVIDUAL"
    elif action_type == "BULK":
        normalized_action = "BULK"
    else:
        normalized_action = "BATCH"
    upload_paths = get_upload_paths(portal_name, request_type, normalized_action)
    if not upload_paths:
        raise ValueError(
            f"No upload path mapping found for {portal_name} {request_type} {normalized_action}"
        )

    process_folder = _resolve_process_folder(upload_paths)
    _clear_folder_contents(process_folder, logger=logger)

    _update_portal_status_for_users(
        connection=connection,
        request_id=request_id,
        user_ids=request_user_ids,
        status="INPROGRESS",
        failure_reason=None,
    )
    logger.info(f"PortalStatus updated to INPROGRESS | RequestId={request_id} | Users={len(request_user_ids)}")

    if normalized_action == "BATCH":
        _build_batch_census_for_request(
            request_id=request_id,
            request_type=request_type,
            request_user_ids=request_user_ids,
            upload_paths=upload_paths,
            logger=logger,
        )
    elif normalized_action == "BULK":
        logger.info(
            "Bulk pre-portal mode selected: census generation skipped; preparing supporting zip only"
        )

    request_documents = _fetch_request_documents_for_users(
        connection=connection,
        request_id=request_id,
        user_ids=request_user_ids,
    )
    logger.info(
        f"Documents fetched for eligible users | RequestId={request_id} | "
        f"EligibleUsers={len(request_user_ids)} | Count={len(request_documents)}"
    )

    downloaded_by_user, errors_by_user, all_downloaded = _download_documents_user_wise(
        blob_service=blob_service,
        request_documents=request_documents,
        destination_root=process_folder,
        logger=logger,
    )

    if normalized_action in {"BATCH", "BULK"}:
        if not all_downloaded:
            raise RuntimeError("No documents downloaded for bulk request")

        if request_type == "ADD":
            zip_target = upload_paths.get("batch_supporting_document")
        else:
            zip_target = upload_paths.get("batch_delete_supporting_document_1")

        if not zip_target:
            raise ValueError("Bulk supporting upload path is missing")

        _build_bulk_supporting_zip(
            downloaded_files=all_downloaded,
            destination_root=process_folder,
            zip_output_path=Path(zip_target),
            logger=logger,
        )

        if errors_by_user:
            combined_errors = []
            for user_id, messages in errors_by_user.items():
                combined_errors.extend([f"User {user_id}: {message}" for message in messages])
            reason = " | ".join(combined_errors)[:1000]
            _update_portal_status_for_users(
                connection=connection,
                request_id=request_id,
                user_ids=request_user_ids,
                status="FAILED",
                failure_reason=reason,
            )
            return False, f"Bulk document download had errors: {reason}"

        _update_portal_status_for_users(
            connection=connection,
            request_id=request_id,
            user_ids=request_user_ids,
            status="COMPLETED",
            failure_reason=None,
        )
        return True, f"Bulk preparation completed. FilesDownloaded={len(all_downloaded)}"

    completed_users: List[str] = []
    failed_users: Dict[str, str] = {}

    for user_id in request_user_ids:
        user_errors = errors_by_user.get(user_id, [])
        user_downloads = downloaded_by_user.get(user_id, [])

        if user_errors:
            failed_users[user_id] = " | ".join(user_errors)[:1000]
            continue

        if not user_downloads:
            failed_users[user_id] = "No documents downloaded for user"
            continue

        completed_users.append(user_id)

    if completed_users:
        _update_portal_status_for_users(
            connection=connection,
            request_id=request_id,
            user_ids=completed_users,
            status="COMPLETED",
            failure_reason=None,
        )

    for failed_user, reason in failed_users.items():
        _update_portal_status_for_users(
            connection=connection,
            request_id=request_id,
            user_ids=[failed_user],
            status="FAILED",
            failure_reason=reason,
        )

    if failed_users:
        return False, (
            f"Individual preparation completed with failures. "
            f"Completed={len(completed_users)} Failed={len(failed_users)}"
        )

    return True, f"Individual preparation completed. Completed={len(completed_users)}"


def prepare_sukoon_requests_without_portal(
    target_request_id: str | None = None,
    logger: logging.Logger | None = None,
) -> RequestPreparationSummary:
    run_id = _make_run_id()
    target_request_id = _normalize_text(target_request_id) or None
    logger = logger or _init_logger(run_id=run_id, request_id=target_request_id)

    logger.info(
        "Starting SUKOON pre-portal preparation loop | "
        f"TargetRequestId={target_request_id or 'ALL_PENDING'}"
    )

    completed = 0
    failed = 0
    skipped = 0

    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        pending_requests = _fetch_pending_requests(connection, target_request_id=target_request_id)
        logger.info(f"Pending requests selected: {len(pending_requests)}")

        if not pending_requests:
            return RequestPreparationSummary(
                total_requests=0,
                completed_requests=0,
                failed_requests=0,
                skipped_requests=0,
            )

        for request_id, user_ids in pending_requests.items():
            request_logger = _init_logger(
                run_id=run_id,
                request_id=request_id,
                logger_name=f"sukoon_preportal.{request_id}",
            )
            request_logger.info(
                "Request logger initialized | "
                f"RequestId={request_id} | RunId={run_id}"
            )
            request_logger.info(
                f"Processing request in pre-portal mode | RequestId={request_id} | Users={len(user_ids)}"
            )

            try:
                blob_service = AzureBlobDownloadService(logger=request_logger)
                is_success, message = _prepare_request_without_portal(
                    connection=connection,
                    blob_service=blob_service,
                    request_id=request_id,
                    request_user_ids=user_ids,
                    logger=request_logger,
                )

                if is_success:
                    completed += 1
                    request_logger.info(f"Request prepared successfully | RequestId={request_id} | {message}")
                else:
                    failed += 1
                    request_logger.error(f"Request prepared with failures | RequestId={request_id} | {message}")
            except ValueError as exc:
                skipped += 1
                reason = str(exc)
                request_logger.warning(f"Request skipped | RequestId={request_id} | Reason={reason}")
                _update_portal_status_for_users(
                    connection=connection,
                    request_id=request_id,
                    user_ids=user_ids,
                    status="FAILED",
                    failure_reason=reason[:1000],
                )
            except Exception as exc:
                failed += 1
                reason = f"Pre-portal preparation failed: {exc}"
                request_logger.error(f"Request failed | RequestId={request_id} | Error={exc}")
                _update_portal_status_for_users(
                    connection=connection,
                    request_id=request_id,
                    user_ids=user_ids,
                    status="FAILED",
                    failure_reason=reason[:1000],
                )

    summary = RequestPreparationSummary(
        total_requests=len(pending_requests),
        completed_requests=completed,
        failed_requests=failed,
        skipped_requests=skipped,
    )
    logger.info(
        "Pre-portal preparation summary | "
        f"Total={summary.total_requests} | "
        f"Completed={summary.completed_requests} | "
        f"Failed={summary.failed_requests} | "
        f"Skipped={summary.skipped_requests}"
    )
    return summary
