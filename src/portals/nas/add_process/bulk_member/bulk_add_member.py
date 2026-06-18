from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from src.portals.nas.add_process.member.master_contract_page import (
    DEFAULT_ACCORDION_TEXT,
    _normalize_text,
)
from src.utils.support_functions import ensure_selector_present


async def _wait_after_click(page: Page, timeout_ms: int = 15000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    await asyncio.sleep(0.5)


async def _first_visible_enabled(locator: Locator) -> Locator | None:
    count = await locator.count()
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible() and await candidate.is_enabled():
                return candidate
        except Exception:
            continue
    return None


async def _select_bulk_policy(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    payer_selector = ensure_selector_present(selectors, "payer_accordion", logger)
    payer_name = _normalize_text(values.get("accordion_text")) or DEFAULT_ACCORDION_TEXT
    payer = page.locator(payer_selector).filter(has_text=payer_name).first
    await payer.wait_for(state="visible", timeout=60000)
    await payer.click()
    await _wait_after_click(page)
    logger.info("NAS bulk payer selected: %s", payer_name)

    policy_filter_selector = ensure_selector_present(selectors, "policy_filter", logger)
    policy_filter = page.locator(policy_filter_selector).first
    filter_value = _normalize_text(values.get("company_name"))
    try:
        if filter_value and await policy_filter.is_visible():
            await policy_filter.fill(filter_value)
            await asyncio.sleep(0.5)
            logger.info("NAS bulk policy filter filled: %s", filter_value)
    except Exception:
        logger.warning("NAS bulk policy filter was not available; continuing with card matching")

    card_selector = ensure_selector_present(selectors, "policy_card", logger)
    contract_link_selector = ensure_selector_present(selectors, "policy_contract_link", logger)
    upload_button_selector = ensure_selector_present(selectors, "upload_members_button", logger)
    contract_name = _normalize_text(values.get("contract_name"))

    cards = page.locator(card_selector)
    await cards.first.wait_for(state="visible", timeout=60000)
    matched_cards: list[tuple[int, Locator]] = []
    for index in range(await cards.count()):
        card = cards.nth(index)
        upload_button = await _first_visible_enabled(card.locator(upload_button_selector))
        if upload_button is None:
            continue

        card_text = _normalize_text(await card.inner_text())
        if contract_name:
            link_texts = [
                _normalize_text(text)
                for text in await card.locator(contract_link_selector).all_inner_texts()
            ]
            if contract_name not in card_text and contract_name not in link_texts:
                continue

        matched_cards.append((len(card_text), upload_button))

    if matched_cards:
        _, upload_button = min(matched_cards, key=lambda item: item[0])
        await upload_button.click()
        await _wait_after_click(page)
        logger.info(
            "NAS bulk upload policy selected%s",
            f": {contract_name}" if contract_name else "",
        )
        return

    visible_buttons = page.locator(upload_button_selector)
    visible_matches: list[Locator] = []
    for index in range(await visible_buttons.count()):
        candidate = visible_buttons.nth(index)
        if await candidate.is_visible() and await candidate.is_enabled():
            visible_matches.append(candidate)

    if len(visible_matches) == 1:
        await visible_matches[0].click()
        await _wait_after_click(page)
        logger.warning("NAS bulk policy selected using the only visible Upload Members button")
        return

    raise RuntimeError(
        "NAS bulk Upload Members button could not be uniquely matched"
        + (f" for ContractName: {contract_name}" if contract_name else "")
    )


async def _upload_bulk_excel(
    page: Page,
    selectors: Dict[str, Any],
    excel_path: str,
    logger: logging.Logger,
) -> None:
    resolved_path = Path(excel_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(
            "NAS bulk member Excel file was not found. "
            f"Expected: {resolved_path}. Set NAS_BULK_MEMBER_FILE to override this path."
        )

    file_input_selector = ensure_selector_present(selectors, "excel_file_input", logger)
    save_button_selector = ensure_selector_present(selectors, "import_save_button", logger)
    member_links_selector = ensure_selector_present(selectors, "member_links", logger)

    file_input = page.locator(file_input_selector).first
    await file_input.wait_for(state="attached", timeout=60000)
    await file_input.set_input_files(str(resolved_path))
    logger.info("NAS bulk member Excel uploaded: %s", resolved_path)

    save_button = page.locator(save_button_selector).first
    await save_button.wait_for(state="visible", timeout=30000)
    await save_button.click()
    await _wait_after_click(page, timeout_ms=30000)

    await page.locator(member_links_selector).first.wait_for(state="visible", timeout=60000)
    logger.info("NAS bulk import saved; member timeline page is ready")


async def _submit_member_timeline(
    page: Page,
    selectors: Dict[str, Any],
    member_id: str,
    member_name: str,
    logger: logging.Logger,
    max_steps: int = 12,
) -> None:
    next_selector = ensure_selector_present(selectors, "timeline_next_button", logger)
    submit_selector = ensure_selector_present(selectors, "timeline_submit_button", logger)

    member_link = page.locator(f"#{member_id}")
    await member_link.wait_for(state="visible", timeout=30000)
    await member_link.click()
    await _wait_after_click(page)
    logger.info("NAS bulk member opened: %s", member_name)

    for step_number in range(1, max_steps + 1):
        submit_button = await _first_visible_enabled(page.locator(submit_selector))
        if submit_button is not None:
            await submit_button.click()
            await _wait_after_click(page, timeout_ms=30000)
            logger.info(
                "NAS bulk member submitted: %s | TimelineSteps=%s",
                member_name,
                step_number - 1,
            )
            return

        next_button = await _first_visible_enabled(page.locator(next_selector))
        if next_button is None:
            raise RuntimeError(
                f"NAS bulk member timeline stalled for '{member_name}': "
                "neither Next nor Submit is visible and enabled"
            )

        await next_button.click()
        await _wait_after_click(page, timeout_ms=30000)
        logger.info(
            "NAS bulk member timeline advanced: %s | Step=%s",
            member_name,
            step_number,
        )

    raise RuntimeError(
        f"NAS bulk member Submit did not appear within {max_steps} timeline steps "
        f"for '{member_name}'"
    )


async def _submit_all_imported_members(
    page: Page,
    selectors: Dict[str, Any],
    logger: logging.Logger,
) -> int:
    member_links_selector = ensure_selector_present(selectors, "member_links", logger)
    member_links = page.locator(member_links_selector)
    await member_links.first.wait_for(state="visible", timeout=60000)

    members: list[tuple[str, str]] = []
    for index in range(await member_links.count()):
        link = member_links.nth(index)
        member_id = str(await link.get_attribute("id") or "").strip()
        member_name = _normalize_text(await link.inner_text()) or f"Member {index + 1}"
        if member_id:
            members.append((member_id, member_name))

    if not members:
        raise RuntimeError("NAS bulk import displayed no member records")

    logger.info("NAS bulk members discovered: %s", len(members))
    for member_id, member_name in members:
        await _submit_member_timeline(
            page=page,
            selectors=selectors,
            member_id=member_id,
            member_name=member_name,
            logger=logger,
        )

    logger.info("NAS bulk member timelines submitted: %s", len(members))
    return len(members)


async def run_bulk_add_member(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> int:
    logger.info("NAS bulk add-member process started")
    excel_path = str(values.get("batch_member_file") or "").strip()
    if not excel_path:
        raise ValueError("NAS batch_member_file is required for bulk member upload")

    await _select_bulk_policy(page, selectors, values, logger)
    await _upload_bulk_excel(page, selectors, excel_path, logger)
    submitted_count = await _submit_all_imported_members(page, selectors, logger)
    logger.info("NAS bulk add-member process completed | Members=%s", submitted_count)
    return submitted_count
