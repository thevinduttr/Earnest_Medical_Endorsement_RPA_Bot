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
        raise ValueError("company_name is required in manual_delete_member.json")

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


async def _open_manual_delete_page(page: Page, selectors: Dict[str, Any], logger: logging.Logger):
    policy_selector = ensure_selector_present(selectors, "policy_servicing_menu", logger)
    member_selector = ensure_selector_present(selectors, "member_menu", logger)
    delete_selector = ensure_selector_present(selectors, "delete_menu", logger)
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

    _assert_not_logged_out(page, "Open Manual Delete Page")
    await click_element(
        page,
        manual_selector,
        "Open Manual Delete Page",
        logger,
        timeout_ms=30000,
        wait_for_load=True,
        post_wait_ms=500,
    )


async def manual_delete_member(
    page: Page,
    delete_selectors: Dict[str, Any],
    delete_values: Dict[str, Any],
    upload_paths: Dict[str, str],
    logger: logging.Logger,
):
    logger.info("Manual member delete process started")

    dashboard_url = str(
        delete_values.get("dashboard_url")
        or "https://medical.sukoon.com/PolicyServicing/Dashboard/Overview"
    )

    if "/policyservicing/dashboard/overview" not in (page.url or "").lower():
        await page.goto(dashboard_url, wait_until="domcontentloaded")
        logger.info(f"Navigated to dashboard: {dashboard_url}")

    await _open_manual_delete_page(page, delete_selectors, logger)

    try:
        await page.wait_for_url("**/PolicyServicing/Member/ManualDelete*", timeout=60000)
        logger.info("Manual delete URL detected")
    except Exception as exc:
        logger.warning(f"Manual delete URL wait skipped/timeout: {exc}")

    await run_actions(
        page,
        actions=[
            {
                "type": "wait_visible",
                "key": "company_dropdown_toggle",
                "label": "Manual Delete Page Ready",
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
            "type": "select",
            "key": "delete_type_selector",
            "label": "Select Delete Type",
            "value_key": "delete_type",
            "timeout_ms": 20000,
            "wait_for_load": False,
        },
        {
            "type": "fill",
            "key": "employee_number_input",
            "label": "Enter Employee Number",
            "value_key": "employee_number",
            "timeout_ms": 20000,
            "post_wait_ms": 100,
        },
        {
            "type": "click",
            "key": "deletion_effective_date_input",
            "label": "Open Deletion Effective Date Picker",
            "timeout_ms": 20000,
            "wait_for_load": False,
            "wait_for_loader": False,
            "fail_on_validation_error": False,
            "post_wait_ms": 120,
        },
        {
            "type": "click",
            "key": "deletion_effective_date_picker_day",
            "label": "Pick Deletion Effective Date",
            "timeout_ms": 20000,
            "wait_for_load": False,
            "wait_for_loader": False,
            "fail_on_validation_error": False,
            "post_wait_ms": 150,
        },
        {
            "type": "upload",
            "key": "supporting_document_input",
            "label": "Upload Supporting File 1",
            "value_key": "delete_supporting_file_1",
            "required": False,
            "timeout_ms": 30000,
            "wait_for_load": True,
            "wait_for_loader": True,
        },
        {
            "type": "upload",
            "key": "supporting_document_input",
            "label": "Upload Supporting File 2",
            "value_key": "delete_supporting_file_2",
            "required": False,
            "timeout_ms": 30000,
            "wait_for_load": True,
            "wait_for_loader": True,
        },
        {
            "type": "fill",
            "key": "delete_comments",
            "label": "Enter Delete Comments",
            "value_key": "delete_comments",
            "required": False,
            "post_wait_ms": 100,
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

    if bool(delete_values.get("click_clear_after_fill", True)):
        await run_actions(
            page,
            actions=[
                {
                    "type": "click",
                    "key": "clear_button",
                    "label": "Clear Delete Form",
                    "required": False,
                    "timeout_ms": 30000,
                    "wait_for_load": True,
                    "wait_for_loader": True,
                    "fail_on_validation_error": False,
                    "post_wait_ms": 300,
                }
            ],
            selectors=delete_selectors,
            values=run_values,
            logger=logger,
            enforce_session_active=True,
        )

    logger.info("Manual member delete process completed")
