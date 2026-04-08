from __future__ import annotations

from typing import Any, Dict, Sequence
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError


def ensure_selector_present(selectors: Dict[str, Any], key: str, logger: logging.Logger) -> str:
    selector = (selectors or {}).get(key)
    if not selector:
        logger.error(f"Missing selector key '{key}'")
        raise ValueError(f"Missing selector key: {key}")
    return str(selector).strip()


def _normalize_selector(selector: str) -> str:
    selector = selector.strip()
    if selector.startswith("/") and not selector.startswith("xpath="):
        return f"xpath={selector}"
    return selector


def _assert_session_active(page: Page, label: str):
    try:
        current_url = (page.url or "").lower()
    except Exception:
        return

    if (
        "myaccount.sukoon.com" in current_url
        or "oauth2/v2.0/authorize" in current_url
        or "logout?post_logout_redirect_uri" in current_url
    ):
        raise RuntimeError(
            f"{label}: redirected to authentication/logout page ({page.url}). "
            "Business tab might not be selected or session expired."
        )


def _resolve_upload_path(file_path_value: str) -> str:
    raw = str(file_path_value).strip()
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    return str((Path.cwd() / expanded).resolve())


async def _wait_for_loader_disappear(
    page: Page,
    *,
    timeout_ms: int,
    loader_selector: str = "#ajax-loader-element",
):
    if page.is_closed():
        return

    locator = page.locator(loader_selector)
    deadline = asyncio.get_running_loop().time() + max(timeout_ms / 1000, 1)
    hidden_streak_start = None

    while asyncio.get_running_loop().time() < deadline:
        visible = False
        try:
            count = await locator.count()
            for index in range(count):
                if await locator.nth(index).is_visible():
                    visible = True
                    break
        except Exception:
            return

        if visible:
            hidden_streak_start = None
        else:
            now = asyncio.get_running_loop().time()
            if hidden_streak_start is None:
                hidden_streak_start = now
            elif (now - hidden_streak_start) >= 0.3:
                return

        await asyncio.sleep(0.1)

    raise RuntimeError(f"Ajax loader did not disappear within {timeout_ms}ms")


async def _extract_validation_error_message(page: Page) -> str | None:
    if page.is_closed():
        return None

    message_selectors = [
        "#message-placeholder .alert.alert-danger #message-panel",
        "#message-placeholder .alert.alert-danger",
        "div.validation-summary-errors.alert.alert-danger",
        ".alert.alert-danger #message-panel",
        ".alert.alert-danger",
    ]

    try:
        for selector in message_selectors:
            message_locator = page.locator(selector)
            count = await message_locator.count()
            for index in range(count):
                candidate = message_locator.nth(index)
                if await candidate.is_visible():
                    text = (await candidate.inner_text()).strip()
                    cleaned = " ".join(text.split())
                    if cleaned:
                        return cleaned
    except Exception:
        return None

    return None


async def _wait_after_action(
    page: Page,
    *,
    wait_for_load: bool,
    timeout_ms: int,
    post_wait_ms: int,
):
    if page.is_closed():
        return

    if wait_for_load:
        dom_timeout = min(timeout_ms, 15000)
        idle_timeout = min(timeout_ms, 10000)

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=dom_timeout)
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=idle_timeout)
        except PlaywrightTimeoutError:
            pass

    if post_wait_ms > 0:
        await asyncio.sleep(post_wait_ms / 1000)


async def wait_for_visible(
    page: Page,
    selector: str,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
):
    target = _normalize_selector(selector)
    locator = page.locator(target)
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)

    while asyncio.get_running_loop().time() < deadline:
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue

        await asyncio.sleep(0.2)

    logger.error(f"{label}: not visible within {timeout_ms}ms -> {target}")
    raise RuntimeError(f"{label}: not visible within {timeout_ms}ms -> {target}")


async def fill_field(
    page: Page,
    selector: str,
    value: Any,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    mask: bool = False,
    wait_for_load: bool = False,
    post_wait_ms: int = 200,
):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{label}: value is empty")

    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
    await locator.fill(str(value))
    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )
    logger.info(f"{label}: filled with {'***' if mask else value}")


def _parse_date(value: str):
    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_html_date(value: str) -> str | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%d")


def _date_values_match(actual_value: str, expected_value: str) -> bool:
    actual_date = _parse_date(actual_value)
    expected_date = _parse_date(expected_value)

    if actual_date is None or expected_date is None:
        return str(actual_value).strip() == str(expected_value).strip()
    return actual_date == expected_date


async def _dispatch_input_change_events(locator):
    await locator.evaluate(
        """
        (el) => {
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        """
    )


