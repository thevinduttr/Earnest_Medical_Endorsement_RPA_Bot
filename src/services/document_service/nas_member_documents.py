from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
from typing import Any, Iterable

from src.services.census_service.sukoon.common import load_request_members_dataframe
from src.services.db_service.nas.preportal_processor import (
    download_request_documents_for_users,
)


@dataclass(frozen=True)
class NasMemberDocumentPreparation:
    ordered_user_ids: list[str]
    ordered_member_names: list[str]
    downloaded_by_user: dict[str, list[Path]]
    documents_by_user: dict[str, list[dict[str, str]]]
    manifest_path: Path


_DOCUMENT_FIELD_PATTERNS = (
    ("visa_copy", ("VISA",)),
    ("passport_copy", ("PASSPORT",)),
    ("national_id_copy", ("EMIRATES", "EMIRATES ID", "EID", "NATIONAL ID")),
    (
        "continuity_certificate",
        ("COC", "CONTINUITY", "CERTIFICATE OF CONTINUITY"),
    ),
    ("member_certificate", ("MEMBER CERTIFICATE", "EMPLOYEE CERTIFICATE")),
    (
        "declaration_attachment",
        ("PEC", "DECLARATION", "MEDICAL"),
    ),
)


def map_document_type_to_nas_field(document_type: str) -> str:
    normalized = " ".join(
        re.sub(r"[^A-Z0-9]+", " ", str(document_type or "").upper()).split()
    )
    for field_name, tokens in _DOCUMENT_FIELD_PATTERNS:
        if any(token in normalized for token in tokens):
            return field_name
    return "supporting_document"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _member_name(row: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in (
            _text(row.get("FirstName")),
            _text(row.get("MiddleName")),
            _text(row.get("LastName")),
        )
        if part
    )


def prepare_nas_member_documents(
    *,
    request_id: str,
    user_ids: Iterable[str],
    destination_root: Path,
    logger: logging.Logger,
) -> NasMemberDocumentPreparation:
    normalized_user_ids = [
        str(user_id).strip()
        for user_id in user_ids
        if str(user_id).strip()
    ]
    members_frame = load_request_members_dataframe(
        request_id=request_id,
        portal_name="NAS",
        request_type="ADD",
        include_user_ids=normalized_user_ids or None,
        logger=logger,
    )
    member_rows = members_frame.to_dict(orient="records")
    ordered_user_ids = [
        _text(row.get("UserId"))
        for row in member_rows
        if _text(row.get("UserId"))
    ]

    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    downloaded_by_user, errors_by_user, _ = download_request_documents_for_users(
        request_id=request_id,
        user_ids=ordered_user_ids,
        destination_root=destination_root,
        logger=logger,
    )
    if errors_by_user:
        details = " | ".join(
            f"User {user_id}: {'; '.join(messages)}"
            for user_id, messages in errors_by_user.items()
        )
        raise RuntimeError(f"NAS member document download failed: {details}")
    missing_users = [
        user_id
        for user_id in ordered_user_ids
        if not downloaded_by_user.get(user_id)
    ]
    if missing_users:
        logger.warning(
            "No NAS member documents found for UserIds: %s",
            ", ".join(missing_users),
        )

    manifest_members = []
    documents_by_user: dict[str, list[dict[str, str]]] = {}
    rows_by_user = {
        _text(row.get("UserId")): row
        for row in member_rows
        if _text(row.get("UserId"))
    }
    for member_index, user_id in enumerate(ordered_user_ids, start=1):
        row = rows_by_user[user_id]
        documents = []
        for file_path in downloaded_by_user.get(user_id, []):
            document_type = re.sub(r"_\d+$", "", Path(file_path).stem)
            documents.append(
                {
                    "document_type": document_type,
                    "nas_field": map_document_type_to_nas_field(document_type),
                    "path": str(Path(file_path).resolve()),
                }
            )
        documents_by_user[user_id] = documents
        manifest_members.append(
            {
                "member_index": member_index,
                "user_id": user_id,
                "member_name": _member_name(row),
                "emirates_id": _text(row.get("EmiratesId")),
                "passport_number": _text(row.get("PassportNo")),
                "staff_id": _text(row.get("StaffId")),
                "documents": documents,
            }
        )

    manifest_path = destination_root / "nas_member_documents_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "request_id": str(request_id).strip(),
                "members": manifest_members,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(
        "NAS member documents organized | RequestId=%s | Members=%s | Manifest=%s",
        request_id,
        len(manifest_members),
        manifest_path,
    )
    return NasMemberDocumentPreparation(
        ordered_user_ids=ordered_user_ids,
        ordered_member_names=[
            _member_name(rows_by_user[user_id])
            for user_id in ordered_user_ids
        ],
        downloaded_by_user=downloaded_by_user,
        documents_by_user=documents_by_user,
        manifest_path=manifest_path,
    )
