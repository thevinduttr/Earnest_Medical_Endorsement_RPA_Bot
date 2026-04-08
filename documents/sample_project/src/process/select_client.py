from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
import logging
from pathlib import Path
import asyncio
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step, wait_for_not_visible
from src.utils.load_data import load_yaml_file

async def select_client_process(
    page: Page,
    df: pd.DataFrame,
    logger: logging.Logger,
    run_id: str | None = None
) -> bool:
    """
    Perform the Search Client process and return:
      - True  -> no matching rows found (new customer; caller may create customer)
      - False -> one or more matching rows found (existing/duplicate; caller should not create)
    """

    logger.info("Select Client process started")
    await asyncio.sleep(2)  # brief pause to ensure page stability

    # Safely grab first row values (if df provided and not empty)
    search_data = {}
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0]
            
            # Extract and merge firstname and lastname for client name
            first_name = str(row.get("FirstName", "") or "").strip()
            last_name = str(row.get("LastName", "") or "").strip()
            
            # Create client name by merging firstname and lastname
            client_name = ""
            if first_name and last_name:
                client_name = f"{first_name} {last_name}".strip()
            elif first_name:
                client_name = first_name
            elif last_name:
                client_name = last_name
            
            search_data = {
                "emirates_id": str(row.get("EmiratesID", "") or "").strip(),
                "mobile": str(row.get("Mobile_CRM", "") or "").strip(),
                "email": str(row.get("Email_CRM", "") or "").strip(),
                "client_name": client_name,
            }
    except Exception as e:
        logger.debug(f"Failed to read values from df: {e}")

    # --- NEW: load select_client locators so we can reference tab & select_button directly ---
    select_client_path = Path("locators/main/select_client.yml")
    select_client_yml = load_yaml_file(select_client_path)
    select_client_cfg = select_client_yml.get("select_client", {})

    # 1) Click the "Select Client" button to open the client tab, then wait for the tab to be visible
    try:
        await run_actions(
            page,
            actions=[{"type": "click", "key": "select_client_button", "label": "Open Select Client"}],
            selectors=select_client_cfg,
            df=df,
            logger=logger,
        )
        tab_selector = select_client_cfg.get("modal")
        if tab_selector:
            await wait_for_next_step(page, logger=logger, label="Client Modal visible", selector=tab_selector, timeout_ms=20000)
            logger.debug("Client modal is visible")
            
            await asyncio.sleep(0.5)
        else:
            logger.warning(f"No 'modal' locator found in {select_client_path}; continuing without explicit modal wait")
    except Exception as e:
        logger.error(f"Failed to open/select client modal: {e}")
        # continue; subsequent steps may still work or will log errors

    # Define priority order for search fields
    search_fields = [
        {"name": "Emirates ID", "key": "search_emirates_id", "data_key": "emirates_id"},
        {"name": "Client Name", "key": "search_client_name", "data_key": "client_name"},
        {"name": "Mobile", "key": "search_mobile_number", "data_key": "mobile"},
        {"name": "Email", "key": "search_email_id", "data_key": "email"}
    ]

    # Try to find a matching client by searching with available fields in priority order
    client_found = False
    for field in search_fields:
        value = search_data.get(field["data_key"], "")
        if not value:
            logger.debug(f"Skipping {field['name']} - no value provided")
            continue

        logger.info(f"Attempting to search by {field['name']}: '{value}'")

        # Build action list for this search field
        actions: List[Dict[str, Any]] = [
            {"type": "click", "key": "advanced_search_button", "label": "Open Advanced Search"},
            {"type": "click", "key": "clear_button", "label": "Clear Search Fields"},
            {"type": "fill", "key": field["key"], "label": field['name'], "value": value},
            {"type": "click", "key": "search_button", "label": "Search"},
            {"type": "click", "key": "advanced_search_button", "label": "Close Advanced Search"},
        ]

        # Run the search actions
        await run_actions(page, actions=actions, selectors=select_client_cfg, df=df, logger=logger)
        await asyncio.sleep(2)

        # Wait for loading spinner (dynamic id) to disappear before checking the result table.
        loading_selector = 'div.loading.row[id^="load_tableClient__ClientSearchModel"]'
        try:
            await wait_for_not_visible(page, logger=logger, label="Wait client-table loading gone", selector=loading_selector, timeout_ms=40000)
            logger.debug("Loading spinner for client table is not visible.")
        except Exception as e:
            logger.debug(f"Loading spinner did not disappear (continuing): {e}")

        # flexible selector: any table whose id starts with 'tableClient__ClientSearchModel'
        table_selector = 'table[id^="tableClient__ClientSearchModel"]'
        rows_count = 0
        try:
            # wait until the table exists in DOM (may already be present)
            await page.wait_for_selector(table_selector, timeout=40000)

            # Preferred method: count rows with 'jqgrow' class (data rows)
            rows_locator = page.locator(f"{table_selector} tbody tr.jqgrow")
            rows_count = await rows_locator.count()

            # Fallback: if no jqgrow rows found, count tbody tr and subtract header row (jqgfirstrow)
            if rows_count == 0:
                all_rows = page.locator(f"{table_selector} tbody tr")
                total = await all_rows.count()
                header_count = await page.locator(f"{table_selector} tbody tr.jqgfirstrow").count()
                rows_count = max(0, total - header_count)

            logger.debug(f"Found {rows_count} data row(s) in client results table for {field['name']} search")
        except Exception as e:
            logger.error(f"Failed to locate or count rows in client table '{table_selector}': {e}")
            rows_count = 0

        # If exactly 1 client found, select it and break
        if rows_count == 1:
            logger.info(f"Existing customer found by {field['name']} (1 row). Selecting the row.")
            try:
                first_row_locator = page.locator(f"{table_selector} tbody tr.jqgrow, {table_selector} tbody tr:not(.jqgfirstrow)").first
                await first_row_locator.click()
                logger.debug("Clicked first client row")

                select_button_selector = select_client_cfg.get("select_button")
                if select_button_selector:
                    try:
                        await run_actions(
                            page,
                            actions=[{"type": "click", "key": "select_button", "label": "Select"}],
                            selectors=select_client_cfg,
                            df=df,
                            logger=logger,
                        )
                    except Exception:
                        await page.click(select_button_selector)
                    logger.info(f"Clicked Select button for the chosen client (matched by {field['name']})")
                else:
                    logger.error(f"'select_button' locator not found in {select_client_path}; cannot click Select.")
                client_found = True
                break
            except Exception as e:
                logger.error(f"Failed to select client row or click Select: {e}")
                break
        elif rows_count > 1:
            # More than one matching client -> select first row and break
            logger.warning(f"Multiple matching clients found ({rows_count}) by {field['name']}. Selecting the first row.")
            try:
                first_row_locator = page.locator(f"{table_selector} tbody tr.jqgrow, {table_selector} tbody tr:not(.jqgfirstrow)").first
                await first_row_locator.click()
                logger.debug("Clicked first client row (multiple results present)")

                select_button_selector = select_client_cfg.get("select_button")
                if select_button_selector:
                    try:
                        await run_actions(
                            page,
                            actions=[{"type": "click", "key": "select_button", "label": "Select"}],
                            selectors=select_client_cfg,
                            df=df,
                            logger=logger,
                        )
                    except Exception:
                        await page.click(select_button_selector)
                    logger.info(f"Clicked Select button for the first client (matched by {field['name']}, multiple results)")
                else:
                    logger.error(f"'select_button' locator not found in {select_client_path}; cannot click Select.")
                client_found = True
                break
            except Exception as e:
                logger.error(f"Failed to select first client row when multiple results found: {e}")
                break
        else:
            # No rows found with this field, try next field
            logger.info(f"No matching client found by {field['name']}. Trying next search field...")
            continue

    # If no client was found after all attempts
    if not client_found:
        logger.error("No matching client rows found with any search criteria. Cannot select a client.")
        raise ValueError("Failed to find and select client with any available search criteria")

    # --- Wait for dashboard element visible (next page ready) ---
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

    logger.info("Select Client process completed successfully")
    return True