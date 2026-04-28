from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.utils.support_functions import run_actions


async def login(
    page: Page,
    login_values: Dict[str, Any],
    login_selectors: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS login process started")

    await run_actions(
        page,
        actions=[
            {
                "type": "fill",
                "key": "username",
                "label": "NAS Username",
                "value_key": "username",
            },
            {
                "type": "fill",
                "key": "password",
                "label": "NAS Password",
                "value_key": "password",
                "mask": True,
            },
            {
                "type": "click",
                "key": "login_button",
                "label": "NAS Login",
                "timeout_ms": 30000,
                "wait_for_load": True,
                "wait_for_loader": False,
                "fail_on_validation_error": False,
            },
        ],
        selectors=login_selectors,
        values=login_values,
        logger=logger,
    )

    try:
        await page.wait_for_url(lambda url: "/Accounts/login" not in str(url), timeout=60000)
        logger.info(f"NAS login redirect detected: {page.url}")
        return
    except PlaywrightTimeoutError:
        logger.warning("NAS login URL did not change within timeout; checking login form visibility")

    username_selector = str(login_selectors.get("username") or "#Username")
    try:
        if await page.locator(username_selector).first.is_visible():
            raise RuntimeError("NAS login form is still visible after login click")
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("NAS login confirmation timed out") from exc

    logger.info("NAS login form is no longer visible")
