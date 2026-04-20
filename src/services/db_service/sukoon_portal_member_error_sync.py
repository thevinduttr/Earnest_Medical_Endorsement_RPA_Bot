from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from src.services.db_service.azure_db_connection import AzureSQLConnection


STATUS_TABLE = "[dbo].[EndorsementRequestStatus]"
MEMBER_TABLE = "[dbo].[EndorsementRequestsMemberData]"


@dataclass(frozen=True)
class MemberErrorSyncSummary:
    mapped_rows: int
    updated_users: int
    unmapped_rows: int


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_name(value: Any) -> str:
    return " ".join(_normalize_text(value).upper().split())


def _normalize_id_like(value: Any) -> str:
    return "".join(_normalize_text(value).upper().split())


def _extract_field(row: Any, key: str) -> str:
    if isinstance(row, dict):
        return _normalize_text(row.get(key))
    return _normalize_text(getattr(row, key, ""))


def _load_request_member_rows(
    connection,
    request_id: str,
    portal_name: str,
    request_type: str,
) -> List[Dict[str, str]]:
    query = f"""
SELECT UserId, FirstName, LastName, EmiratesId, StaffId, HealthCardNumber
FROM {MEMBER_TABLE}
WHERE RequestId = ?
  AND UPPER(PortalName) = ?
  AND UPPER(RequestType) = ?
ORDER BY Id ASC, CreatedAt ASC
"""

    cursor = connection.cursor()
    try:
        cursor.execute(query, [request_id, _normalize_text(portal_name).upper(), _normalize_text(request_type).upper()])
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
    finally:
        cursor.close()

    mapped_rows: List[Dict[str, str]] = []
    for row in rows:
        row_dict = {columns[index]: row[index] for index in range(len(columns))}
        mapped_rows.append(
            {
                "user_id": _normalize_text(row_dict.get("UserId")),
                "first_name": _normalize_name(row_dict.get("FirstName")),
                "last_name": _normalize_name(row_dict.get("LastName")),
                "eid_number": _normalize_id_like(row_dict.get("EmiratesId")),
                "employee_number": _normalize_id_like(
                    row_dict.get("StaffId") or row_dict.get("HealthCardNumber")
                ),
            }
        )

    return [row for row in mapped_rows if row.get("user_id")]


def _build_identity_indexes(member_rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[Tuple[str, ...], Set[str]]]:
    by_name: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    by_name_eid: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)
    by_name_employee: Dict[Tuple[str, str, str], Set[str]] = defaultdict(set)
    by_name_eid_employee: Dict[Tuple[str, str, str, str], Set[str]] = defaultdict(set)

    for row in member_rows:
        user_id = row["user_id"]
        first_name = row["first_name"]
        last_name = row["last_name"]
        eid_number = row["eid_number"]
        employee_number = row["employee_number"]

        if not first_name and not last_name:
            continue

        by_name[(first_name, last_name)].add(user_id)

        if eid_number:
            by_name_eid[(first_name, last_name, eid_number)].add(user_id)

        if employee_number:
            by_name_employee[(first_name, last_name, employee_number)].add(user_id)

        if eid_number and employee_number:
            by_name_eid_employee[(first_name, last_name, eid_number, employee_number)].add(user_id)

    return {
        "by_name": by_name,
        "by_name_eid": by_name_eid,
        "by_name_employee": by_name_employee,
        "by_name_eid_employee": by_name_eid_employee,
    }


def _pick_unique(candidates: Set[str]) -> str | None:
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def _resolve_user_id_from_error_row(
    indexes: Dict[str, Dict[Tuple[str, ...], Set[str]]],
    first_name: str,
    last_name: str,
    eid_number: str,
    employee_number: str,
) -> str | None:
    if not first_name and not last_name:
        return None

    by_name = indexes["by_name"]
    by_name_eid = indexes["by_name_eid"]
    by_name_employee = indexes["by_name_employee"]
    by_name_eid_employee = indexes["by_name_eid_employee"]

    if eid_number and employee_number:
        resolved = _pick_unique(by_name_eid_employee.get((first_name, last_name, eid_number, employee_number), set()))
        if resolved:
            return resolved

    if eid_number:
        resolved = _pick_unique(by_name_eid.get((first_name, last_name, eid_number), set()))
        if resolved:
            return resolved

    if employee_number:
        resolved = _pick_unique(by_name_employee.get((first_name, last_name, employee_number), set()))
        if resolved:
            return resolved

    return _pick_unique(by_name.get((first_name, last_name), set()))


