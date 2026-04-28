from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.utils.support_functions import ensure_selector_present


DEFAULT_ACCORDION_TEXT = "Liva Insurance B.S.C. (C) - LIVA - Nas"


async def select_company_accordion(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS accordion page started")

    accordion_selector = ensure_selector_present(selectors, "accordion_header", logger)
    accordion_text = str(
        values.get("accordion_text")
        or values.get("company_name")
        or DEFAULT_ACCORDION_TEXT
    ).strip()
    locator = page.locator(accordion_selector).filter(has_text=accordion_text).first

    await locator.wait_for(state="visible", timeout=60000)
    await locator.click()

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    logger.info(f"NAS company accordion selected: {accordion_text}")
