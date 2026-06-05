from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.utils.support_functions import click_element, ensure_selector_present, run_actions


@dataclass(frozen=True)
class BatchValidationError:
    first_name: str
    last_name: str
    eid_number: str
    employee_number: str
    error_message: str


@dataclass(frozen=True)
class BatchAddResult:
    validation_message: str | None
    invalid_members: List[BatchValidationError]
    reference_number: str | None = None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_header(value: Any) -> str:
    return _normalize_text(value).lower()


async def _extract_summary_message(page: Page) -> str | None:
    message_selectors = [
        "#member-summary #message-panel",
        "#message-placeholder #message-panel",
        "#message-placeholder .alert.alert-danger",
        "#message-placeholder .alert.alert-success",
    ]

    for selector in message_selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            if await candidate.is_visible():
                text = _normalize_text(await candidate.inner_text())
                if text:
                    return text

    return None


async def _extract_invalid_member_errors(page: Page, logger: logging.Logger) -> List[BatchValidationError]:
    try:
        rows_payload = await page.evaluate(
            """
            () => {
                const table = document.querySelector('#member-summary #grid table');
                if (!table) return [];

                const headers = Array.from(table.querySelectorAll('thead th')).map(
                    (th) => (th.textContent || '').trim()
                );

                const rows = Array.from(table.querySelectorAll('tbody tr')).map((tr) => {
                    const cells = Array.from(tr.querySelectorAll('td')).map(
                        (td) => (td.textContent || '').trim()
                    );
                    const entry = {};
                    headers.forEach((header, idx) => {
                        entry[header] = cells[idx] || '';
                    });
                    return entry;
                });

                return rows;
            }
            """
        )
    except Exception as exc:
        logger.warning(f"Unable to extract Invalid Members table rows: {exc}")
        return []

    errors: List[BatchValidationError] = []
    for row_data in rows_payload or []:
        normalized_row = {
            _normalize_header(column): _normalize_text(value)
            for column, value in dict(row_data or {}).items()
        }

        error_message = (
            normalized_row.get("error message")
            or normalized_row.get("validation error")
            or normalized_row.get("validationerror")
            or ""
        )
        if not error_message:
            continue

        errors.append(
            BatchValidationError(
                first_name=normalized_row.get("first name", ""),
                last_name=normalized_row.get("last name", ""),
                eid_number=normalized_row.get("eid number", ""),
                employee_number=normalized_row.get("employee number", ""),
                error_message=error_message,
            )
        )

    return errors


async def _has_validation_table_rows(page: Page) -> bool:
    try:
        rows = page.locator("#member-summary #grid tbody tr")
        count = await rows.count()
        if count <= 0:
            return False

        for index in range(count):
            if await rows.nth(index).is_visible():
                return True
        return False
    except Exception:
        return False


async def _is_submit_visible(page: Page) -> bool:
    try:
        submit = page.locator("#btnSubmit")
        count = await submit.count()
        for index in range(count):
            if await submit.nth(index).is_visible():
                return True
        return False
    except Exception:
        return False


async def _extract_submission_reference_number(page: Page) -> str | None:
    selectors = [
        "[data-bind='text: submissionReferenceNumber']",
        ".row.border.table-inside-padding [data-bind='text: submissionReferenceNumber']",
    ]

    for selector in selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            if await candidate.is_visible():
                text = _normalize_text(await candidate.inner_text())
                if text:
                    return text

    return None


async def _submit_batch_and_extract_reference(
    page: Page,
    selectors: Dict[str, Any],
    logger: logging.Logger,
) -> str:
    submit_selector = ensure_selector_present(selectors, "batch_submit_button", logger)
    await click_element(
        page,
        submit_selector,
        "Click Submit",
        logger,
        timeout_ms=30000,
        wait_for_load=True,
        wait_for_loader=True,
        post_wait_ms=400,
        fail_on_validation_error=False,
    )

    try:
        await page.wait_for_url("**/PolicyServicing/Member/AdditionReview*", timeout=60000)
        logger.info("Addition review URL detected after submit")
    except Exception as exc:
        logger.warning(f"Addition review URL wait skipped/timeout: {exc}")

    try:
        await page.locator("[data-bind='text: submissionReferenceNumber']").first.wait_for(
            state="visible",
            timeout=30000,
        )
    except Exception:
        pass

    reference_number = await _extract_submission_reference_number(page)
    if not reference_number:
        raise RuntimeError("Reference number not found on addition review page after submit")

    logger.info(f"Batch submission reference number extracted: {reference_number}")
    return reference_number


async def _wait_for_validation_outcome(
    page: Page,
    logger: logging.Logger,
    timeout_ms: int = 60000,
) -> BatchAddResult:
    deadline = asyncio.get_running_loop().time() + max(timeout_ms / 1000.0, 1.0)

    while asyncio.get_running_loop().time() < deadline:
        validation_message = await _extract_summary_message(page)
        if validation_message:
            normalized_message = validation_message.lower()
            if "invalid member" in normalized_message:
                invalid_members = await _extract_invalid_member_errors(page, logger)
                if not invalid_members:
                    invalid_members = [
                        BatchValidationError(
                            first_name="",
                            last_name="",
                            eid_number="",
                            employee_number="",
                            error_message=validation_message,
                        )
                    ]
                return BatchAddResult(
                    validation_message=validation_message,
                    invalid_members=invalid_members,
                )

            if any(token in normalized_message for token in ("required", "error", "cannot", "failed", "invalid")):
                return BatchAddResult(
                    validation_message=validation_message,
                    invalid_members=[],
                )

        if await _has_validation_table_rows(page):
            invalid_members = await _extract_invalid_member_errors(page, logger)
            if invalid_members:
                return BatchAddResult(
                    validation_message="Invalid Members",
                    invalid_members=invalid_members,
                )

            return BatchAddResult(validation_message=validation_message, invalid_members=[])

        if await _is_submit_visible(page):
            return BatchAddResult(validation_message=validation_message, invalid_members=[])

        await asyncio.sleep(0.5)

    raise RuntimeError(
        f"Click Validate: no validation outcome detected within {timeout_ms}ms "
        "(no message, no member table rows, no Submit button)"
    )


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
        raise ValueError("company_name is required in batch_add_member.json")

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