async def fill_date_field(
    page: Page,
    selector: str,
    value: Any,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    wait_for_load: bool = False,
    post_wait_ms: int = 300,
):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{label}: date value is empty")

    expected_value = str(value).strip()
    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)

    await locator.click()
    await locator.fill(expected_value)
    await _dispatch_input_change_events(locator)
    await locator.press("Tab")

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )

    actual_value = (await locator.input_value()).strip()
    if _date_values_match(actual_value, expected_value):
        logger.info(f"{label}: date committed as {actual_value}")
        return

    html_value = _to_html_date(expected_value)
    if html_value:
        await locator.evaluate(
            """
            (el, val) => {
                el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }
            """,
            html_value,
        )
        await locator.press("Tab")

        await _wait_after_action(
            page,
            wait_for_load=wait_for_load,
            timeout_ms=timeout_ms,
            post_wait_ms=post_wait_ms,
        )

        actual_value = (await locator.input_value()).strip()
        if _date_values_match(actual_value, expected_value):
            logger.info(f"{label}: date committed as {actual_value}")
            return

    await locator.evaluate(
        """
        (el, val) => {
            const parseDate = (text) => {
                const ddmmyyyy = /^([0-9]{2})[/]([0-9]{2})[/]([0-9]{4})$/;
                const yyyymmdd = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/;

                let m = text.match(ddmmyyyy);
                if (m) {
                    return new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
                }

                m = text.match(yyyymmdd);
                if (m) {
                    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
                }

                return null;
            };

            const date = parseDate(String(val).trim());
            const jq = window.jQuery || window.$;

            if (jq) {
                try {
                    const jqEl = jq(el);
                    if (typeof jqEl.datepicker === 'function') {
                        jqEl.datepicker('setDate', date || val);
                        jqEl.trigger('change');
                    }
                } catch (e) {
                    // ignore datepicker fallback errors
                }
            }

            try {
                el.removeAttribute('readonly');
            } catch (e) {
                // ignore readonly removal errors
            }

            if (date) {
                const day = String(date.getDate()).padStart(2, '0');
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const year = String(date.getFullYear());
                el.value = `${day}/${month}/${year}`;
            } else {
                el.value = val;
            }

            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('keyup', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
        """,
        expected_value,
    )
    await locator.press("Tab")

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )

    actual_value = (await locator.input_value()).strip()
    if _date_values_match(actual_value, expected_value):
        logger.info(f"{label}: date committed as {actual_value}")
        return

    raise RuntimeError(
        f"{label}: date value not committed correctly. Expected '{expected_value}', got '{actual_value}'"
    )


async def click_element(
    page: Page,
    selector: str,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    wait_for_load: bool = True,
    post_wait_ms: int = 300,
    wait_for_loader: bool = True,
    fail_on_validation_error: bool = True,
):
    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
    await locator.click()

    if wait_for_loader:
        await _wait_for_loader_disappear(page, timeout_ms=min(max(timeout_ms, 5000), 60000))

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )

    if fail_on_validation_error:
        validation_error = await _extract_validation_error_message(page)
        if validation_error:
            logger.error(f"{label}: validation error -> {validation_error}")
            raise RuntimeError(f"{label}: {validation_error}")

    logger.info(f"{label}: clicked")


async def select_field(
    page: Page,
    selector: str,
    value: Any,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    wait_for_load: bool = True,
    post_wait_ms: int = 200,
):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{label}: value is empty")

    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
    value_text = str(value).strip()

    selected = False
    for option_args in ({"value": value_text}, {"label": value_text}):
        try:
            await locator.select_option(**option_args)
            selected = True
            break
        except Exception:
            continue

    if not selected and value_text.isdigit():
        try:
            await locator.select_option(index=int(value_text))
            selected = True
        except Exception:
            selected = False

    if not selected:
        raise ValueError(f"{label}: unable to select option '{value_text}'")

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )
    logger.info(f"{label}: selected {value_text}")


async def check_field(
    page: Page,
    selector: str,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    wait_for_load: bool = True,
    post_wait_ms: int = 150,
    wait_for_loader: bool = True,
    fail_on_validation_error: bool = True,
):
    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
    await locator.check()

    if wait_for_loader:
        await _wait_for_loader_disappear(page, timeout_ms=min(max(timeout_ms, 5000), 60000))

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )

    if fail_on_validation_error:
        validation_error = await _extract_validation_error_message(page)
        if validation_error:
            logger.error(f"{label}: validation error -> {validation_error}")
            raise RuntimeError(f"{label}: {validation_error}")

    logger.info(f"{label}: checked")


async def upload_file(
    page: Page,
    selector: str,
    file_path_value: Any,
    label: str,
    logger: logging.Logger,
    timeout_ms: int = 20000,
    wait_for_load: bool = True,
    post_wait_ms: int = 200,
    wait_for_loader: bool = True,
    fail_on_validation_error: bool = True,
):
    if file_path_value is None or str(file_path_value).strip() == "":
        raise ValueError(f"{label}: file path is empty")

    resolved_path = _resolve_upload_path(str(file_path_value))
    if not Path(resolved_path).exists():
        raise FileNotFoundError(f"{label}: file not found at {resolved_path}")

    locator = await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
    await locator.set_input_files(resolved_path)

    if wait_for_loader:
        await _wait_for_loader_disappear(page, timeout_ms=min(max(timeout_ms, 5000), 60000))

    await _wait_after_action(
        page,
        wait_for_load=wait_for_load,
        timeout_ms=timeout_ms,
        post_wait_ms=post_wait_ms,
    )

    if fail_on_validation_error:
        validation_error = await _extract_validation_error_message(page)
        if validation_error:
            logger.error(f"{label}: validation error -> {validation_error}")
            raise RuntimeError(f"{label}: {validation_error}")

    logger.info(f"{label}: uploaded file {resolved_path}")


