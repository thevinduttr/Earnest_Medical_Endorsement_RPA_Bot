from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence

from src.services.db_service.azure_db_connection import AzureSQLConnection


TABLE_NAME = "[dbo].[EndorsementRequestsMemberData]"

PROCESS_FIELD_MAPS: Dict[str, Dict[str, str]] = {
    "add_individual": {
        "company_name": "PolicyNumber",
        "principal_radio": "MemberType",
        "employee_number": "EmpNo",
        "first_name": "FirstName",
        "middle_name": "MiddleName",
        "last_name": "LastName",
        "gender": "Gender",
        "marital_status": "MaritalStatus",
        "relationship": "Relation",
        "date_of_birth": "DateOfBirth",
        "salary_band": "SalaryBand",
        "nationality": "Nationality",
        "passport_number": "PassportNo",
        "eid_number": "EmiratesId",
        "unique_id_visa": "UnifiedNo",
        "visa_file_number": "VisaFileNumber",
        "category": "Category",
        "commission_based": "Commission",
        "department": "Department",
        "start_date": "EffectiveDate",
        "emirate_residence": "VisaIssuanceEmirate",
        "birth_certificate": "BirthCertificateNumber",
        "residential_location": "ResidenceEmirate",
        "work_location": "WorkEmirate",
        "communication_email": "Email",
        "communication_mobile_number": "MobileNo",
        "sponsor_type": "SponsorType",
        "sponsor_uid": "SponsorId",
        "sponsor_contact_number": "SponsorContactNumber",
        "sponsor_email": "SponsorContactEmail",
    },
    "add_batch": {
        "company_name": "PolicyNumber",
    },
    "delete_manual": {
        "company_name": "PolicyNumber",
        "employee_number": "HealthCardNumber",
        "deletion_effective_date": "DeletionEffectiveDate",
    },
    "delete_batch": {
        "company_name": "PolicyNumber",
    },
    "delete_bulk": {
        "company_name": "PolicyNumber",
    },
}

DATE_VALUE_KEYS = {
    "date_of_birth",
    "start_date",
    "deletion_effective_date",
}


@dataclass(frozen=True)
class MemberProcessValues:
    request_id: str
    process_values: Dict[str, str]
    source_row: Dict[str, Any]


def _normalize_upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _resolve_action_variants(action_type: str) -> Sequence[str]:
    action = _normalize_upper(action_type)
    if action in {"INDIVIDUAL", "INDIVIUAL", "MANUAL", "MANNUAL"}:
        return ("INDIVIDUAL", "INDIVIUAL", "MANUAL", "MANNUAL")
    if action == "BATCH":
        return ("BATCH",)
    if action == "BULK":
        return ("BULK",)
    return (action,)


def _format_date_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    text_value = str(value).strip()
    if not text_value:
        return None

    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y")
    except ValueError:
        pass

    for date_format in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            parsed = datetime.strptime(text_value, date_format)
            return parsed.strftime("%d/%m/%Y")
        except ValueError:
            continue

    return text_value


def _normalize_text_value(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, (datetime, date)):
        return _format_date_value(value)

    if isinstance(value, Decimal):
        text_value = format(value, "f").rstrip("0").rstrip(".")
        return text_value if text_value else "0"

    text_value = str(value).strip()
    return text_value or None


def _normalize_commission(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, bool):
        return "Y" if value else "N"

    text_value = str(value).strip().upper()
    if text_value in {"1", "Y", "YES", "TRUE", "T"}:
        return "Y"
    if text_value in {"0", "N", "NO", "FALSE", "F"}:
        return "N"
    return str(value).strip() or None


def _build_fetch_query(action_variants: Sequence[str], has_request_id: bool, has_user_id: bool) -> str:
    placeholders = ", ".join("?" for _ in action_variants)
    where_parts = [
        "UPPER(PortalName) = ?",
        "UPPER(RequestType) = ?",
        f"UPPER(ActionType) IN ({placeholders})",
    ]

    if has_request_id:
        where_parts.append("RequestId = ?")
    if has_user_id:
        where_parts.append("UserId = ?")

    where_sql = "\n      AND ".join(where_parts)
    return f"""
SELECT TOP (1) *
FROM {TABLE_NAME}
WHERE {where_sql}
ORDER BY CreatedAt DESC, RequestId DESC
"""


def _fetch_member_row(
    portal_name: str,
    request_type: str,
    action_type: str,
    request_id: Optional[str],
    user_id: Optional[str],
    logger=None,
) -> Optional[Dict[str, Any]]:
    action_variants = _resolve_action_variants(action_type)
    query = _build_fetch_query(
        action_variants,
        has_request_id=bool(request_id),
        has_user_id=bool(user_id),
    )

    query_params = [
        _normalize_upper(portal_name),
        _normalize_upper(request_type),
        *action_variants,
    ]
    if request_id:
        query_params.append(str(request_id).strip())
    if user_id:
        query_params.append(str(user_id).strip())

    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        cursor = connection.cursor()
        try:
            cursor.execute(query, query_params)
            row = cursor.fetchone()
            if row is None:
                return None

            columns = [column[0] for column in cursor.description]
            return {columns[index]: row[index] for index in range(len(columns))}
        finally:
            cursor.close()


