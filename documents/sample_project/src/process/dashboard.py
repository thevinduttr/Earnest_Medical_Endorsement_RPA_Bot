from __future__ import annotations
from typing import Any, Dict, List
import logging
import asyncio
import pandas as pd
from pathlib import Path
from playwright.async_api import Page

from src.utils.support_functions import run_actions , wait_for_next_step
from src.utils.load_data import load_yaml_file

async def open_client_search(
    page: Page,
    df: pd.DataFrame,
    dashboard_selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
):

    # Build actions (loop-driven)
    actions: List[Dict[str, Any]] = [
        # {"type": "click", "key": "toggle_sidebar",         "label": "Toggle sidebar"},
        {"type": "click", "key": "sidebar_client_main",    "label": "Open Client menu"},
        {"type": "click", "key": "sidebar_search_client",  "label": "Open Search Client"},
    ]

    await run_actions(page, actions=actions, selectors=dashboard_selectors_group, df=df, logger=logger)
    logger.info("Dashboard: navigated to Client → Search Client and Waiting for page load")
    
    # --- NEW: Wait for dashboard element visible (next page ready) ---
    search_client_path = Path("locators/client/search_client.yml")
    search_client_yml = load_yaml_file(search_client_path)

    # Expect structure: dashboard: { xpath: "..." }
    search_client_cfg = search_client_yml.get("search_client", {})
    search_client_xpath = search_client_cfg.get("tab")

    if not search_client_xpath:
        logger.error(f"Search Client locator not found in {search_client_path}")
        raise ValueError("Search Client locator missing; cannot verify post-login dashboard")

    # Wait for the next-step element (dashboard) to appear
    await wait_for_next_step(
        page,
        logger=logger,
        label="Search Client page ready",
        selector=search_client_xpath,
        timeout_ms=45000,  # optional: custom timeout for dashboard load
    )

    logger.info("Dashboard: Search Client page loaded successfully.")
    await asyncio.sleep(1)
    
async def open_client_create(
    page: Page,
    df: pd.DataFrame,
    dashboard_selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
):
    """
    From the dashboard, open Client -> Create Client using selectors in locators/main/dashboard_page.yml
    """
    # Build actions (loop-driven)
    actions: List[Dict[str, Any]] = [
        # {"type": "click", "key": "toggle_sidebar",         "label": "Toggle sidebar"},
        {"type": "click", "key": "sidebar_client_main",    "label": "Open Client menu"},
        {"type": "click", "key": "sidebar_create_client",  "label": "Open Create Client"},
    ]

    await run_actions(page, actions=actions, selectors=dashboard_selectors_group, df=df, logger=logger)
    logger.info("Dashboard: navigated to Client → Create Client and Waiting for page load")
    
    # --- NEW: Wait for dashboard element visible (next page ready) ---
    create_client_path = Path("locators/client/create_client.yml")
    create_client_yml = load_yaml_file(create_client_path)

    # Expect structure: create_client: { tab: "..." }
    create_client_cfg = create_client_yml.get("create_client", {})
    create_client_xpath = create_client_cfg.get("tab")

    if not create_client_xpath:
        logger.error(f"Create Client locator not found in {create_client_path}")
        raise ValueError("Create Client locator missing; cannot verify post-login dashboard")

    # Wait for the next-step element (dashboard) to appear
    await wait_for_next_step(
        page,
        logger=logger,
        label="Create Client page ready",
        selector=create_client_xpath,
        timeout_ms=45000,  # optional: custom timeout for dashboard load
    )
    
    logger.info("Dashboard: Create Client page loaded successfully.")
    await asyncio.sleep(1)

async def open_lead_create(
    page: Page,
    df: pd.DataFrame,
    dashboard_selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
):
    """
    From the dashboard, open Lead -> Create Lead using selectors in locators/main/dashboard_page.yml
    """
    # Build actions (loop-driven)
    actions: List[Dict[str, Any]] = [
        # {"type": "click", "key": "toggle_sidebar",         "label": "Toggle sidebar"},
        {"type": "click", "key": "sidebar_lead_main",      "label": "Open Lead menu"},
        {"type": "click", "key": "sidebar_create_lead",    "label": "Open Create Lead"},
    ]

    await run_actions(page, actions=actions, selectors=dashboard_selectors_group, df=df, logger=logger)
    logger.info("Dashboard: navigated to Lead → Create Lead and Waiting for page load")
    
    # --- NEW: Wait for dashboard element visible (next page ready) ---
    create_lead_path = Path("locators/lead/create_lead.yml")
    create_lead_yml = load_yaml_file(create_lead_path)

    # Expect structure: create_lead: { tab: "..." }
    create_lead_cfg = create_lead_yml.get("create_lead", {})
    create_lead_xpath = create_lead_cfg.get("tab")

    if not create_lead_xpath:
        logger.error(f"Create Lead locator not found in {create_lead_path}")
        raise ValueError("Create Lead locator missing; cannot verify post-login dashboard")

    # Wait for the next-step element (dashboard) to appear
    await wait_for_next_step(
        page,
        logger=logger,
        label="Create Lead page ready",
        selector=create_lead_xpath,
        timeout_ms=45000,  # optional: custom timeout for dashboard load
    )
    
    logger.info("Dashboard: Create Lead page loaded successfully.")
    await asyncio.sleep(1)
    
async def open_prospect_create(
    page: Page,
    df: pd.DataFrame,
    dashboard_selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
):
    """
    From the dashboard, open Prospect -> Create Prospect using selectors in locators/main/dashboard_page.yml
    """
    # Build actions (loop-driven)
    actions: List[Dict[str, Any]] = [
        # {"type": "click", "key": "toggle_sidebar",         "label": "Toggle sidebar"},
        {"type": "click", "key": "sidebar_prospect_main",      "label": "Open Prospect menu"},
        {"type": "click", "key": "sidebar_create_prospect",    "label": "Open Create Prospect"},
    ]

    await run_actions(page, actions=actions, selectors=dashboard_selectors_group, df=df, logger=logger)
    logger.info("Dashboard: navigated to Prospect → Create Prospect and Waiting for page load")
    
    # --- NEW: Wait for dashboard element visible (next page ready) ---
    create_prospect_path = Path("locators/prospect/create_prospect.yml")
    create_prospect_yml = load_yaml_file(create_prospect_path)

    # Expect structure: create_prospect: { tab: "..." }
    create_prospect_cfg = create_prospect_yml.get("create_prospect", {})
    create_prospect_xpath = create_prospect_cfg.get("tab")

    if not create_prospect_xpath:
        logger.error(f"Create Prospect locator not found in {create_prospect_path}")
        raise ValueError("Create Prospect locator missing; cannot verify post-login dashboard")

    # Wait for the next-step element (dashboard) to appear
    await wait_for_next_step(
        page,
        logger=logger,
        label="Create Prospect page ready",
        selector=create_prospect_xpath,
        timeout_ms=45000,  # optional: custom timeout for dashboard load
    )
    
    logger.info("Dashboard: Create Prospect page loaded successfully.")
    await asyncio.sleep(1)