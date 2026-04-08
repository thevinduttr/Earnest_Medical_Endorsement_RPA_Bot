from typing import Dict, Any, List
import pandas as pd
import logging
from pathlib import Path
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step, notify_process_error
from src.utils.load_data import load_yaml_file
from src.utils.error_handler import ValidationError

async def login(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
    request_id: str | None = None,
):
    """
    Declarative, loop-driven login:
      - Uses one YAML group (passed as selectors_group) coming from locators/main/login_page.yml -> section "login"
      - Values come from df.iloc[0] (username/password)
      - After login, waits until dashboard page element is visible
        (from locators/main/dashboard_page.yml -> dashboard.xpath)
    """
    selectors = selectors_group or {}
    logger.info("Login started")

    # Define pipeline of actions
    actions: List[Dict[str, Any]] = [
        {"type": "fill",   "key": "username", "label": "Username", "value_col": "Username", "mask": False},
        {"type": "fill",   "key": "password", "label": "Password", "value_col": "Password", "mask": True},
        {"type": "click",  "key": "submit",   "label": "Submit"},
    ]

    # Optional success checks based on what exists in login selectors
    if selectors.get("success_selector"):
        actions.append({"type": "wait_visible", "key": "success_selector", "label": "Success marker"})
    elif selectors.get("success_text"):
        actions.append({"type": "wait_text", "text_from": "success_text", "label": "Success text"})

    # Run main login actions
    await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger)
    logger.info("Login steps completed, checking for password-expired alert...")

    # Check if the portal blocks login due to an expired password.
    password_expired_selector = selectors.get(
        "password_expired_selector",
        "div.validation-summary-errors.alert.alert-danger",
    )
    password_expired_text = str(
        selectors.get(
            "password_expired_text",
            "Your password has expired. Please reset it to continue.",
        )
    ).strip()

    try:
        expired_loc = page.locator(password_expired_selector).first
        if await expired_loc.count() > 0:
            try:
                await expired_loc.wait_for(state="visible", timeout=2000)
            except Exception:
                pass

            if await expired_loc.is_visible():
                expired_message = (await expired_loc.inner_text() or "").strip()
                if password_expired_text.lower() in expired_message.lower():
                    composed = (
                        "CRM login blocked: password expired. "
                        f"Portal message: {expired_message}"
                    )
                    logger.error(composed)

                    await notify_process_error(
                        page=page,
                        logger=logger,
                        run_id=run_id,
                        subject=(
                            f"[{run_id}] CRM login failed - password expired"
                            if run_id
                            else "CRM login failed - password expired"
                        ),
                        body=composed,
                        shot_name="login_password_expired.png",
                        flag_validation=True,
                        request_id=request_id,
                    )
                    raise ValidationError(composed)
    except ValidationError:
        raise
    except Exception as e:
        logger.debug(f"Password-expired check failed or not applicable: {e}")

    logger.info("Login steps completed, checking for optional 'Start New Session' button...")

    # --- NEW: If Start New Session button appears after submit, click it (only when visible) ---
    start_btn = selectors.get("start_new_session_button")
    if start_btn:
        # Playwright accepts "xpath=..." prefix for XPath selectors; adapt if raw XPath provided
        selector_str = start_btn if start_btn.strip().startswith(("css=", "xpath=")) else (f"xpath={start_btn}" if start_btn.strip().startswith("//") else start_btn)
        try:
            # short timeout so we don't block if it never appears
            await page.wait_for_selector(selector_str, timeout=3000)
            loc = page.locator(selector_str)
            if await loc.is_visible():
                logger.info("Optional Start New Session button is visible — clicking it")
                await loc.click()
            else:
                logger.debug("Start New Session selector present but not visible; skipping click")
        except Exception:
            # likely a timeout or not present — continue silently
            logger.debug("Start New Session button not found within short timeout; continuing")

    logger.info("Waiting for dashboard page...")

    # --- NEW: Wait for dashboard element visible (next page ready) ---
    dashboard_path = Path("locators/main/dashboard_page.yml")
    dashboard_yml = load_yaml_file(dashboard_path)

    # Expect structure: dashboard: { xpath: "..." }
    dashboard_cfg = dashboard_yml.get("dashboard", {})
    dashboard_xpath = dashboard_cfg.get("xpath")

    if not dashboard_xpath:
        logger.error(f"Dashboard locator not found in {dashboard_path}")
        raise ValueError("Dashboard locator missing; cannot verify post-login dashboard")

    # Wait for the next-step element (dashboard) to appear
    await wait_for_next_step(
        page,
        logger=logger,
        label="Dashboard page ready",
        selector=dashboard_xpath,
        timeout_ms=45000,  # optional: custom timeout for dashboard load
    )

    logger.info("Login completed successfully; dashboard visible.")
