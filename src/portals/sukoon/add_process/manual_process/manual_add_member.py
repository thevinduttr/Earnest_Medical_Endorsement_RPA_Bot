from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.portals.sukoon.add_process.manual_process.sections.communication_details_section import (
    fill_communication_details_section,
)
from src.portals.sukoon.add_process.manual_process.sections.profile_section import fill_profile_section
from src.portals.sukoon.add_process.manual_process.sections.sponsor_details_section import (
    fill_sponsor_details_section,
)
from src.portals.sukoon.add_process.manual_process.sections.upload_member_files_section import (
    fill_upload_member_files_section,
)

from src.utils.support_functions import click_element, ensure_selector_present, run_actions


def _assert_not_logged_out(page: Page, step: str):
    current_url = (page.url or "").lower()
    if "myaccount.sukoon.com" in current_url or "oauth2/v2.0/authorize" in current_url:
        raise RuntimeError(
            f"{step}: redirected to authentication page ({page.url}). "
            "Business tab might not be selected or session expired."
        )


async def _select_company(page: Page, selectors: Dict[str, Any], values: Dict[str, Any], logger: logging.Logger):
    company_name = str(values.get("company_name") or "").strip()
    if not company_name:
        raise ValueError("company_name is required in manual_add_member.json")

    dropdown_toggle = ensure_selector_present(selectors, "company_dropdown_toggle", logger)
    await click_element(
        page,
        dropdown_toggle,
        "Open Company Dropdown",
        logger,
        timeout_ms=20000,
        wait_for_load=False,
        post_wait_ms=300,
    )

    option_items_selector = str(selectors.get("company_option_items") or "li a span.text").strip()
    option_locator = page.locator(option_items_selector).filter(has_text=company_name).first
    await option_locator.wait_for(state="visible", timeout=20000)
    await option_locator.click()

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    logger.info(f"Company selected: {company_name}")


async def _open_manual_member_page(page: Page, selectors: Dict[str, Any], logger: logging.Logger):
    policy_selector = ensure_selector_present(selectors, "policy_servicing_menu", logger)
    member_selector = ensure_selector_present(selectors, "member_menu", logger)
    add_selector = ensure_selector_present(selectors, "add_menu", logger)
    manual_selector = ensure_selector_present(selectors, "manual_menu", logger)

    _assert_not_logged_out(page, "Open Policy Servicing Menu")
    await click_element(
        page,
        policy_selector,
        "Open Policy Servicing Menu",
        logger,
        timeout_ms=20000,
        wait_for_load=True,
        post_wait_ms=300,
    )

    _assert_not_logged_out(page, "Open Member Menu")
    await click_element(
        page,
        member_selector,
        "Open Member Menu",
        logger,
        timeout_ms=20000,
        wait_for_load=False,
        post_wait_ms=250,
    )

    try:
        await click_element(
            page,
            add_selector,
            "Open Add Menu",
            logger,
            timeout_ms=7000,
            wait_for_load=False,
            post_wait_ms=250,
        )
    except Exception:
        logger.info("Add menu not visible after first Member click. Retrying Member menu expansion.")
        await click_element(
            page,
            member_selector,
            "Re-open Member Menu",
            logger,
            timeout_ms=15000,
            wait_for_load=False,
            post_wait_ms=250,
        )
        await click_element(
            page,
            add_selector,
            "Open Add Menu",
            logger,
            timeout_ms=20000,
            wait_for_load=False,
            post_wait_ms=250,
        )

    _assert_not_logged_out(page, "Open Manual Add Page")
    await click_element(
        page,
        manual_selector,
        "Open Manual Add Page",
        logger,
        timeout_ms=30000,
        wait_for_load=True,
        post_wait_ms=500,
    )


async def manual_add_member(
    page: Page,
    manual_selectors: Dict[str, Any],
    manual_values: Dict[str, Any],
    upload_paths: Dict[str, str],
    logger: logging.Logger,
):
    logger.info("Manual member add process started")

    dashboard_url = str(
        manual_values.get("dashboard_url")
        or "https://medical.sukoon.com/PolicyServicing/Dashboard/Overview"
    )

    if "/policyservicing/dashboard/overview" not in (page.url or "").lower():
        await page.goto(dashboard_url, wait_until="domcontentloaded")
        logger.info(f"Navigated to dashboard: {dashboard_url}")

    await _open_manual_member_page(page, manual_selectors, logger)

    try:
        await page.wait_for_url("**/PolicyServicing/member/manualaddition*", timeout=60000)
        logger.info("Manual addition URL detected")
    except Exception as exc:
        logger.warning(f"Manual page URL wait skipped/timeout: {exc}")

    await run_actions(
        page,
        actions=[
            {
                "type": "wait_visible",
                "key": "company_dropdown_toggle",
                "label": "Manual Add Page Ready",
                "timeout_ms": 30000,
            }
        ],
        selectors=manual_selectors,
        values=manual_values,
        logger=logger,
        enforce_session_active=True,
    )

    await _select_company(page, manual_selectors, manual_values, logger)
    await fill_profile_section(page, manual_selectors, manual_values, logger)
    await fill_communication_details_section(page, manual_selectors, manual_values, logger)
    await fill_sponsor_details_section(page, manual_selectors, manual_values, logger)
    await fill_upload_member_files_section(page, manual_selectors, manual_values, upload_paths, logger)

    logger.info("Manual member add process completed (all sections)")
