from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.services.mail_service.outlook_mail_service import find_latest_nas_otp
from src.utils.mail_config import MailConfig
from src.utils.support_functions import run_actions


async def _is_mfa_page_visible(
    page: Page,
    login_selectors: Dict[str, Any],
    logger: logging.Logger,
    timeout_ms: int = 15000,
) -> bool:
    selector = str(login_selectors.get("mfa_heading") or 'h1:has-text("Verify your identity")')
    try:
        await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
        logger.info("NAS MFA page detected")
        return True
    except PlaywrightTimeoutError:
        return False


async def _wait_for_nas_login_complete(page: Page, logger: logging.Logger) -> bool:
    try:
        await page.wait_for_url(
            lambda url: "/Accounts/login" not in str(url) and "/Accounts/MFALogin" not in str(url),
            timeout=60000,
        )
        logger.info(f"NAS login redirect detected: {page.url}")
        return True
    except PlaywrightTimeoutError:
        logger.warning("NAS login URL did not reach portal within timeout; checking login form visibility")
        return False


async def _fill_otp_with_typing(
    page: Page,
    login_selectors: Dict[str, Any],
    otp_code: str,
    logger: logging.Logger,
) -> bool:
    otp_inputs_selector = str(login_selectors.get("otp_inputs") or ".otp-field input.inp")
    hidden_code_selector = str(
        login_selectors.get("otp_hidden_code")
        or 'form[action="/Accounts/MFALogin"] input#Code'
    )
    continue_button_selector = str(
        login_selectors.get("otp_continue_button")
        or 'form[action="/Accounts/MFALogin"] button[type="submit"]:has-text("Continue")'
    )

    inputs = page.locator(otp_inputs_selector)
    if await inputs.count() < len(otp_code):
        logger.warning("NAS OTP inputs were not fully available for typing")
        return False

    await inputs.first.click()
    await inputs.first.type(otp_code, delay=80)

    try:
        await page.wait_for_function(
            """
            ([hiddenSelector, expectedCode]) => {
                const hidden = document.querySelector(hiddenSelector);
                return hidden && hidden.value === expectedCode;
            }
            """,
            arg=[hidden_code_selector, otp_code],
            timeout=5000,
        )
        continue_button = page.locator(continue_button_selector).first
        await continue_button.wait_for(state="visible", timeout=5000)
        if not await continue_button.is_enabled():
            logger.warning("NAS OTP Continue button was still disabled after typing")
            return False
        logger.info("NAS OTP entered using page typing behavior")
        return True
    except PlaywrightTimeoutError:
        logger.warning("NAS OTP typing did not populate hidden code/enabled button; using fallback")
        return False


async def _fill_otp_with_dom_fallback(
    page: Page,
    login_selectors: Dict[str, Any],
    otp_code: str,
    logger: logging.Logger,
) -> None:
    otp_inputs_selector = str(login_selectors.get("otp_inputs") or ".otp-field input.inp")
    hidden_code_selector = str(
        login_selectors.get("otp_hidden_code")
        or 'form[action="/Accounts/MFALogin"] input#Code'
    )
    continue_button_selector = str(
        login_selectors.get("otp_continue_button")
        or 'form[action="/Accounts/MFALogin"] button[type="submit"]:has-text("Continue")'
    )

    await page.evaluate(
        """
        ([inputSelector, hiddenSelector, code]) => {
            const dispatch = (el) => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            };

            const inputs = Array.from(document.querySelectorAll(inputSelector));
            code.split('').forEach((digit, index) => {
                const input = inputs[index];
                if (!input) return;
                input.removeAttribute('disabled');
                input.value = digit;
                dispatch(input);
            });

            const hidden = document.querySelector(hiddenSelector);
            if (hidden) {
                hidden.value = code;
                dispatch(hidden);
            }
        }
        """,
        [otp_inputs_selector, hidden_code_selector, otp_code],
    )
    await page.locator(continue_button_selector).first.evaluate(
        """
        (button) => {
            button.removeAttribute('disabled');
            button.disabled = false;
        }
        """
    )
    logger.info("NAS OTP entered using DOM fallback")


async def _submit_mfa_code(
    page: Page,
    login_selectors: Dict[str, Any],
    otp_code: str,
    logger: logging.Logger,
) -> None:
    continue_button_selector = str(
        login_selectors.get("otp_continue_button")
        or 'form[action="/Accounts/MFALogin"] button[type="submit"]:has-text("Continue")'
    )

    if not await _fill_otp_with_typing(page, login_selectors, otp_code, logger):
        await _fill_otp_with_dom_fallback(page, login_selectors, otp_code, logger)

    await page.locator(continue_button_selector).first.click()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    logger.info("NAS MFA Continue clicked")


async def _find_otp_for_current_login(
    mail_config: MailConfig,
    login_submit_time: datetime,
    logger: logging.Logger,
) -> str:
    logger.info(
        "Waiting for NAS OTP email for the current login session. TimeoutSeconds=%s",
        mail_config.otp_poll_timeout_seconds,
    )
    try:
        return await asyncio.to_thread(
            find_latest_nas_otp,
            mail_config,
            received_after=login_submit_time,
            timeout_seconds=mail_config.otp_poll_timeout_seconds,
            logger=logger,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            "NAS OTP was not received for the current login session. "
            "Login will stop without clicking Resend so the browser can close "
            "and the existing retry process can start a fresh login."
        ) from exc


async def _handle_mfa_if_present(
    page: Page,
    login_selectors: Dict[str, Any],
    login_submit_time: datetime,
    logger: logging.Logger,
) -> bool:
    if not await _is_mfa_page_visible(page, login_selectors, logger):
        return False

    mail_config = MailConfig.load()
    otp_code = await _find_otp_for_current_login(
        mail_config,
        login_submit_time,
        logger,
    )
    await _submit_mfa_code(page, login_selectors, otp_code, logger)
    if not await _wait_for_nas_login_complete(page, logger):
        raise RuntimeError("NAS MFA submitted but portal redirect was not detected")
    return True


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
        ],
        selectors=login_selectors,
        values=login_values,
        logger=logger,
    )

    login_submit_time = datetime.now(timezone.utc)
    await run_actions(
        page,
        actions=[
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

    if await _handle_mfa_if_present(page, login_selectors, login_submit_time, logger):
        return

    try:
        login_complete = await _wait_for_nas_login_complete(page, logger)
        if login_complete and "/Accounts/login" not in page.url and "/Accounts/MFALogin" not in page.url:
            return
        if await _handle_mfa_if_present(page, login_selectors, login_submit_time, logger):
            return
        raise PlaywrightTimeoutError("NAS login did not redirect to portal")
    except PlaywrightTimeoutError:
        logger.warning("NAS login URL did not change within timeout; checking login form visibility")

    if await _handle_mfa_if_present(page, login_selectors, login_submit_time, logger):
        return

    username_selector = str(login_selectors.get("username") or "#Username")
    try:
        if await page.locator(username_selector).first.is_visible():
            raise RuntimeError("NAS login form is still visible after login click")
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("NAS login confirmation timed out") from exc

    logger.info("NAS login form is no longer visible")

