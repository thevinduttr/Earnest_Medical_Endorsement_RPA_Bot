from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page

from src.utils.support_functions import click_element, ensure_selector_present, run_actions


async def _ensure_business_tab_selected(page: Page, login_selectors: Dict[str, Any], logger: logging.Logger):
	active_selector = str(login_selectors.get("business_tab_active") or "label.currentTab").strip()
	active_locator = page.locator(active_selector).filter(has_text="Business").first

	try:
		if await active_locator.is_visible():
			logger.info("Business tab already active via currentTab label")
			return
	except Exception:
		pass

	logger.info("Business tab is not active. Clicking Business button")
	business_tab_selector = ensure_selector_present(login_selectors, "business_tab", logger)
	await click_element(
		page,
		business_tab_selector,
		"Switch to Business Tab",
		logger,
		timeout_ms=15000,
		wait_for_load=True,
		post_wait_ms=500,
	)

	try:
		await active_locator.wait_for(state="visible", timeout=10000)
		logger.info("Business tab activated")
	except Exception as exc:
		logger.warning(f"Business tab active label not confirmed after click: {exc}")


async def login(
	page: Page,
	login_values: Dict[str, Any],
	login_selectors: Dict[str, Any],
	dashboard_selectors: Dict[str, Any],
	logger: logging.Logger,
):
	"""
	Sukoon login flow (YAML selectors + JSON values).

	This keeps the same declarative action pattern used in the sample project,
	so later you can switch JSON values to DB values without changing flow logic.
	"""
	logger.info("Sukoon login process started")

	open_login_actions: List[Dict[str, Any]] = [
		{"type": "click", "key": "sign_in_button", "label": "Open Sign In"},
	]

	await run_actions(
		page,
		actions=open_login_actions,
		selectors=login_selectors,
		values=login_values,
		logger=logger,
	)

	await _ensure_business_tab_selected(page, login_selectors, logger)

	credential_actions: List[Dict[str, Any]] = [
		{
			"type": "fill",
			"key": "email_address",
			"label": "Email Address",
			"value_key": "username",
		},
		{
			"type": "fill",
			"key": "password",
			"label": "Password",
			"value_key": "password",
			"mask": True,
		},
		{"type": "click", "key": "login_button", "label": "Submit Login"},
	]

	await run_actions(
		page,
		actions=credential_actions,
		selectors=login_selectors,
		values=login_values,
		logger=logger,
	)

	# URL check is best-effort; dashboard element check remains the source of truth.
	try:
		await page.wait_for_url("**/PolicyServicing/Dashboard/Overview", timeout=60000)
		logger.info("Login redirect URL detected")
	except Exception as exc:
		logger.warning(f"Dashboard URL wait skipped/timeout: {exc}")

	await run_actions(
		page,
		actions=[
			{
				"type": "wait_visible",
				"key": "policy_servicing",
				"label": "Dashboard Ready",
				"timeout_ms": 60000,
			}
		],
		selectors=dashboard_selectors,
		values=login_values,
		logger=logger,
	)

	logger.info("Sukoon login process completed successfully")
