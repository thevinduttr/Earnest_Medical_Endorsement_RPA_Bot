from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.utils.support_functions import ensure_selector_present


DEFAULT_ACCORDION_TEXT = "Liva Insurance B.S.C. (C) - LIVA - Nas"


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_contract_title(value: Any) -> str:
    text = _normalize_text(value)
    for prefix in ("MContract Name :", "CONTRACT NAME :"):
        if text.upper().startswith(prefix.upper()):
            text = text[len(prefix):].strip()
            break
    return text


async def _find_contract_card(
    page: Page,
    *,
    card_selector: str,
    contract_link_selector: str,
    contract_name: str,
    logger: logging.Logger,
):
    cards = page.locator(card_selector)
    await cards.first.wait_for(state="visible", timeout=60000)

    card_count = await cards.count()
    for index in range(card_count):
        card = cards.nth(index)
        contract_link = card.locator(contract_link_selector).first
        try:
            title_text = _normalize_contract_title(await contract_link.inner_text())
            title_attr = _normalize_contract_title(await contract_link.get_attribute("title"))
        except Exception:
            continue

        if contract_name in {title_text, title_attr}:
            logger.info(f"NAS contract card matched at index {index}: {contract_name}")
            return card

    return None


async def select_company_accordion(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS accordion page started")

    accordion_selector = ensure_selector_present(selectors, "accordion_header", logger)
    accordion_text = DEFAULT_ACCORDION_TEXT
    locator = page.locator(accordion_selector).filter(has_text=accordion_text).first

    await locator.wait_for(state="visible", timeout=60000)
    await locator.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    logger.info(f"NAS company accordion selected: {accordion_text}")

    contract_name = _normalize_text(values.get("contract_name"))
    if not contract_name:
        raise ValueError("NAS ContractName is required to select the policy card")

    policy_card_selector = ensure_selector_present(selectors, "policy_card", logger)
    contract_link_selector = ensure_selector_present(selectors, "policy_contract_link", logger)
    select_button_selector = ensure_selector_present(selectors, "select_policy_button", logger)

    matched_card = await _find_contract_card(
        page,
        card_selector=policy_card_selector,
        contract_link_selector=contract_link_selector,
        contract_name=contract_name,
        logger=logger,
    )
    if matched_card is None:
        raise RuntimeError(f"NAS policy card not found for ContractName: {contract_name}")

    select_button = matched_card.locator(select_button_selector).first
    await select_button.wait_for(state="visible", timeout=30000)
    await select_button.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    logger.info(f"NAS policy selected for ContractName: {contract_name}")