def _merge_member_errors(error_messages: Iterable[str]) -> str:
    deduplicated: List[str] = []
    seen: Set[str] = set()
    for message in error_messages:
        text = _normalize_text(message)
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        deduplicated.append(text)

    merged = " | ".join(deduplicated)
    if not merged:
        return ""

    return f"Invalid Member : {merged}"[:1000]


def _update_failed_portal_status_for_users(
    connection,
    request_id: str,
    reasons_by_user: Dict[str, str],
) -> int:
    if not reasons_by_user:
        return 0

    query = f"""
UPDATE {STATUS_TABLE}
SET PortalStatus = 'FAILED',
    PortalFailureReason = ?,
    UpdatedAt = SYSUTCDATETIME()
WHERE RequestId = ?
  AND UserId = ?
"""

    cursor = connection.cursor()
    try:
        for user_id, reason in reasons_by_user.items():
            cursor.execute(query, [reason, request_id, user_id])
        connection.commit()
    finally:
        cursor.close()

    return len(reasons_by_user)


def sync_batch_validation_errors_to_portal_status(
    *,
    request_id: str,
    invalid_members: Sequence[Any],
    portal_name: str = "SUKOON",
    request_type: str = "ADD",
    logger=None,
) -> MemberErrorSyncSummary:
    request_id = _normalize_text(request_id)
    if not request_id:
        raise ValueError("request_id is required for member error sync")

    if not invalid_members:
        return MemberErrorSyncSummary(mapped_rows=0, updated_users=0, unmapped_rows=0)

    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        member_rows = _load_request_member_rows(
            connection=connection,
            request_id=request_id,
            portal_name=portal_name,
            request_type=request_type,
        )

        indexes = _build_identity_indexes(member_rows)

        error_messages_by_user: Dict[str, List[str]] = defaultdict(list)
        unmapped_rows = 0
        mapped_rows = 0

        for row in invalid_members:
            first_name = _normalize_name(_extract_field(row, "first_name"))
            last_name = _normalize_name(_extract_field(row, "last_name"))
            eid_number = _normalize_id_like(_extract_field(row, "eid_number"))
            employee_number = _normalize_id_like(_extract_field(row, "employee_number"))
            error_message = _normalize_text(_extract_field(row, "error_message"))

            resolved_user_id = _resolve_user_id_from_error_row(
                indexes=indexes,
                first_name=first_name,
                last_name=last_name,
                eid_number=eid_number,
                employee_number=employee_number,
            )

            if not resolved_user_id:
                unmapped_rows += 1
                if logger:
                    logger.warning(
                        "Unable to map invalid member row to UserId | "
                        f"FirstName={first_name or '-'} | LastName={last_name or '-'} | "
                        f"EID={eid_number or '-'} | Employee={employee_number or '-'} | "
                        f"Error={error_message or '-'}"
                    )
                continue

            mapped_rows += 1
            if error_message:
                error_messages_by_user[resolved_user_id].append(error_message)

        reasons_by_user = {
            user_id: _merge_member_errors(messages)
            for user_id, messages in error_messages_by_user.items()
        }

        updated_users = _update_failed_portal_status_for_users(
            connection=connection,
            request_id=request_id,
            reasons_by_user=reasons_by_user,
        )

    if logger:
        logger.info(
            "Batch validation error sync summary | "
            f"RequestId={request_id} | MappedRows={mapped_rows} | "
            f"UpdatedUsers={updated_users} | UnmappedRows={unmapped_rows}"
        )

    return MemberErrorSyncSummary(
        mapped_rows=mapped_rows,
        updated_users=updated_users,
        unmapped_rows=unmapped_rows,
    )