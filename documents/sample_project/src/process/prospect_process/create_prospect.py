from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page

from src.utils.support_functions import run_actions, upload_files_via_drop, wait_for_next_step, get_autofilled_input_value
from src.utils.load_data import load_section_from_yaml, load_yaml_file

from src.process.select_client import select_client_process
from src.process.prospect_process.vehicle_process.vehicle_process_main import vehicle_flow

async def create_prospect_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,   # <-- NEW parameter
) -> None:
    """
    Create Prospect flow — explicit action list executed in order:
      28. click search client button
      29. click advanced search button
      30. enter emirate id 
      31. clcik search button
      32. click advanced search button again to hide that panel
      33. check how many table rows available
      34. if one available select that row 
      35. clicked select button
      36. fill general details
      37. click search vehicle button in vehicle details
    """
    logger.info("Create Prospect process started")
    selectors = selectors_group or {}

    # --- Pre-upload actions (open tab) ---
    pre_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "New Prospect Tab"},
    ]
    
    client_details_actions: List[Dict[str, Any]] = [
        {"type": "select",   "key": "client_uae_license_held_for", "label": "UAE License Held For", "value_col": "LicenseExperience_CRM"},
    ]

    general_details_actions: List[Dict[str, Any]] = [
        {"type": "select", "key": "general_business_type", "label": "Business Type", "value_col": "BusinessType"},
        {"type": "select", "key": "general_class", "label": "Class", "value_col": "Class"},
        {"type": "select", "key": "general_policy_type", "label": "Policy Type", "value_col": "PolicyTypeCRM"},
        {"type": "select", "key": "general_source", "label": "Source", "value_col": "Source"},
        {"type": "select", "key": "general_pos", "label": "POS", "value_col": "POS"},
        
        {"type": "select", "key": "general_classification", "label": "Classification", "value_col": "Classification"},
        {"type": "select", "key": "general_competitor", "label": "Competitor", "value_col": ""},
        {"type": "fill", "key": "general_client_ref_no", "label": "Client Ref No", "value_col": ""},
        {"type": "fill", "key": "general_location", "label": "Location", "value_col": "LocationRegion"},
        {"type": "select", "key": "general_sales_user", "label": "Sales User", "value_col": "SalesUser"},
        {"type": "select", "key": "general_assign_to_group", "label": "Assign to Group", "value_col": "AssignToGroup"},
        {"type": "select", "key": "general_assign_to_user", "label": "Assign to User", "value_col": "AssignToUser"},
    ]
    
    save_action: List[Dict[str, Any]] = [
        {"type": "click", "key": "save_button", "label": "Save New Prospect" , "validation_check": True},
    ]

    post_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "tab", "label": "New Prospect Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"},
    ]

    await select_client_process(page=page, df=df, logger=logger, run_id=run_id)

    # helper to only run actions whose keys exist in YAML
    def _filter(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [a for a in actions if a.get("key") and a.get("key") in selectors]

    # Execute sections
    for section_name, actions in [
        ("pre-upload",      _filter(pre_upload_actions)),
        ("general-details",  _filter(general_details_actions)),
        ("client-details",  _filter(client_details_actions)),
        ("save", _filter(save_action)),
    ]:
        if actions:
            try:
                await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
            except Exception as e:
                logger.error(f"Error during create-Prospect {section_name} actions: {e}")

    # After completing general-details actions, attempt to scrape the auto-filled Prospect RefNo (if selector exists)
    try:
        if "general_prospect_ref_no" in selectors:
            try:
                prospect_ref = await get_autofilled_input_value(
                    page,
                    logger=logger,
                    selector_key="general_prospect_ref_no",
                    selectors=selectors,
                    label="Prospect RefNo",
                    timeout_ms=10000,
                )
                logger.info(f"Scraped Prospect RefNo: {prospect_ref}")
                
                # Optionally write back to DF if desired:
                df.at[0, "crm_ref_no"] = prospect_ref
            except Exception as e:
                logger.debug(f"Could not scrape Prospect RefNo (continuing): {e}")
    except Exception:
        # defensive: don't let a failure here break the main flow
        logger.debug("Skipping Prospect RefNo scrape due to selectors or other error")

    # Pass run_id into vehicle_flow so vehicle steps also use run folder for validation
    await asyncio.sleep(1)
    
    dashboard_selectors = load_section_from_yaml("locators/main/dashboard_page.yml", section="dashboard")
    await vehicle_flow(page, df, dashboard_selectors, logger, run_id=run_id)
    
    # --- Upload documents (optional) ---
    try:
        # Sample documents list (edit to match your files). Use file_name WITHOUT extension (helper will find passport.*)
        documents = [
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
            logger.error(f"Error during create-Prospect post-upload actions: {e}")

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

    logger.info("Create Prospect process completed")