def _map_row_to_process_values(process_key: str, row: Dict[str, Any]) -> Dict[str, str]:
    field_map = PROCESS_FIELD_MAPS.get(process_key)
    if not field_map:
        raise ValueError(f"Unsupported process key for DB mapping: {process_key}")

    values: Dict[str, str] = {}
    for json_key, db_column in field_map.items():
        raw_value = row.get(db_column)

        if json_key in DATE_VALUE_KEYS:
            mapped_value = _format_date_value(raw_value)
        elif json_key == "commission_based":
            mapped_value = _normalize_commission(raw_value)
        else:
            mapped_value = _normalize_text_value(raw_value)

        if mapped_value is not None:
            values[json_key] = mapped_value

    if process_key == "add_individual" and not values.get("employee_number"):
        for column_name in ("EmpNo", "StaffId", "HealthCardNumber"):
            fallback_value = _normalize_text_value(row.get(column_name))
            if fallback_value:
                values["employee_number"] = fallback_value
                break

    # Manual delete form uses the same field for health card input; fallback to StaffId if empty.
    if process_key == "delete_manual" and not values.get("employee_number"):
        fallback_value = _normalize_text_value(row.get("StaffId"))
        if fallback_value:
            values["employee_number"] = fallback_value

    return values


def load_member_process_values(
    portal_name: str,
    request_type: str,
    action_type: str,
    process_key: str,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    logger=None,
) -> MemberProcessValues:
    row = _fetch_member_row(
        portal_name=portal_name,
        request_type=request_type,
        action_type=action_type,
        request_id=request_id,
        user_id=user_id,
        logger=logger,
    )
    if row is None:
        request_filter = f" and RequestId={request_id}" if request_id else ""
        user_filter = f" and UserId={user_id}" if user_id else ""
        raise ValueError(
            "No record found in EndorsementRequestsMemberData for "
            f"PortalName={portal_name}, RequestType={request_type}, ActionType={action_type}{request_filter}{user_filter}"
        )

    process_values = _map_row_to_process_values(process_key=process_key, row=row)
    resolved_request_id = _normalize_text_value(row.get("RequestId")) or str(request_id or "").strip()

    return MemberProcessValues(
        request_id=resolved_request_id,
        process_values=process_values,
        source_row=row,
    )


def _normalize_action_for_selector(action_type: Any) -> str:
    action = _normalize_upper(action_type)
    if action in {"INDIVIDUAL", "INDIVIUAL", "MANUAL", "MANNUAL"}:
        return "INDIVIDUAL"
    if action in {"BATCH", "BULK"}:
        return action
    return action


def load_process_selector_by_request_id(request_id: str, user_id: Optional[str] = None, logger=None) -> Dict[str, str]:
    request_id_text = str(request_id or "").strip()
    if not request_id_text:
        raise ValueError("request_id is required to load process selector from DB")
    user_id_text = str(user_id or "").strip() if user_id is not None else ""

    where_sql = "RequestId = ?"
    query_params: list[Any] = [request_id_text]
    if user_id_text:
        where_sql += " AND UserId = ?"
        query_params.append(user_id_text)

    query = f"""
SELECT TOP (1) PortalName, RequestType, ActionType, RequestId
FROM {TABLE_NAME}
WHERE {where_sql}
ORDER BY CreatedAt DESC, Id DESC
"""

    with AzureSQLConnection(logger=logger) as db_connection:
        connection = db_connection.connect()
        cursor = connection.cursor()
        try:
            cursor.execute(query, query_params)
            row = cursor.fetchone()
            if row is None:
                raise ValueError(
                    f"No process selector row found in EndorsementRequestsMemberData for RequestId={request_id_text}"
                )

            columns = [column[0] for column in cursor.description]
            row_data = {columns[index]: row[index] for index in range(len(columns))}
        finally:
            cursor.close()

    selector = {
        "PortalName": _normalize_upper(row_data.get("PortalName")),
        "RequestType": _normalize_upper(row_data.get("RequestType")),
        "ActionType": _normalize_action_for_selector(row_data.get("ActionType")),
    }

    if logger:
        logger.info(
            "Selector loaded from DB | "
            f"RequestId={request_id_text} | PortalName={selector['PortalName']} | "
            f"RequestType={selector['RequestType']} | ActionType={selector['ActionType']}"
        )

    return selector
