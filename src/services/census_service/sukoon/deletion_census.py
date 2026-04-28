from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from src.services.census_service.sukoon.common import (
    CensusBuildResult,
    fill_census_template,
    load_success_user_ids,
    normalize_scalar,
    to_excel_date,
)


DEFAULT_DELETE_TEMPLATE = Path("data/templates/SUKOON/DETETE.xlsx")


def _value_from_deletion_row(row: Dict[str, Any], header: str, _row_number: int) -> Any:
    if header in {"health card number", "card number"}:
        return normalize_scalar(row.get("HealthCardNumber") or row.get("StaffId"))
    if header in {"deletion effective date", "effective date"}:
        return to_excel_date(row.get("DeletionEffectiveDate"))
    return ""


def load_request_user_ids(
    request_id: str,
    portal_name: str = "SUKOON",
    request_type: str = "DELETE",
    logger=None,
) -> list[str]:
    _ = portal_name
    _ = request_type
    # Step 01: Use OCR/Email SUCCESS users only for delete census/doc steps.
    return load_success_user_ids(request_id=request_id, logger=logger)


def build_deletion_census_file(
    request_id: str,
    output_path: str | Path,
    portal_name: str = "SUKOON",
    include_user_ids: Iterable[str] | None = None,
    logger=None,
) -> CensusBuildResult:
    if include_user_ids is None:
        include_user_ids = load_request_user_ids(request_id=request_id, logger=logger)

    # Step 02: Build DELETE census using the DETETE template and mapped delete fields.
    return fill_census_template(
        request_id=request_id,
        request_type="DELETE",
        output_path=output_path,
        template_path=DEFAULT_DELETE_TEMPLATE,
        portal_name=portal_name,
        include_user_ids=include_user_ids,
        value_mapper=_value_from_deletion_row,
        date_headers={"deletion effective date", "effective date"},
        success_log_label="Deletion census generated",
        logger=logger,
    )