async def _click_view_after_policy_selection(page: Page, selectors: Dict[str, Any], logger: logging.Logger):
    view_selector = ensure_selector_present(selectors, "batch_view_button", logger)
    await click_element(
        page,
        view_selector,
        "Click View",
        logger,
        timeout_ms=20000,
        wait_for_load=True,
        wait_for_loader=True,
        post_wait_ms=350,
        fail_on_validation_error=False,
    )

    # Upload input becoming visible confirms the policy context is loaded.
    await page.locator(ensure_selector_present(selectors, "batch_member_file_input", logger)).first.wait_for(
        state="visible",
        timeout=30000,
    )
    logger.info("View loaded and batch upload controls are visible")


async def _open_batch_member_page(page: Page, selectors: Dict[str, Any], logger: logging.Logger):
    policy_selector = ensure_selector_present(selectors, "policy_servicing_menu", logger)
    member_selector = ensure_selector_present(selectors, "member_menu", logger)
    add_selector = ensure_selector_present(selectors, "add_menu", logger)
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

    _assert_not_logged_out(page, "Open Batch Add Page")
    await click_element(
        page,
        batch_selector,
        "Open Batch Add Page",
        logger,
        timeout_ms=30000,
        wait_for_load=True,
        post_wait_ms=500,
    )


async def batch_add_member(
    page: Page,
    batch_selectors: Dict[str, Any],
    batch_values: Dict[str, Any],
    upload_paths: Dict[str, str],
    logger: logging.Logger,
) -> BatchAddResult:
    logger.info("Batch member add process started")

    dashboard_url = str(
        batch_values.get("dashboard_url")
        or "https://medical.sukoon.com/PolicyServicing/Dashboard/Overview"
    )

    if "/policyservicing/dashboard/overview" not in (page.url or "").lower():
        await page.goto(dashboard_url, wait_until="domcontentloaded")
        logger.info(f"Navigated to dashboard: {dashboard_url}")

    await _open_batch_member_page(page, batch_selectors, logger)

    try:
        await page.wait_for_url("**/PolicyServicing/Member/BatchAddition*", timeout=60000)
        logger.info("Batch addition URL detected")
    except Exception as exc:
        logger.warning(f"Batch page URL wait skipped/timeout: {exc}")

    await run_actions(
        page,
        actions=[
            {
                "type": "wait_visible",
                "key": "policy_dropdown_toggle",
                "label": "Batch Add Page Ready",
                "timeout_ms": 30000,
            }
        ],
        selectors=batch_selectors,
        values=batch_values,
        logger=logger,
        enforce_session_active=True,
    )

    await _select_company(page, batch_selectors, batch_values, logger)
    await _click_view_after_policy_selection(page, batch_selectors, logger)

    run_values = dict(batch_values)
    run_values.update(upload_paths or {})

    actions: List[Dict[str, Any]] = [
        {
            "type": "upload",
            "key": "batch_member_file_input",
            "label": "Upload Batch Member File",
            "value_key": "batch_member_file",
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "upload",
            "key": "batch_supporting_document_input",
            "label": "Upload Batch Supporting Document",
            "value_key": "batch_supporting_document",
            "required": False,
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "fill",
            "key": "batch_comments",
            "label": "Enter Batch Comments",
            "value_key": "batch_comments",
            "required": False,
            "post_wait_ms": 150,
        },
        {
            "type": "click",
            "key": "batch_validate_button",
            "label": "Click Validate",
            "wait_for_load": True,
            "wait_for_loader": True,
            "fail_on_validation_error": False,
            "timeout_ms": 60000,
            "post_wait_ms": 400,
        },
    ]

    await run_actions(
        page,
        actions=actions,
        selectors=batch_selectors,
        values=run_values,
        logger=logger,
        enforce_session_active=True,
    )

    validate_result = await _wait_for_validation_outcome(page, logger, timeout_ms=60000)

    if validate_result.validation_message:
        logger.info(f"Validate result message: {validate_result.validation_message}")

    if validate_result.invalid_members:
        logger.error(
            "Invalid members returned after validation | "
            f"Count={len(validate_result.invalid_members)}"
        )
        return validate_result

    if validate_result.validation_message:
        msg = validate_result.validation_message.lower()
        if any(token in msg for token in ("required", "error", "cannot", "failed", "invalid")):
            # Some portals return a message that contains 'required' while also
            # indicating the records were validated successfully and the user
            # must click Submit (for example: "Census records validated successfully..."
            # "Please upload above required document(s) and click on 'Submit' button...").
            # Treat messages that contain both 'validated' and 'submit' as a successful
            # validation outcome and proceed to submit rather than raising an error.
            if "validated" in msg and "submit" in msg:
                # Proceed to submit flow
                logger.info(
                    "Validation message indicates successful validation and requires Submit; proceeding to submit."
                )
            else:
                raise RuntimeError(f"Click Validate: {validate_result.validation_message}")

    reference_number = await _submit_batch_and_extract_reference(
        page=page,
        selectors=batch_selectors,
        logger=logger,
    )

    logger.info("Batch member add process completed")
    return BatchAddResult(
        validation_message=validate_result.validation_message,
        invalid_members=validate_result.invalid_members,
        reference_number=reference_number,
    )
