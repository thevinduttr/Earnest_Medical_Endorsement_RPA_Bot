from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page
import base64

from src.utils.support_functions import run_actions, wait_for_next_step, upload_files_via_drop
from src.utils.load_data import load_yaml_file

async def create_client_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,   # <-- NEW parameter
) -> None:
    """
    Create Client flow — explicit action list executed in order:
      11. open New Client tab (if selector)
      12. fill client details
      13. fill AML verification fields
      14. fill contact details
      15. fill other details
      16. upload document(s) if provided in df
      17. click Save
      18. close New client tab
    """
    logger.info("Create Client process started")
    selectors = selectors_group or {}

    # --- Pre-upload actions (open tab) ---
    pre_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "Open New Client Tab"},
    ]

    client_details_actions: List[Dict[str, Any]] = [
        {"type": "select", "key": "client_type", "label": "Client Type", "value_col": "ClientType"},
        {"type": "select", "key": "title", "label": "Title", "value_col": "Title"},
        {"type": "fill",   "key": "first_name", "label": "First Name", "value_col": "FirstName"},
        {"type": "fill",   "key": "last_name",  "label": "Last Name",  "value_col": "LastName"},
        {"type": "select", "key": "gender", "label": "Gender", "value_col": "Gender"},
        {"type": "fill",   "key": "dob",    "label": "Date Of Birth", "value_col": "DateOfBirth"},
        {"type": "fill",   "key": "emirates_id", "label": "Emirates Id", "value_col": "EmiratesID", "required": False},
        # {"type": "fill",   "key": "emirates_id_expiry", "label": "Emirates Id Expiry", "value_col": "EmiratesIDExpiryDate", "required": False},
        {"type": "fill",   "key": "other_id", "label": "Other Id", "value_col": ""},
        {"type": "fill",   "key": "credit_limit", "label": "Credit Limit", "value_col": "CreditLimit"},
        {"type": "fill",   "key": "credit_days", "label": "Credit Days", "value_col": "CreditDays"},
        {"type": "select", "key": "payment_options", "label": "Payment Type", "value_col": "PaymentOption"},
        {"type": "select", "key": "marital_status", "label": "Marital Status", "value_col": "MaritalStatus"},
        {"type": "fill",   "key": "date_of_anniversary", "label": "Date Of Anniversary", "value_col": ""},
        {"type": "select", "key": "occupation", "label": "Occupation", "value_col": "Occupation"},
        {"type": "select", "key": "annual_income", "label": "Annual Income", "value_col": "AnnualIncome"},
        {"type": "fill",   "key": "designation", "label": "Designation", "value_col": "Designation"},
        {"type": "fill",   "key": "passport_no", "label": "Passport No",  "value_col": "PassportNo"},
        {"type": "fill",   "key": "vat_reg_no", "label": "VAT No",  "value_col": "VATRegistrationNumber"},
        {"type": "select", "key": "suspended",  "label": "Suspend Client",  "value_col": "Suspended"},
        {"type": "fill",   "key": "suspended_comments", "label": "Suspended Comment", "value_col": ""},
        {"type": "fill",   "key": "tcf_no", "label": "TCF No", "value_col": "TCFNo"},    
        {"type": "select",   "key": "tcf_emirate", "label": "TCF Emirate", "value_col": ""},        
    ]

    aml_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "aml_verified", "label": "AML Verified"},
        {"type": "select", "key": "aml_status", "label": "AML Status", "value_col": "AMLStatus"},
        {"type": "fill",   "key": "aml_review_date", "label": "AML Review Date", "value_col": ""},
        {"type": "fill",   "key": "aml_remarks", "label": "AML Remarks", "value_col": ""},
    ]

    license_details_actions: List[Dict[str, Any]] = [
        {"type": "fill",   "key": "dl_issue_date", "label": "License Issue Date", "value_col": "LicenseIssueDate"},
        {"type": "fill",   "key": "dl_exp_date", "label": "License Expiry Date", "value_col": "LicenseExpiryDate", "required": False},
        {"type": "fill",   "key": "dl_license_no", "label": "License Number", "value_col": "LicenseNumber"},
        {"type": "select", "key": "dl_issue_place", "label": "License Issue Place", "value_col": "LicenseIssuePlace"},
    ]

    contact_details_actions: List[Dict[str, Any]] = [
        {"type": "fill",   "key": "contact_address", "label": "Address", "value_col": "Address"},
        {"type": "fill",   "key": "contact_pobox", "label": "PO Box", "value_col": "POBox"},
        {"type": "select", "key": "contact_nationality", "label": "Nationality", "value_col": "Nationality"},
        {"type": "select", "key": "contact_emirate", "label": "Emirate", "value_col": "Emirate"},
        {"type": "fill",   "key": "contact_landline_no", "label": "Landline No", "value_col": ""},
        {"type": "fill",   "key": "contact_fax_no", "label": "Fax No", "value_col": ""},
        {"type": "fill",   "key": "contact_mobile_number", "label": "Mobile No", "value_col": ""},
        {"type": "fill",   "key": "contact_other_contact_details", "label": "Other Contact Details", "value_col": ""},
        
        {"type": "fill",   "key": "contact_mobile_number", "label": "Mobile No", "value_col": "Mobile_CRM"},
        {"type": "fill",   "key": "contact_email", "label": "Email", "value_col": "Email_CRM"},
    ]
    
    other_details_actions: List[Dict[str, Any]] = [
        # Contact person may be optional for individuals; mark non-fatal
        {"type": "fill",   "key": "other_contact_person", "label": "Contact Person Name", "value_col": "ContactPersonName", "required": False},
        {"type": "fill",   "key": "other_contact_person_designation", "label": "Contact Person Designation", "value_col": "ContactPersonDesignation"},
        {"type": "select", "key": "other_sales_user", "label": "Sales User", "value_col": "SalesUser"},
        {"type": "select", "key": "other_is_group_client", "label": "Group Client", "value_col": "GroupClient"},
        {"type": "select", "key": "other_pos", "label": "POS", "value_col": "POS"},
        {"type": "fill",   "key": "other_client_code", "label": "Client Code", "value_col": "ClientCode"},
        {"type": "select", "key": "other_source", "label": "Source", "value_col": "Source"},
    ]

    save_action: List[Dict[str, Any]] = [
        {"type": "click",  "key": "save_button", "label": "Save", "validation_check": True, "required": True},
    ]
    
    post_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "Open New Client Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"},
    ]

    # helper to only run actions whose keys exist in YAML
    def _filter(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [a for a in actions if a.get("key") and a.get("key") in selectors]

    # Execute sections
    for section_name, actions in [
        ("pre-upload",      _filter(pre_upload_actions)),
        ("client-details",  _filter(client_details_actions)),
        # ("aml-details",     _filter(aml_actions)),
        ("license-details", _filter(license_details_actions)),
        ("contact-details", _filter(contact_details_actions)),
        ("other-details",   _filter(other_details_actions)),
    ]:
        if actions:
            try:
                await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
            except Exception as e:
                # Log and re-raise so the ValidationError/critical failure stops the client_flow and overall run
                logger.error(f"Error during create-client {section_name} actions: {e}")
                raise

    # --- Upload documents (optional) ---
    try:
        # Sample documents list with different examples of how to specify files
        documents = [
            # emirate_id document
            {
                "path": "data/attachments",
                "file_name": "EMIRATES_ID",
                "doc_type": "Emirates ID",
                "expiry_date": df["EmiratesIDExpiryDate"].iloc[0]
            },
            
            #Driving License document
            {
                "path": "data/attachments",
                "file_name": "DRIVING_LICENSE",
                "doc_type": "UAE DL",
                "expiry_date": df["LicenseExpiryDate"].iloc[0]
            }
        ]

        provided = locals().get("documents") or documents
        if not provided:
            logger.info("No 'documents' variable provided; skipping document upload.")
        else:
            logger.info(f"Uploading {len(provided)} document(s) from provided list.")
            # Get upload selector from YAML instead of hardcoding
            upload_selector = selectors.get("upload_document_field", "div[id^='DragnDrop__'].dropzone")
            await upload_files_via_drop(
                page,
                files=provided,
                drop_selector=upload_selector,
                logger=logger,
                run_id=run_id,
                wait_between=2.5,
            )
    except Exception as e:
        logger.error(f"Document upload failed (continuing): {e}")
        
    # --- Save action ---
    if save_action:
        try:
            await run_actions(page, actions=save_action, selectors=selectors, df=df, logger=logger, run_id=run_id)
        except Exception as e:
            logger.error(f"Error during create-client save action: {e}")
            raise

    # --- Post-upload actions (optional) ---
    if post_upload_actions:
        try:
            await run_actions(page, actions=post_upload_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
        except Exception as e:
            logger.error(f"Error during create-client post-upload actions: {e}")
            raise

    # Optional: wait for a next-step element (e.g., dashboard link) if your flow requires
    dashboard_path = Path("locators/main/dashboard_page.yml")
    dashboard_yml = load_yaml_file(dashboard_path)
    dashboard_cfg = dashboard_yml.get("dashboard", {})
    dashboard_xpath = dashboard_cfg.get("xpath")
    if dashboard_xpath:
        try:
            await wait_for_next_step(page, logger=logger, label="Dashboard page ready", selector=dashboard_xpath, timeout_ms=45000)
        except Exception as e:
            logger.debug(f"Dashboard next-step wait failed (continuing): {e}")

    logger.info("Create Client process completed")
