from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
import logging
from pathlib import Path
import asyncio
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step, wait_for_not_visible
from src.utils.load_data import load_yaml_file

async def search_select_vehicle_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None
) -> bool:
    """
    Search vehicle by chassis and:
      - return True  -> no matching rows found (new vehicle; caller may create)
      - return False -> one or more matching rows found (existing/duplicate; selected first row)
    """
    logger.info("Search Vehicle process started")
    await asyncio.sleep(1)
    
    selectors_raw = selectors_group or {}

    # Safely get chassis value from df (support common column names)
    chassis = ""
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0]
            chassis = str(row.get("ChassisNumber", "")).strip()
    except Exception as e:
        logger.debug(f"Failed to read chassis from df: {e}")

    # Build actions to open advanced search, fill chassis and run search
    actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "search_vehicle_button", "label": "Search Vehicle"},
        {"type": "click", "key": "advanced_search_button", "label": "Open Advanced Search"},
    ]

    if chassis:
        logger.info("Chassis value found; using it for search.")
        actions.append(
            {
                "type": "fill",
                "key": "search_chassis",
                "label": "Chassis No",
                "value": chassis,
            }
        )
    else:
        logger.info("No chassis value provided; performing empty chassis search (may return many).")

    actions.extend(
        [
            {"type": "click", "key": "search_button", "label": "Search"},
            {"type": "click", "key": "advanced_search_button", "label": "Close Advanced Search"},
        ]
    )
    
    close_actions = [
        {"type": "click", "key": "close_modal_button", "label": "Close Vehicle Modal"},
    ]

    # Execute search actions
    await run_actions(page, actions=actions, selectors=selectors_raw, df=df, logger=logger)
    await asyncio.sleep(0.5)

    # Wait for potential loading spinner specific to table (best-effort)
    loading_selector = 'div.loading.row[id^="load_vehicle__VehicleSearchModel"], div.loading.row[id^="load_table"]'
    try:
        await wait_for_not_visible(page, logger=logger, label="Wait vehicle-table loading gone", selector=loading_selector, timeout_ms=30000)
    except Exception as e:
        logger.debug(f"Vehicle loading spinner did not disappear (continuing): {e}")

    # Try to locate the results table - flexible selector (best guess similar to client table naming)
    table_selector = 'table[id^="vehicle__VehicleSearchModel"]'
    rows_count = 0
    try:
        await page.wait_for_selector(table_selector, timeout=20000)

        rows_locator = page.locator(f"{table_selector} tbody tr.jqgrow")
        rows_count = await rows_locator.count()

        if rows_count == 0:
            all_rows = page.locator(f"{table_selector} tbody tr")
            total = await all_rows.count()
            header_count = await page.locator(f"{table_selector} tbody tr.jqgfirstrow").count()
            rows_count = max(0, total - header_count)

        logger.debug(f"Found {rows_count} data row(s) in vehicle results table (selector={table_selector})")
    except Exception as e:
        logger.error(f"Failed to locate or count rows in vehicle table '{table_selector}': {e}")
        rows_count = 0

    is_new_vehicle = False

    if rows_count == 1:
        logger.info("Existing vehicle found (1 row). Selecting the row.")
        try:
            first_row_locator = page.locator(f"{table_selector} tbody tr.jqgrow, {table_selector} tbody tr:not(.jqgfirstrow)").first
            await first_row_locator.click()
            logger.debug("Clicked first vehicle row")

            select_button_selector = selectors_raw.get("select_button")
            if select_button_selector:
                try:
                    await run_actions(
                        page,
                        actions=[{"type": "click", "key": "select_button", "label": "Select"}],
                        selectors=selectors_raw,
                        df=df,
                        logger=logger,
                    )
                except Exception:
                    await page.click(select_button_selector)
                logger.info("Clicked Select button for the chosen vehicle")
            else:
                logger.debug(f"No 'select_button' in locators; row selected but Select click skipped.")
        except Exception as e:
            logger.error(f"Failed to select vehicle row or click Select: {e}")
        is_new_vehicle = False

    elif rows_count > 1:
        logger.error(f"Multiple matching vehicles found ({rows_count}). Expected exactly 1. Selecting the first row anyway.")
        try:
            first_row_locator = page.locator(f"{table_selector} tbody tr.jqgrow, {table_selector} tbody tr:not(.jqgfirstrow)").first
            await first_row_locator.click()
            logger.debug("Clicked first vehicle row (multiple results present)")

            select_button_selector = selectors_raw.get("select_button")
            if select_button_selector:
                try:
                    await run_actions(
                        page,
                        actions=[{"type": "click", "key": "select_button", "label": "Select"}],
                        selectors=selectors_raw,
                        df=df,
                        logger=logger,
                    )
                except Exception:
                    await page.click(select_button_selector)
                logger.info("Clicked Select button for the first vehicle (multiple results present)")
            else:
                logger.debug(f"No 'select_button' in locators; row selected but Select click skipped.")
        except Exception as e:
            logger.error(f"Failed to select first vehicle row when multiple results found: {e}")
        is_new_vehicle = False

    else:
        logger.info("No matching vehicle rows found — new vehicle. Proceed to create.")
        is_new_vehicle = True
        
    if is_new_vehicle:
        try:
            await run_actions(page, actions=close_actions, selectors=selectors_raw, df=df, logger=logger)
            logger.debug("Closed vehicle search modal for new vehicle")
        except Exception as e:
            logger.error(f"Failed to close vehicle modal for new vehicle: {e}")

    logger.info("Search Vehicle process completed")
    return is_new_vehicle
