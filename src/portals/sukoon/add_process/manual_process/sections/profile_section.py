from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def fill_profile_section(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
):
    logger.info("Profile section started")

    actions: List[Dict[str, Any]] = [
        {
            "type": "check",
            "key": "principal_radio",
            "label": "Select Principal",
            "wait_for_load": False,
        },
        {
            "type": "fill",
            "key": "employee_number",
            "label": "Enter Employee Number",
            "value_key": "employee_number",
            "post_wait_ms": 150,
        },
        {
            "type": "click",
            "key": "go_button",
            "label": "Click GO",
            "wait_for_load": True,
            "post_wait_ms": 350,
        },
        {"type": "fill", "key": "first_name", "label": "First Name", "value_key": "first_name"},
        {
            "type": "fill",
            "key": "middle_name",
            "label": "Middle Name",
            "value_key": "middle_name",
            "required": False,
        },
        {"type": "fill", "key": "last_name", "label": "Last Name", "value_key": "last_name"},
        {"type": "select", "key": "gender", "label": "Gender", "value_key": "gender"},
        {
            "type": "select",
            "key": "marital_status",
            "label": "Marital Status",
            "value_key": "marital_status",
        },
        {
            "type": "select",
            "key": "relationship",
            "label": "Relationship",
            "value_key": "relationship",
        },
        {
            "type": "fill_date",
            "key": "date_of_birth",
            "label": "Date Of Birth",
            "value_key": "date_of_birth",
        },
        {
            "type": "select",
            "key": "salary_band",
            "label": "Salary Band",
            "value_key": "salary_band",
        },
        {
            "type": "select",
            "key": "nationality",
            "label": "Nationality",
            "value_key": "nationality",
        },
        {
            "type": "fill",
            "key": "passport_number",
            "label": "Passport Number",
            "value_key": "passport_number",
        },
        {
            "type": "fill",
            "key": "eid_number",
            "label": "EID Number",
            "value_key": "eid_number",
        },
        {
            "type": "fill",
            "key": "unique_id_visa",
            "label": "Unique ID (Visa)",
            "value_key": "unique_id_visa",
        },
        {
            "type": "fill",
            "key": "visa_file_number",
            "label": "Visa File Number",
            "value_key": "visa_file_number",
        },
        {
            "type": "select",
            "key": "category",
            "label": "Category",
            "value_key": "category",
        },
        {
            "type": "select",
            "key": "commission_based",
            "label": "Commission Based",
            "value_key": "commission_based",
        },
        {
            "type": "fill",
            "key": "department",
            "label": "Department",
            "value_key": "department",
        },
        {
            "type": "fill_date",
            "key": "start_date",
            "label": "Start Date",
            "value_key": "start_date",
        },
        {
            "type": "select",
            "key": "emirate_residence",
            "label": "Emirate Residence",
            "value_key": "emirate_residence",
        },
        {
            "type": "fill",
            "key": "birth_certificate",
            "label": "Birth Certificate Number",
            "value_key": "birth_certificate",
        },
        {
            "type": "click",
            "key": "step1_next_button",
            "label": "Profile Next",
            "wait_for_load": True,
            "wait_for_loader": True,
            "next_key": "communication_residential_location",
            "next_label": "Communication Section Ready",
            "next_timeout_ms": 30000,
            "timeout_ms": 30000,
            "post_wait_ms": 400,
        },
    ]

    await run_actions(
        page,
        actions=actions,
        selectors=selectors,
        values=values,
        logger=logger,
        enforce_session_active=True,
    )

    logger.info("Profile section completed")
