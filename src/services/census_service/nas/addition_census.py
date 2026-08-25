from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from src.services.census_service.nas.common import (
    fill_nas_census_template,
    format_iso_date,
    normalize_commission,
    normalize_contract_name,
    normalize_scalar,
)
from src.services.census_service.sukoon.common import CensusBuildResult


DEFAULT_NAS_ADD_TEMPLATE = Path("data/templates/NAS/ADD.xlsx")

_FIELD_MAP = {
    "first name": "FirstName",
    "middle name": "MiddleName",
    "last name": "LastName",
    "arabic first name": "ArabicFirstName",
    "arabic middle name": "ArabicMiddleName",
    "arabic last name": "ArabicLastName",
    "gender": "Gender",
    "marital status": "MaritalStatus",
    "category": "Category",
    "relation": "Relation",
    "department": "Department",
    "grade": "Grade",
    "principal card no.": "PrincipalCardNo",
    "family no.": "FamilyNo",
    "staff id": "StaffId",
    "nationality": "Nationality",
    "sub-nationality": "SubNationality",
    "emirates id": "EmiratesId",
    "unified no": "UnifiedNo",
    "passport no": "PassportNo",
    "work country": "WorkCountry",
    "work emirate": "WorkEmirate",
    "work region": "WorkRegion",
    "residence country": "ResidenceCountry",
    "residence emirate": "ResidenceEmirate",
    "residence region": "ResidenceRegion",
    "email": "Email",
    "mobile no": "MobileNo",
    "salary band": "SalaryBand",
    "visa issuance emirate": "VisaIssuanceEmirate",
    "birth certificate number": "BirthCertificateNumber",
    "visa file number": "VisaFileNumber",
    "member photo": "MemberPhoto",
    "member type": "MemberType",
    "occupation": "Occupation",
    "regulator no": "RegulatorNo",
}

_BLANK_OPTIONAL_HEADERS = {
    "visa expiry date",
    "coc available",
    "pec declaration",
    "medical declaration file",
    "visa type",
    "company phone",
    "company mail",
    "waived pec declaration",
}


def value_from_nas_addition_row(
    row: Dict[str, Any],
    header: str,
    _row_number: int,
) -> Any:
    if header == "contract name":
        return normalize_contract_name(row.get("ContractName"))
    if header == "effective date":
        return format_iso_date(row.get("EffectiveDate"))
    if header == "dob":
        return format_iso_date(row.get("DateOfBirth"))
    if header == "commission":
        return normalize_commission(row.get("Commission"))
    if header == "passport expiry date":
        return format_iso_date(row.get("PassportExpiryDate"))
    if header in _BLANK_OPTIONAL_HEADERS:
        return ""

    field_name = _FIELD_MAP.get(header)
    return normalize_scalar(row.get(field_name)) if field_name else ""


def build_nas_addition_census_file(
    request_id: str,
    output_path: str | Path,
    include_user_ids: Iterable[str] | None = None,
    logger=None,
) -> CensusBuildResult:
    return fill_nas_census_template(
        request_id=request_id,
        request_type="ADD",
        output_path=output_path,
        template_path=DEFAULT_NAS_ADD_TEMPLATE,
        include_user_ids=include_user_ids,
        value_mapper=value_from_nas_addition_row,
        success_log_label="NAS addition census generated",
        logger=logger,
    )
