from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

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
        raise ValueError("company_name is required in batch_delete_member.json")

    dropdown_toggle = ensure_selector_present(selectors, "policy_dropdown_toggle", logger)
    await click_element(
        page,
        dropdown_toggle,
        "Open Policy Number Dropdown",
        logger,
        timeout_ms=20000,
        wait_for_load=False,
        post_wait_ms=300,
    )

    option_items_selector = str(selectors.get("policy_option_items") or "li a span.text").strip()
    option_locator = page.locator(option_items_selector).filter(has_text=company_name).first
    await option_locator.wait_for(state="visible", timeout=20000)
    await option_locator.click()

    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    logger.info(f"Policy selected: {company_name}")


async def _open_batch_delete_page(page: Page, selectors: Dict[str, Any], logger: logging.Logger):
    policy_selector = ensure_selector_present(selectors, "policy_servicing_menu", logger)
    member_selector = ensure_selector_present(selectors, "member_menu", logger)
    delete_selector = ensure_selector_present(selectors, "delete_menu", logger)
    batch_selector = ensure_selector_present(selectors, "batch_menu", logger)

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
            delete_selector,
            "Open Delete Menu",
            logger,
            timeout_ms=7000,
            wait_for_load=False,
            post_wait_ms=250,
        )
    except Exception:
        logger.info("Delete menu not visible after first Member click. Retrying Member menu expansion.")
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
            delete_selector,
            "Open Delete Menu",
            logger,
            timeout_ms=20000,
            wait_for_load=False,
            post_wait_ms=250,
        )

    _assert_not_logged_out(page, "Open Batch Delete Page")
    await click_element(
        page,
        batch_selector,
        "Open Batch Delete Page",
        logger,
        timeout_ms=30000,
        wait_for_load=True,
        post_wait_ms=500,
    )


async def batch_delete_member(
    page: Page,
    delete_selectors: Dict[str, Any],
    delete_values: Dict[str, Any],
    upload_paths: Dict[str, str],
    logger: logging.Logger,
):
    logger.info("Batch member delete process started")

    dashboard_url = str(
        delete_values.get("dashboard_url")
        or "https://medical.sukoon.com/PolicyServicing/Dashboard/Overview"
    )

    if "/policyservicing/dashboard/overview" not in (page.url or "").lower():
        await page.goto(dashboard_url, wait_until="domcontentloaded")
        logger.info(f"Navigated to dashboard: {dashboard_url}")

    await _open_batch_delete_page(page, delete_selectors, logger)

    try:
        await page.wait_for_url("**/PolicyServicing/Member/BatchDeletion*", timeout=60000)
        logger.info("Batch deletion URL detected")
    except Exception as exc:
        logger.warning(f"Batch delete URL wait skipped/timeout: {exc}")

    await run_actions(
        page,
        actions=[
            {
                "type": "wait_visible",
                "key": "policy_dropdown_toggle",
                "label": "Batch Delete Page Ready",
                "timeout_ms": 30000,
            }
        ],
        selectors=delete_selectors,
        values=delete_values,
        logger=logger,
        enforce_session_active=True,
    )

    await _select_company(page, delete_selectors, delete_values, logger)

    run_values = dict(delete_values)
    run_values.update(upload_paths or {})

    actions: List[Dict[str, Any]] = [
        {
            "type": "upload",
            "key": "batch_delete_member_file_input",
            "label": "Upload Batch Delete Member File",
            "value_key": "batch_delete_member_file",
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "upload",
            "key": "batch_delete_supporting_document_input",
            "label": "Upload Batch Delete Supporting Document 1",
            "value_key": "batch_delete_supporting_document_1",
            "required": False,
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "upload",
            "key": "batch_delete_supporting_document_input",
            "label": "Upload Batch Delete Supporting Document 2",
            "value_key": "batch_delete_supporting_document_2",
            "required": False,
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "fill",
            "key": "batch_delete_comments",
            "label": "Enter Batch Delete Comments",
            "value_key": "batch_delete_comments",
            "required": False,
            "post_wait_ms": 150,
        },
        {
            "type": "click",
            "key": "pre_validate_panel_1",
            "label": "Focus Pre-Validate Panel 1",
            "required": False,
            "wait_for_load": False,
            "wait_for_loader": False,
            "fail_on_validation_error": False,
            "post_wait_ms": 100,
            "timeout_ms": 12000,
        },
        {
            "type": "click",
            "key": "pre_validate_panel_2",
            "label": "Focus Pre-Validate Panel 2",
            "required": False,
            "wait_for_load": False,
            "wait_for_loader": False,
            "fail_on_validation_error": False,
            "post_wait_ms": 120,
            "timeout_ms": 12000,
        },
        {
            "type": "click",
            "key": "batch_delete_validate_button",
            "label": "Click Validate",
            "wait_for_load": True,
            "wait_for_loader": True,
            "fail_on_validation_error": True,
            "timeout_ms": 60000,
            "post_wait_ms": 400,
        },
    ]

    await run_actions(
        page,
        actions=actions,
        selectors=delete_selectors,
        values=run_values,
        logger=logger,
        enforce_session_active=True,
    )

    logger.info("Batch member delete process completed")
