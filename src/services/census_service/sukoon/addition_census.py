from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from src.services.census_service.sukoon.common import (
    CensusBuildResult,
    fill_census_template,
    normalize_scalar,
    to_excel_date,
)


DEFAULT_ADD_TEMPLATE = Path("data/templates/SUKOON/ADD.xlsx")


def _value_from_addition_row(row: Dict[str, Any], header: str, row_number: int) -> Any:
    if header == "sl no.":
        return row_number
    if header == "first name":
        return normalize_scalar(row.get("FirstName"))
    if header == "middle name":
        return normalize_scalar(row.get("MiddleName"))
    if header == "last name":
        return normalize_scalar(row.get("LastName"))
    if header == "employee number":
        return normalize_scalar(row.get("StaffId"))
    if header == "date of birth":
        return to_excel_date(row.get("DateOfBirth"))
    if header == "gender":
        return normalize_scalar(row.get("Gender"))
    if header == "marital status":
        return normalize_scalar(row.get("MaritalStatus"))
    if header == "relation":
        return normalize_scalar(row.get("Relation"))
    if header == "category":
        return normalize_scalar(row.get("Category"))
    if header == "region":
        return normalize_scalar(row.get("WorkRegion"))
    if header == "lsb":
        return normalize_scalar(row.get("SalaryBand"))
    if header == "nationality":
        return normalize_scalar(row.get("Nationality"))
    if header == "passport number":
        return normalize_scalar(row.get("PassportNo"))
    if header == "eid number":
        return normalize_scalar(row.get("EmiratesId"))
    if header == "uid number":
        return normalize_scalar(row.get("UnifiedNo"))
    if header == "visa issued location":
        return normalize_scalar(row.get("VisaIssuanceEmirate"))
    if header == "actual salary band":
        return normalize_scalar(row.get("SalaryBand"))
    if header == "person commission":
        return normalize_scalar(row.get("Commission"))
    if header == "residential location":
        return normalize_scalar(row.get("ResidenceEmirate"))
    if header == "work location":
        return normalize_scalar(row.get("WorkEmirate"))
    if header == "mobile number":
        return normalize_scalar(row.get("MobileNo"))
    if header == "email":
        return normalize_scalar(row.get("Email"))
    if header == "photo file name":
        return normalize_scalar(row.get("MemberPhoto"))
    if header == "sponsor type":
        return normalize_scalar(row.get("SponsorType"))
    if header == "sponsor id":
        return normalize_scalar(row.get("SponsorId"))
    if header == "sponsor contact number":
        return normalize_scalar(row.get("SponsorContactNumber"))
    if header == "sponsor contact email":
        return normalize_scalar(row.get("SponsorContactEmail"))
    if header == "occupation":
        return normalize_scalar(row.get("Occupation"))
    if header in {"addition effective date", "effective date"}:
        return to_excel_date(row.get("EffectiveDate"))
    if header == "visa file number":
        return normalize_scalar(row.get("VisaFileNumber"))
    if header == "birth certificate number":
        return normalize_scalar(row.get("BirthCertificateNumber"))
    if header == "policy number":
        return normalize_scalar(row.get("PolicyNumber"))
    return ""


def build_addition_census_file(
    request_id: str,
    output_path: str | Path,
    portal_name: str = "SUKOON",
    include_user_ids: Iterable[str] | None = None,
    logger=None,
) -> CensusBuildResult:
    # Step 01: Build ADD census using the ADD template and mapped member fields.
    return fill_census_template(
        request_id=request_id,
        request_type="ADD",
        output_path=output_path,
        template_path=DEFAULT_ADD_TEMPLATE,
        portal_name=portal_name,
        include_user_ids=include_user_ids,
        value_mapper=_value_from_addition_row,
        date_headers={"date of birth", "addition effective date", "effective date"},
        success_log_label="Addition census generated",
        logger=logger,
    )