async def run_actions(
    page: Page,
    *,
    actions: Sequence[Dict[str, Any]],
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
    default_timeout_ms: int = 20000,
    enforce_session_active: bool = False,
):
    """
    Execute declarative actions using locator keys and value keys.

    Action examples:
    - {"type": "click", "key": "sign_in_button", "label": "Sign In"}
    - {"type": "fill", "key": "email_address", "value_key": "username", "label": "Email"}
    - {"type": "fill_date", "key": "date_of_birth", "value_key": "date_of_birth", "label": "DOB"}
    - {"type": "select", "key": "gender", "value": "Male", "label": "Gender"}
    - {"type": "check", "key": "principal_radio", "label": "Principal"}
    - {"type": "upload", "key": "supporting_document", "value_key": "supporting_file_1", "label": "Upload File"}
    - {"type": "wait_visible", "key": "policy_servicing", "label": "Dashboard Ready"}
    """
    for index, action in enumerate(actions, start=1):
        action_type = str(action.get("type", "")).lower().strip()
        label = action.get("label") or f"Action {index}"
        required = bool(action.get("required", True))
        timeout_ms = int(action.get("timeout_ms", default_timeout_ms))
        wait_for_load = bool(action.get("wait_for_load")) if "wait_for_load" in action else action_type in {"click", "select", "check"}
        post_wait_ms = int(action.get("post_wait_ms", 300 if wait_for_load else 200))
        wait_for_loader = bool(action.get("wait_for_loader", action_type in {"click", "check", "upload"}))
        fail_on_validation_error = bool(action.get("fail_on_validation_error", action_type in {"click", "check", "upload"}))

        try:
            if enforce_session_active:
                _assert_session_active(page, label)

            if action_type in {"fill", "fill_date", "click", "wait_visible", "select", "check", "upload"}:
                key = str(action.get("key", "")).strip()
                if not key:
                    raise ValueError(f"{label}: key is required")
                selector = ensure_selector_present(selectors, key, logger)

            if action_type == "fill":
                if "value" in action:
                    value = action["value"]
                else:
                    value_key = str(action.get("value_key", "")).strip()
                    if not value_key:
                        raise ValueError(f"{label}: value or value_key is required")
                    value = values.get(value_key)
                mask = bool(action.get("mask", False))
                await fill_field(
                    page,
                    selector,
                    value,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    mask=mask,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                )

            elif action_type == "fill_date":
                if "value" in action:
                    value = action["value"]
                else:
                    value_key = str(action.get("value_key", "")).strip()
                    if not value_key:
                        raise ValueError(f"{label}: value or value_key is required")
                    value = values.get(value_key)

                await fill_date_field(
                    page,
                    selector,
                    value,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                )

            elif action_type == "click":
                await click_element(
                    page,
                    selector,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                    wait_for_loader=wait_for_loader,
                    fail_on_validation_error=fail_on_validation_error,
                )

                next_key = str(action.get("next_key", "")).strip()
                if next_key:
                    next_selector = ensure_selector_present(selectors, next_key, logger)
                    next_label = str(action.get("next_label") or f"{label} Next Element")
                    next_timeout_ms = int(action.get("next_timeout_ms", timeout_ms))
                    await wait_for_visible(page, next_selector, next_label, logger, timeout_ms=next_timeout_ms)
                    logger.info(f"{next_label}: visible")

            elif action_type == "select":
                if "value" in action:
                    value = action["value"]
                else:
                    value_key = str(action.get("value_key", "")).strip()
                    if not value_key:
                        raise ValueError(f"{label}: value or value_key is required")
                    value = values.get(value_key)

                await select_field(
                    page,
                    selector,
                    value,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                )

            elif action_type == "check":
                await check_field(
                    page,
                    selector,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                    wait_for_loader=wait_for_loader,
                    fail_on_validation_error=fail_on_validation_error,
                )

            elif action_type == "upload":
                if "value" in action:
                    value = action["value"]
                else:
                    value_key = str(action.get("value_key", "")).strip()
                    if not value_key:
                        raise ValueError(f"{label}: value or value_key is required")
                    value = values.get(value_key)

                await upload_file(
                    page,
                    selector,
                    value,
                    label,
                    logger,
                    timeout_ms=timeout_ms,
                    wait_for_load=wait_for_load,
                    post_wait_ms=post_wait_ms,
                    wait_for_loader=wait_for_loader,
                    fail_on_validation_error=fail_on_validation_error,
                )

            elif action_type == "wait_visible":
                await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)
                logger.info(f"{label}: visible")

            else:
                raise ValueError(f"{label}: unsupported action type '{action_type}'")

            if enforce_session_active:
                _assert_session_active(page, label)

        except Exception as exc:
            if required:
                logger.error(f"{label}: failed -> {exc}")
                raise
            logger.warning(f"{label}: optional step skipped -> {exc}")
