from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.portals.nas.add_process.member.master_contract_page import (
    _find_contract_card,
    _normalize_text,
)
from src.utils.support_functions import ensure_selector_present


async def select_sub_policy_add_member(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS sub-policy page started")

    sub_policy_contract_name = _normalize_text(
        values.get("sub_policy_contract_name") or values.get("contract_name")
    )
    if not sub_policy_contract_name:
        raise ValueError("NAS sub_policy_contract_name is required to select the sub-policy card")

    sub_policy_card_selector = ensure_selector_present(selectors, "sub_policy_card", logger)
    sub_policy_contract_link_selector = ensure_selector_present(
        selectors,
        "sub_policy_contract_link",
        logger,
    )
    sub_policy_add_member_selector = ensure_selector_present(
        selectors,
        "sub_policy_add_member_button",
        logger,
    )

    sub_policy_card = await _find_contract_card(
        page,
        card_selector=sub_policy_card_selector,
        contract_link_selector=sub_policy_contract_link_selector,
        contract_name=sub_policy_contract_name,
        logger=logger,
    )
    if sub_policy_card is None:
        raise RuntimeError(
            f"NAS sub-policy card not found for ContractName: {sub_policy_contract_name}"
        )

    add_member_button = sub_policy_card.locator(sub_policy_add_member_selector).first
    await add_member_button.wait_for(state="visible", timeout=30000)
    await add_member_button.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    logger.info(
        "NAS sub-policy Add Member selected for ContractName: "
        f"{sub_policy_contract_name}"
    )
    