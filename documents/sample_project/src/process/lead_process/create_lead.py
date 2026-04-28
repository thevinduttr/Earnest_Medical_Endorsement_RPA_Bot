from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step , get_autofilled_input_value , upload_files_via_drop
from src.utils.load_data import load_yaml_file

from src.process.select_client import select_client_process

async def create_lead_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,   # <-- NEW parameter
) -> None:
    """
    Create Lead flow — explicit action list executed in order:
      19. select lead in sidebar
      20. navigate to create lead
      21. fill lead details
      22. click save button
      23. then load requirement details and fill that fields
      24. upload documents if needed
      25. close New Lead tab
    """
    logger.info("Create Lead process started")
    selectors = selectors_group or {}

    # --- Pre-upload actions (open tab) ---
    pre_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "Open New Lead Tab"},
    ]

    client_details_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "save_button", "label": "Save Lead"},
    ]

    requirements_actions: List[Dict[str, Any]] = [
        {"type": "select", "key": "requirement_business_type", "label": " Business Type", "value_col": "BusinessType"},
        {"type": "select", "key": "requirement_class", "label": "Class", "value_col": "Class"},
        {"type": "select", "key": "requirement_policy_type", "label": "Policy Type", "value_col": "PolicyTypeCRM"},
        {"type": "select", "key": "requirement_insurer", "label": "Insurer", "value_col": "InsuranceCompany"},
        {"type": "fill", "key": "requirement_lead_generation_date", "label": "Lead Generation Date", "value_col": ""},
        {"type": "fill", "key": "requirement_due_date", "label": "Due Date", "value_col": ""},
        {"type": "select", "key": "requirement_classification", "label": "Classification", "value_col": "Classification"},
        {"type": "select", "key": "requirement_source", "label": "Source", "value_col": "Source"},
        {"type": "select", "key": "requirement_pos", "label": "POS", "value_col": "POS"},
        {"type": "select", "key": "requirement_sales_user", "label": "Sales User", "value_col": "SalesUser"},
        {"type": "select", "key": "requirement_assign_to_group", "label": "Assign to Group", "value_col": "AssignToGroup"},
        {"type": "select", "key": "requirement_assign_to_user", "label": "Assign to User", "value_col": "AssignToUser"},
        {"type": "fill", "key": "requirement_remarks", "label": "Remarks", "value_col": "Remarks"},
    ]
    
    save_action: List[Dict[str, Any]] = [
        {"type": "click", "key": "save_button", "label": "Save New Lead", "validation_check": True},
    ]

    post_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "New Lead Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"},
    ]
    
    await select_client_process(page=page, df=df, logger=logger)

    # helper to only run actions whose keys exist in YAML
    def _filter(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [a for a in actions if a.get("key") and a.get("key") in selectors]

    # Execute sections
    for section_name, actions in [
        ("pre-upload",      _filter(pre_upload_actions)),
        ("client-details",  _filter(client_details_actions)),
        ("requirements-details", _filter(requirements_actions)),
        ("save", _filter(save_action)),
    ]:
        if actions:
            try:
                await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
            except Exception as e:
                logger.error(f"Error during create-lead {section_name} actions: {e}")

    # After completing general-details actions, attempt to scrape the auto-filled Prospect RefNo (if selector exists)
    try:
        if "requirement_lead_ref_no" in selectors:
            try:
                lead_ref = await get_autofilled_input_value(
                    page,
                    logger=logger,
                    selector_key="requirement_lead_ref_no",
                    selectors=selectors,
                    label="Prospect RefNo",
                    timeout_ms=10000,
                )
                logger.info(f"Scraped Lead RefNo: {lead_ref}")
                # Optionally write back to DF if desired:
                df.at[0, "lead_refr_no"] = lead_ref
            except Exception as e:
                logger.debug(f"Could not scrape Lead RefNo (continuing): {e}")
    except Exception:
        # defensive: don't let a failure here break the main flow
        logger.debug("Skipping Lead RefNo scrape due to selectors or other error")

    await asyncio.sleep(1)
    
    # --- Upload documents (optional) ---
    try:
        # Sample documents list (edit to match your files). Use file_name WITHOUT extension (helper will find passport.*)
        documents = [
            # emirate_id document
            {
                "path": "data/attachments",
                "file_name": "EMIRATES_ID",
                "doc_type": "Other Docs",
                "expiry_date": df["EmiratesIDExpiryDate"].iloc[0]
            },
            
            #Driving License document
            {
                "path": "data/attachments",
                "file_name": "DRIVING_LICENSE",
                "doc_type": "Other Docs",
                "expiry_date": df["LicenseExpiryDate"].iloc[0]
            },
            
            #Vehicle documents
            {
                "path": "data/attachments",
                "file_name": "PCD_HYSA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "MULKIYA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "E_MULKIYA_HYSA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "VCC",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "KAVAK_QUOTATION",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "ALBA_QUOTATION",
                "doc_type": "Other Docs",
                "expiry_date": ""
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
            logger.error(f"Error during create-lead post-upload actions: {e}")

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

    logger.info("Create Lead process completed")
