from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
import logging
from pathlib import Path
import asyncio
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step, wait_for_not_visible
from src.utils.load_data import load_yaml_file


async def search_client_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Perform the Search Client process and return:
      - (True, None)  -> no matching rows found (new customer; caller may create customer)
      - (False, match_info) -> one or more matching rows found (existing customer with match details)
    """

    logger.info("Search Client process started")
    await asyncio.sleep(2)

    selectors_raw = selectors_group or {}

    # Safely grab row values
    search_data = {}
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0]
            search_data = {
                "emirates_id": str(row.get("EmiratesID", "") or "").strip(),
                "mobile_crm": str(row.get("Mobile_CRM", "") or "").strip(),
                "email_crm": str(row.get("Email_CRM", "") or "").strip(),
                "first_name": str(row.get("FirstName", "") or "").strip(),
                "last_name": str(row.get("LastName", "") or "").strip(),
            }
    except Exception as e:
        logger.debug(f"Failed to read values from df: {e}")

    # Configure search fields with their data keys and selector keys
    # Easy to extend by adding new entries to this list
    search_fields = [
        {
            "name": "Emirates ID",
            "data_key": "emirates_id",
            "selector_key": "search_emirates_id",
            "priority": 1
        },
        {
            "name": "Mobile Number",
            "data_key": "mobile_crm", 
            "selector_key": "search_mobile_number",
            "priority": 2
        },
        {
            "name": "Email Id",
            "data_key": "email_crm",
            "selector_key": "search_email_id",
            "priority": 3
        },
        # Easy to add more fields here:
        # {
        #     "name": "Phone Number",
        #     "data_key": "phone_number",
        #     "selector_key": "search_phone_number",
        #     "priority": 4
        # }
    ]

    # Filter fields that have actual values
    fields_to_search = []
    for field in search_fields:
        value = search_data.get(field["data_key"], "")
        if value:
            fields_to_search.append({**field, "value": value})
        else:
            logger.debug(f"Skipping {field['name']} - no value provided")

    if not fields_to_search:
        # Fallback to combined name search if no individual fields available
        combined_name = " ".join(filter(None, [search_data.get("first_name", ""), search_data.get("last_name", "")])).strip()
        if combined_name:
            logger.info("No individual search fields found; using combined client name for search.")
            fields_to_search = [{
                "name": "Client Name",
                "data_key": "combined_name",
                "selector_key": "search_client_name",
                "value": combined_name,
                "priority": 999
            }]

    if not fields_to_search:
        logger.warning("No search criteria available")
        return True  # Treat as new customer if no search data

    # Sort fields by priority
    fields_to_search.sort(key=lambda x: x["priority"])

    # Define reusable action templates
    clear_action = [
        {"type": "click", "key": "clear_button", "label": "Clear"}
    ]
    
    close_tab_action = [
        {"type": "click", "key": "tab", "label": "Opened Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"}
    ]

    # Open advanced search once at the beginning
    open_advanced_search = [
        {"type": "click", "key": "advanced_search_button", "label": "Open Advanced Search"}
    ]
    
    await run_actions(page, actions=open_advanced_search, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
    await asyncio.sleep(1)

    # Search each field sequentially
    for field in fields_to_search:
        logger.info(f"Searching by {field['name']}: '{field['value']}'")
        
        # Clear previous search values
        try:
            await run_actions(page, actions=clear_action, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
            await asyncio.sleep(1)
        except Exception as e:
            logger.debug(f"Failed to clear previous values: {e}")

        # Fill the search field and search
        search_actions = [
            {
                "type": "fill",
                "key": field["selector_key"],
                "label": field["name"],
                "value": field["value"]
            },
            {"type": "click", "key": "search_button", "label": "Search"}
        ]
        
        await run_actions(page, actions=search_actions, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
        await asyncio.sleep(2)
        
        # Wait for loading to complete
        loading_selector = 'div.loading.row[id^="load_tableClient__ClientSearchModel"]'
        try:
            await wait_for_not_visible(page, logger=logger, label="Wait client-table loading gone", selector=loading_selector, timeout_ms=40000)
            logger.debug("Loading spinner for client table is not visible.")
        except Exception as e:
            logger.debug(f"Loading spinner did not disappear (continuing): {e}")
        
        # Check for results
        table_selector = 'table[id^="tableClient__ClientSearchModel"]'
        rows_count = 0
        try:
            await page.wait_for_selector(table_selector, timeout=40000)
            rows_locator = page.locator(f"{table_selector} tbody tr.jqgrow")
            rows_count = await rows_locator.count()

            if rows_count == 0:
                all_rows = page.locator(f"{table_selector} tbody tr")
                total = await all_rows.count()
                header_count = await page.locator(f"{table_selector} tbody tr.jqgfirstrow").count()
                rows_count = max(0, total - header_count)

            logger.debug(f"Found {rows_count} data row(s) for {field['name']} search")
        except Exception as e:
            logger.error(f"Failed to locate or count rows in client table: {e}")
            rows_count = 0

        # If duplicates found, handle immediately
        if rows_count >= 1:
            if rows_count == 1:
                logger.info(f"Existing customer found by {field['name']} (1 row). Will proceed with selecting existing client.")
            else:
                logger.info(f"Existing customers found by {field['name']}: {rows_count} rows. Will proceed with selecting existing client.")

            # Store match information
            match_info = {
                "matched_by": field['name'],
                "matched_value": field['value'],
                "match_count": rows_count
            }
            
            # Close advanced search and tabs before returning
            try:
                close_advanced_search = [
                    {"type": "click", "key": "advanced_search_button", "label": "Close Advanced Search"}
                ]
                await run_actions(page, actions=close_advanced_search, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
                await asyncio.sleep(1)
                
                await run_actions(page, actions=close_tab_action, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
                await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"Failed to close UI elements after duplicate result: {e}")

            # Signal caller that existing client was found
            return False, match_info

        logger.info(f"No duplicates found for {field['name']} - continuing to next field")

    # If we reach here, no duplicates were found in any search
    logger.info("No matching rows found in any search — new customer. Proceed to create.")

    # Close advanced search and tabs after all searches complete
    try:
        close_advanced_search = [
            {"type": "click", "key": "advanced_search_button", "label": "Close Advanced Search"}
        ]
        await run_actions(page, actions=close_advanced_search, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
        await asyncio.sleep(1)
        
        await run_actions(page, actions=close_tab_action, selectors=selectors_raw, df=df, logger=logger, run_id=run_id)
        await asyncio.sleep(2)
    except Exception as e:
        logger.debug(f"Failed to close UI elements: {e}")
        
    # Wait for dashboard element visible (next page ready)
    dashboard_path = Path("locators/main/dashboard_page.yml")
    dashboard_yml = load_yaml_file(dashboard_path)

    dashboard_cfg = dashboard_yml.get("dashboard", {})
    dashboard_xpath = dashboard_cfg.get("xpath")

    if not dashboard_xpath:
        logger.error(f"Dashboard locator not found in {dashboard_path}")
        raise ValueError("Dashboard locator missing; cannot verify post-login dashboard")

    await wait_for_next_step(
        page,
        logger=logger,
        label="Dashboard page ready",
        selector=dashboard_xpath,
        timeout_ms=45000,
    )

    logger.info("Search Client process completed successfully")
    return True, None
