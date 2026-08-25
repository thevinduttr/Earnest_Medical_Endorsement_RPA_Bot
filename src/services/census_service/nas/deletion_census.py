from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from src.services.census_service.nas.common import (
    fill_nas_census_template,
    format_day_first_date,
    normalize_scalar,
)
from src.services.census_service.sukoon.common import CensusBuildResult


DEFAULT_NAS_DELETE_TEMPLATE = Path("data/templates/NAS/DELETE.xlsx")


def value_from_nas_deletion_row(
    row: Dict[str, Any],
    header: str,
    _row_number: int,
) -> Any:
    if header == "member card no":
        return normalize_scalar(row.get("HealthCardNumber") or row.get("StaffId"))
    if header == "emirates id":
        return normalize_scalar(row.get("EmiratesId"))
    if header == "effective date":
        return format_day_first_date(row.get("DeletionEffectiveDate"))
    if header == "deletion reason":
        return ""
    return ""


def build_nas_deletion_census_file(
    request_id: str,
    output_path: str | Path,
    include_user_ids: Iterable[str] | None = None,
    logger=None,
) -> CensusBuildResult:
    return fill_nas_census_template(
        request_id=request_id,
        request_type="DELETE",
        output_path=output_path,
        template_path=DEFAULT_NAS_DELETE_TEMPLATE,
        include_user_ids=include_user_ids,
        value_mapper=value_from_nas_deletion_row,
        success_log_label="NAS deletion census generated",
        logger=logger,
    )
