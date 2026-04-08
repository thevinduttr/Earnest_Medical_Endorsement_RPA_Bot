from __future__ import annotations
import asyncio
from typing import Any, Dict, Optional, Union, Sequence , List
import logging
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout
from . import send_email as send_email_helper
from .error_handler import ValidationError
import time
from pathlib import Path
import base64
from typing import Sequence

# ---------- Core selector helpers ----------

def ensure_selector_present(selectors: Dict[str, Any], key: str, logger: logging.Logger) -> str:
    sel = (selectors or {}).get(key)
    if not sel:
        logger.error(f"Missing required selector '{key}' in YAML.")
        raise ValueError(f"Missing required selector: {key}")
    return str(sel)

async def wait_for_visible(page: Page, selector: str, field_label: str, logger: logging.Logger, timeout_ms: int = 20000):
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout_ms)
        # ensure the element is scrolled into view so the action is visible to the operator
        try:
            await loc.scroll_into_view_if_needed()
            await asyncio.sleep(0.05)
            logger.debug(f"{field_label}: scrolled into view @ {selector}")
        except Exception:
            # non-fatal if scrolling fails
            logger.debug(f"{field_label}: scroll_into_view_if_needed failed for {selector}")
        logger.debug(f"{field_label}: element visible @ {selector}")
        return loc
    except PlaywrightTimeout:
        logger.error(f"{field_label}: selector not visible within {timeout_ms}ms -> {selector}")
        raise
    except Exception as e:
        logger.error(f"{field_label}: selector error -> {selector} | {e}")
        raise

async def wait_for_text(page: Page, text: str, field_label: str, logger: logging.Logger, timeout_ms: int = 20000):
    try:
        await page.get_by_text(str(text), exact=False).wait_for(state="visible", timeout=timeout_ms)
        logger.info(f"{field_label}: text visible -> {text}")
    except PlaywrightTimeout:
        logger.error(f"{field_label}: text not visible within {timeout_ms}ms -> {text}")
        raise
    except Exception as e:
        logger.error(f"{field_label}: wait_text error -> {text} | {e}")
        raise

# ---------- NEW: next-step waiter (page-agnostic) ----------

async def wait_for_next_step(
    page: Page,
    *,
    logger: logging.Logger,
    label: str = "Next step",
    selector: Optional[str] = None,
    selector_key: Optional[str] = None,
    selectors: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 30000,
):
    """
    Wait for the next-step element to prove the process/page advanced.
    Call this after finishing a step (e.g., after clicking Submit) when you need to ensure
    the subsequent page/section is ready.

    Usage:
      await wait_for_next_step(page, logger=logger, selector="//div[@id='dashboard']")
      await wait_for_next_step(page, logger=logger, selector_key="dashboard_card", selectors=selectors)
      await wait_for_next_step(page, logger=logger, label="Post-login ready", selector_key="success_selector", selectors=selectors, timeout_ms=45000)
    """
    if selector_key:
        if selectors is None:
            logger.error(f"{label}: selector_key='{selector_key}' provided but 'selectors' dict is None.")
            raise ValueError(f"{label}: selectors dict required when using selector_key")
        target = ensure_selector_present(selectors, selector_key, logger)
    else:
        target = (selector or "").strip()

    if not target:
        logger.error(f"{label}: no selector or selector_key provided.")
        raise ValueError(f"{label}: missing next-step selector")

    await wait_for_visible(page, target, label, logger, timeout_ms=timeout_ms)
    
    await asyncio.sleep(0.3)
    
    logger.info(f"{label}: next-step element visible (completed)")

# ---------- NEW: wait until element is NOT visible (hidden/detached) ----------
async def wait_for_not_visible(
    page: Page,
    *,
    logger: logging.Logger,
    label: str = "Wait hidden",
    selector: Optional[str] = None,
    selector_key: Optional[str] = None,
    selectors: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 20000,
):
    """
    Wait until the target element becomes not visible (hidden or detached).
    Useful for waiting for loading spinners or overlays to disappear.

    Usage:
      await wait_for_not_visible(page, logger=logger, selector="//div[@id='spinner']", timeout_ms=30000)
      await wait_for_not_visible(page, logger=logger, selector_key="loading_spinner", selectors=selectors)
      await wait_for_not_visible(page, logger=logger, label="Wait spinner gone", selector_key="spinner", selectors=selectors)
    """
    if selector_key:
        if selectors is None:
            logger.error(f"{label}: selector_key='{selector_key}' provided but 'selectors' dict is None.")
            raise ValueError(f"{label}: selectors dict required when using selector_key")
        target = ensure_selector_present(selectors, selector_key, logger)
    else:
        target = (selector or "").strip()

    if not target:
        logger.error(f"{label}: no selector or selector_key provided.")
        raise ValueError(f"{label}: missing selector to wait for hidden")

    try:
        loc = page.locator(target).first
        await loc.wait_for(state="hidden", timeout=timeout_ms)
        logger.info(f"{label}: element became not visible -> {target}")
        return loc
    except PlaywrightTimeout:
        logger.error(f"{label}: element still visible after {timeout_ms}ms -> {target}")
        raise
    except Exception as e:
        logger.error(f"{label}: wait_for_not_visible error -> {target} | {e}")
        raise

# ---------- Atomic actions ----------

async def fill_field(
    page: Page,
    selector: str,
    value: Any,
    field_label: str,
    logger: logging.Logger,
    mask: bool = False,
    timeout_ms: int = 20000,
):
    if value is None or str(value).strip() == "":
        logger.error(f"{field_label}: no value provided; cannot fill.")
        raise ValueError(f"No value for {field_label}")
    loc = await wait_for_visible(page, selector, field_label, logger, timeout_ms=timeout_ms)
    # ensure visible to human/operator
    try:
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.15)
    except Exception:
        logger.debug(f"{field_label}: scroll before fill failed (non-fatal)")
    shown = "***" if mask else str(value)
    try:
        await loc.fill(str(value))
        await asyncio.sleep(0.5)
        logger.info(f"{field_label}: filled with '{shown}'")
    except Exception as e:
        logger.error(f"{field_label}: fill failed @ {selector} | {e}")
        raise

# NEW helper: check and extract warning notification
async def check_warning_notification(
    page: Page,
    logger: logging.Logger,
    *,
    label: str = "Warning check",
    warning_selector: str = "div.ui-pnotify.stack_top_right div.alert.ui-pnotify-container.alert-primary",
    timeout_ms: int = 2000,
) -> tuple[bool, str]:
    """
    Check for warning notification (e.g., "Username cannot be blank").
    Returns (True, warning_message) if warning is visible, (False, "") otherwise.
    """
    try:
        warn_loc = page.locator(warning_selector).first
        if await warn_loc.count() == 0:
            return False, ""
        
        try:
            await warn_loc.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            if not await warn_loc.is_visible():
                return False, ""
        
        # Extract warning message
        try:
            data = await warn_loc.evaluate(
                "el => ({ title: (el.querySelector('h4.ui-pnotify-title')?.innerText || '').trim(), text: (el.querySelector('div.ui-pnotify-text')?.innerText || '').trim(), raw: el.innerText.trim() })"
            )
            title = (data.get("title") or "").strip()
            text = (data.get("text") or "").strip()
            raw = data.get("raw", "")
            
            msg_parts = []
            if title:
                msg_parts.append(title)
            if text:
                msg_parts.append(text)
            
            warning_message = ": ".join(msg_parts) if msg_parts else raw
            if warning_message:
                logger.info(f"{label}: warning notification detected -> {warning_message}")
                return True, warning_message
            else:
                logger.debug(f"{label}: warning notification visible but no readable text")
                return True, "Warning notification (no text)"
        except Exception as e:
            logger.debug(f"{label}: failed to extract warning text -> {e}")
            return True, "Warning notification (extraction failed)"
            
    except Exception as e:
        logger.debug(f"{label}: check_warning_notification error -> {e}")
        return False, ""

# NEW helper: dismiss warning notification by clicking closer
async def dismiss_warning_notification(
    page: Page,
    logger: logging.Logger,
    *,
    label: str = "Dismiss warning",
    warning_selector: str = "div.ui-pnotify.stack_top_right div.alert.ui-pnotify-container.alert-primary",
    closer_selector: str = "div.ui-pnotify-closer",
    timeout_ms: int = 5000,
) -> bool:
    """
    Dismiss a warning notification by clicking the close button.
    Returns True if dismissed successfully, False otherwise.
    """
    try:
        warn_loc = page.locator(warning_selector).first
        if await warn_loc.count() == 0:
            logger.debug(f"{label}: no warning notification to dismiss")
            return False
        
        closer_loc = warn_loc.locator(closer_selector).first
        if await closer_loc.count() == 0:
            logger.debug(f"{label}: warning notification has no closer button")
            return False
        
        await closer_loc.click()
        await asyncio.sleep(0.5)
        
        # Wait for warning to disappear
        try:
            await warn_loc.wait_for(state="hidden", timeout=timeout_ms)
            logger.info(f"{label}: warning notification dismissed")
            return True
        except PlaywrightTimeout:
            logger.warning(f"{label}: warning notification did not disappear after clicking closer")
            return False
            
    except Exception as e:
        logger.error(f"{label}: failed to dismiss warning notification -> {e}")
        return False

async def click_element(page: Page, selector: str, field_label: str, logger: logging.Logger, timeout_ms: int = 20000, validation_check: bool = False, run_id: Optional[str] = None):
    loc = await wait_for_visible(page, selector, field_label, logger, timeout_ms=timeout_ms)
    # make sure the element is visible to the operator before clicking
    try:
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.05)
    except Exception:
        logger.debug(f"{field_label}: scroll before click failed (non-fatal)")
    try:
        await loc.click()
        await asyncio.sleep(0.5)
        logger.info(f"{field_label}: clicked")
        
        # Check for validation errors if validation_check is True
        if validation_check:
            try:
                # Wait for potential validation messages (give a little time for validation to complete)
                await asyncio.sleep(0.3)
                
                # NEW: Check for warning notifications with retry logic
                warning_attempt = 1
                max_warning_attempts = 2
                warning_messages = []
                
                while warning_attempt <= max_warning_attempts:
                    is_warning, warning_message = await check_warning_notification(
                        page=page,
                        logger=logger,
                        label=f"{field_label} warning check (attempt {warning_attempt})"
                    )
                    
                    if is_warning:
                        warning_messages.append(warning_message)
                        logger.warning(f"{field_label}: warning appeared on attempt {warning_attempt} -> {warning_message}")
                        
                        if warning_attempt < max_warning_attempts:
                            # Dismiss warning and retry click
                            dismissed = await dismiss_warning_notification(
                                page=page,
                                logger=logger,
                                label=f"{field_label} dismiss warning (attempt {warning_attempt})"
                            )
                            
                            if dismissed:
                                logger.info(f"{field_label}: retrying click after dismissing warning")
                                await asyncio.sleep(0.2)
                                await loc.click()
                                await asyncio.sleep(0.5)
                                logger.info(f"{field_label}: clicked (retry attempt {warning_attempt})")
                                warning_attempt += 1
                            else:
                                # Could not dismiss, treat as validation error
                                logger.error(f"{field_label}: could not dismiss warning notification")
                                break
                        else:
                            # Second warning appearance - treat as validation error
                            logger.error(f"{field_label}: warning appeared twice, treating as validation error")
                            break
                    else:
                        # No warning found
                        break
                
                # If warnings appeared twice, treat as validation error
                if len(warning_messages) >= 2:
                    combined_warning = f"Warning appeared {len(warning_messages)} times: {' | '.join(warning_messages)}"
                    
                    # Extract request_id from run_id to attach submitted documents
                    from . import send_email as send_email_helper
                    request_id = send_email_helper.extract_request_id_from_run_id(run_id) if run_id else None
                    
                    await notify_process_error(
                        page=page,
                        logger=logger,
                        run_id=run_id,
                        subject=f"[{run_id}] Repeats Warning and Won’t Proceed after {field_label}",
                        body=f"Field: {field_label}\n\n{combined_warning}",
                        shot_name="repeated_warning_error.png",
                        flag_validation=True,
                        request_id=request_id
                    )
                    raise ValidationError(combined_warning)
                
                # Check for validation error summary
                is_error, error_message = await check_validation_summary(
                    page=page,
                    logger=logger,
                    label=f"Post-{field_label} validation check",
                    run_id=run_id
                )
                
                if is_error:
                    # Validation error was found and logged by check_validation_summary
                    # Send error notification
                    # Extract request_id from run_id
                    from . import send_email as send_email_helper
                    request_id = send_email_helper.extract_request_id_from_run_id(run_id) if run_id else None
                    await notify_process_error(
                        page=page,
                        logger=logger,
                        run_id=run_id,
                        subject=f"[{run_id}] Validation error after {field_label}",
                        body=error_message,
                        shot_name="validation_error.png",
                        flag_validation=True,
                        request_id=request_id
                    )
                    raise ValidationError(error_message)
                    
            except ValidationError:
                raise
            except Exception as e:
                logger.error(f"Error checking validation after {field_label}: {e}")
                
    except Exception as e:
        logger.error(f"{field_label}: click failed @ {selector} | {e}")
        raise

    # --- NEW: detect optional loading overlay and wait for it to disappear (non-fatal) ---
    overlay_selector = "//div[@id='__messageBox_wait']"
    try:
        overlay_loc = page.locator(overlay_selector).first
        try:
            # short wait to see if overlay appears at all (non-fatal)
            await overlay_loc.wait_for(state="visible", timeout=2000)
            logger.info(f"{field_label}: loading overlay appeared -> waiting for disappearance")
            # wait longer for it to disappear; use a larger timeout than the click timeout
            overlay_timeout = max(timeout_ms, 30000)
            await wait_for_not_visible(page, logger=logger, selector=overlay_selector, label=f"{field_label} loading overlay", timeout_ms=overlay_timeout)
            logger.info(f"{field_label}: loading overlay disappeared")
        except PlaywrightTimeout:
            # overlay did not appear within the short window — that's fine
            logger.debug(f"{field_label}: loading overlay did not appear after click (short timeout)")
    except Exception as e:
        # non-fatal: any unexpected overlay-check error should not break the flow
        logger.debug(f"{field_label}: overlay wait check failed -> {e}")

    # If caller requested validation check, run the outcome waiter which will log errors or success
    # if validation_check:
    #     try:
    #         found_success = await wait_for_validation_outcome(page, logger, label=field_label, timeout_ms=timeout_ms, run_id=run_id)
    #         if found_success:
    #             logger.debug(f"{field_label}: validation_check -> success detected")
    #         else:
    #             logger.debug(f"{field_label}: validation_check -> no success detected (errors may have been logged)")
    #     except Exception as e:
    #         logger.error(f"{field_label}: validation summary/outcome check failed -> {e}")
    #         raise

    if validation_check:
        try:
            # wait_for_validation_outcome should return True if success, False if error
            found_success = await wait_for_validation_outcome(page, logger, label=field_label, timeout_ms=timeout_ms, run_id=run_id)
            
            if found_success:
                logger.debug(f"{field_label}: validation_check -> success detected")
            else:
                # --- FIX START: Logic added to catch the error here ---
                logger.warning(f"{field_label}: validation_check -> no success detected. Checking for error summary...")
                
                # Check explicitly for the error message again so we can throw it
                is_error, error_message = await check_validation_summary(
                    page=page, 
                    logger=logger, 
                    label=f"Post-Overlay {field_label} validation", 
                    run_id=run_id
                )

                if is_error:
                    # Send the missing email!
                    # Extract request_id from run_id
                    from . import send_email as send_email_helper
                    request_id = send_email_helper.extract_request_id_from_run_id(run_id) if run_id else None
                    await notify_process_error(
                        page=page,
                        logger=logger,
                        run_id=run_id,
                        subject=f"[{run_id}] Validation error after {field_label}",
                        body=error_message,
                        shot_name="validation_error_post_overlay.png",
                        flag_validation=True,
                        request_id=request_id
                    )
                    # Stop the bot!
                    raise ValidationError(error_message)
                else:
                    # Fallback if no specific message found but success was missing
                    raise ValidationError(f"{field_label}: Validation success criteria not met after overlay.")
                # --- FIX END ---

        except Exception as e:
            logger.error(f"{field_label}: validation summary/outcome check failed -> {e}")
            raise

# NEW helper: wait for either validation summary (error) or success notification, log & return outcome
async def wait_for_validation_outcome(
    page: Page,
    logger: logging.Logger,
    *,
    label: str = "Validation outcome",
    val_selector: str = "div.validation-summary-errors.alert.alert-danger",
    success_selector: str = "div.alert.ui-pnotify-container.alert-success, div.ui-pnotify-container.alert-success",
    timeout_ms: int = 5000,
    run_id: Optional[str] = None,
) -> bool:
    """
    Wait until either a validation error or success notification appears. If validation error is found,
    it will be logged once and the ValidationError will be raised immediately. Returns True if success 
    found, False if no notification appears within timeout.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    val_loc = page.locator(val_selector).first
    success_loc = page.locator(success_selector).first
    validation_error_handled = False

    while time.monotonic() < deadline:
        try:
            # Check success first
            if await success_loc.count() and await success_loc.is_visible():
                try:
                    data = await success_loc.evaluate(
                        "el => ({ title: (el.querySelector('h4')?.innerText || '').trim(), text: (el.querySelector('.ui-pnotify-text')?.innerText || '').trim(), raw: el.innerText.trim() })"
                    )
                except Exception:
                    # fallback to inner_text
                    data = {"title": "", "text": "", "raw": (await success_loc.inner_text()).strip()}

                title = (data.get("title") or "").strip()
                text = (data.get("text") or "").strip()
                raw = (data.get("raw") or "").strip()

                msg = text or title or raw
                if msg:
                    logger.info(f"{label}: success -> {msg}")
                else:
                    logger.info(f"{label}: success notification visible (no readable text)")
                return True

            # Then check validation error
            if not validation_error_handled and await val_loc.count() and await val_loc.is_visible():
                # Process validation error only once
                validation_error_handled = True
                await check_validation_summary(page, logger, label=label, selector=val_selector, timeout_ms=timeout_ms, run_id=run_id)
                # This will raise ValidationError so we won't continue polling
                return False

        except ValidationError:
            # Let validation errors propagate up immediately
            raise
        except Exception as e:
            logger.debug(f"{label}: outcome polling check encountered an error -> {e}")

        await asyncio.sleep(0.25)

    # timed out without seeing either element
    logger.debug(f"{label}: neither validation error nor success notification appeared within {timeout_ms}ms")
    return False

# NEW helper: scrape and log validation summary
async def check_validation_summary(page: Page, logger: logging.Logger, *, label: str = "Validation check", selector: str = "div.validation-summary-errors.alert.alert-danger", timeout_ms: int = 2000, run_id: Optional[str] = None) -> tuple[bool, str]:
    """
    Look for a validation-summary alert, extract span + list items, log as error, and return tuple of (found, error_message).
    If run_id provided, save screenshot into data/logs/{run_id}/, otherwise fallback to data/outputs/error_screenshots.
    """
    try:
        val_loc = page.locator(selector).first
        # quick existence/visibility check (fast)
        if await val_loc.count() == 0:
            return False, ""
        # wait briefly for visibility (non-blocking long)
        try:
            await val_loc.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            # not visible within short window -> treat as absent
            if not await val_loc.is_visible():
                return False, ""

        # Extract structured text (span + each li)
        data = await val_loc.evaluate(
            "el => ({ span: (el.querySelector('span')?.innerText || '').trim(), items: Array.from(el.querySelectorAll('ul li')).map(li => li.innerText.trim()), raw: el.innerText.trim() })"
        )
        span_msg = (data.get("span") or "").strip()
        items = data.get("items") or []
        details = "; ".join([it for it in items if it])
        # Build a descriptive message and log as ERROR per requirements
        details_msg = []
        if span_msg:
            details_msg.append(span_msg)
        if details:
            details_msg.append(details)
        raw = data.get("raw", "")
        if not details_msg and raw:
            details_msg.append(raw)

        composed = " | ".join(details_msg) if details_msg else "validation summary present but no readable content"
        error_message = f"Validation Error occurred after clicking {label}: {composed}"
        logger.error(error_message)
        return True, error_message

        # Only write the validation flag file, don't send an email from here
        # The process-level handler in main.py will send the email with proper run context
        if run_id:
            try:
                flag_path = Path(f"data/logs/{run_id}/validation_error.flag")
                flag_path.write_text(composed)
                logger.debug(f"Wrote validation flag file: {flag_path}")
            except Exception as fe:
                logger.debug(f"Failed to write validation flag file: {fe}")

        # Take screenshot but don't send email
        try:
            if page is not None and run_id:
                shot_path = Path(f"data/logs/{run_id}/validation_error_{label.replace(' ', '_')}.png")
                shot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(shot_path), full_page=True)
                logger.error(f"Saved validation error screenshot: {shot_path}")
        except Exception as se:
            logger.error(f"Failed to capture validation error screenshot: {se}")

        # Raise ValidationError so callers stop
        raise ValidationError(composed)
    except ValidationError:
        raise
    except Exception as e:
        logger.debug(f"{label}: check_validation_summary evaluation failed -> {e}")
        return False

async def select_option(
    page: Page,
    selector: str,
    field_label: str,
    logger: logging.Logger,
    *,
    value: Optional[str] = None,
    label: Optional[str] = None,
    index: Optional[int] = None,
    timeout_ms: int = 20000,
):
    """
    Robust select helper with preferred JS-fallback-first strategy:
      1) Inspect options and log them.
      2) Attempt fast JS fallback to set element.value and dispatch 'change' using the best-matched option value.
      3) If JS fallback fails, attempt index/value/label selection and the normalized fallback matching.
    """
    if value is None and label is None and index is None:
        logger.error(f"{field_label}: no select option provided (value/label/index).")
        raise ValueError(f"No select option for {field_label}")

    loc = await wait_for_visible(page, selector, field_label, logger, timeout_ms=timeout_ms)

    # scroll into view so operator can see the select before changes
    try:
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.15)
    except Exception:
        logger.debug(f"{field_label}: scroll before select failed (non-fatal)")

    # normalize helper
    def _norm(s: str) -> str:
        return s.strip().lower().rstrip(".")

    async def _inspect_options() -> List[Dict[str, str]]:
        try:
            return await loc.evaluate(
                "el => Array.from(el.options).map(o => ({ value: o.value, text: (o.text || '').trim() }))"
            )
        except Exception as e:
            logger.debug(f"{field_label}: failed to inspect options -> {e}")
            return []

    # 1) Inspect & log available options
    opts = await _inspect_options()
    if opts:
        opts_str = ", ".join([f"{o.get('value','')}=>'{o.get('text','')}'" for o in opts])
        logger.info(f"{field_label}: available options -> {opts_str}")
    else:
        logger.info(f"{field_label}: no options discovered during inspection")

    # Determine target normalized tokens
    target_norms = []
    if value is not None:
        target_norms.append(("value", _norm(str(value))))
    if label is not None:
        target_norms.append(("label", _norm(str(label))))

    # Try to derive a concrete option.value from available options (normalized matches)
    found_value: Optional[str] = None
    for kind, tnorm in target_norms:
        for o in opts:
            if _norm(o.get("text", "")) == tnorm or _norm(o.get("value", "")) == tnorm:
                found_value = o.get("value")
                break
        if found_value:
            break

    if not found_value:
        for kind, tnorm in target_norms:
            for o in opts:
                if tnorm in _norm(o.get("text", "")) or tnorm in _norm(o.get("value", "")):
                    found_value = o.get("value")
                    break
            if found_value:
                break

    # 2) Fast JS fallback first (preferred by request)
    if found_value is not None:
        try:
            await loc.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('change')); }", found_value)
            await asyncio.sleep(0.25)
            # verify applied
            current = await loc.evaluate("el => el.value")
            if str(current) == str(found_value):
                logger.info(f"{field_label}: selected via JS fallback (value='{found_value}')")
                return
            else:
                logger.debug(f"{field_label}: JS fallback set value='{found_value}' but element.value is '{current}' (will try other methods)")
        except Exception as e_js:
            logger.debug(f"{field_label}: JS fallback attempt failed -> {e_js}; will try other methods")

    # If JS fallback didn't apply or no derived value, continue with resilient selection attempts
    try:
        # index direct
        if index is not None:
            await loc.select_option({"index": int(index)})
            await asyncio.sleep(0.1)
            logger.info(f"{field_label}: selected (index={index})")
            return

        # try direct value attempt (if provided)
        if value is not None:
            try:
                await loc.select_option({"value": str(value)})
                await asyncio.sleep(0.1)
                logger.info(f"{field_label}: selected (value='{value}')")
                return
            except Exception as e_val:
                logger.debug(f"{field_label}: select by value '{value}' failed -> {e_val}")

        # try direct label attempt
        if label is not None:
            try:
                await loc.select_option({"label": str(label)})
                await asyncio.sleep(0.1)
                logger.info(f"{field_label}: selected (label='{label}')")
                return
            except Exception as e_lbl:
                logger.debug(f"{field_label}: select by label '{label}' failed -> {e_lbl}")

        # If we derived found_value earlier but JS didn't finalize, try selecting by that value via select_option
        if found_value is not None:
            try:
                await loc.select_option({"value": found_value})
                await asyncio.sleep(0.1)
                logger.info(f"{field_label}: selected after fallback (value='{found_value}')")
                return
            except Exception as e_final:
                logger.debug(f"{field_label}: select by derived value '{found_value}' failed -> {e_final}")

        # As last resort try a JS set with raw requested value/label
        js_val = value if value is not None else (label or "")
        try:
            await loc.evaluate("(el, v) => { el.value = v; el.dispatchEvent(new Event('change')); }", js_val)
            await asyncio.sleep(0.1)
            current = await loc.evaluate("el => el.value")
            logger.info(f"{field_label}: attempted JS set fallback (requested='{js_val}', current='{current}')")
            return
        except Exception as e_js2:
            logger.debug(f"{field_label}: final JS fallback failed -> {e_js2}")

        # If we get here without success, decide whether this is a "value mismatch" (non-fatal)
        # or an interaction/XPath/element problem (critical).
        # If options were discovered but no matching option found -> treat as value mismatch (DEBUG), do not send email or stop process.
        if opts:
            # Report as DEBUG per rules with attempted token(s) & available options
            try:
                opts_str = ", ".join([f"{o.get('value','')}=>'{o.get('text','')}'" for o in opts])
            except Exception:
                opts_str = str(opts)
            attempted = value if value is not None else (label or "")
            logger.debug(f"{field_label}: value mismatch; attempted='{attempted}'; available_options={opts_str}")
            return
        else:
            # No options discovered and selection failed -> likely XPath/element interaction issue. Treat as critical ERROR.
            # Capture screenshot and notify
            logger.error(f"{field_label}: select failed @ {selector} (element/options not available or not interactable)")
            try:
                shot_dir = Path("data/outputs/error_screenshots")
                shot_dir.mkdir(parents=True, exist_ok=True)
                shot_path = shot_dir / f"select_error_{field_label.replace(' ', '_')}.png"
                await page.screenshot(path=str(shot_path), full_page=True)
                logger.error(f"Saved select error screenshot: {shot_path}")
            except Exception as se:
                shot_path = None
                logger.error(f"Failed to capture select error screenshot: {se}")

            # NOTE: Log files are NOT attached to error emails (removed as per CR update)
            subject = f"Critical select error in {field_label}"
            body = f"Field: {field_label}\nSelector: {selector}\nAttempted value: {value or label or index}\n\nAn element interaction or selector problem occurred while trying to select a value."
            try:
                # Note: This function doesn't have run_id, so cannot extract request_id here
                # If needed in future, run_id should be passed to select_option function
                await send_email_helper.send_error_email(subject, body, screenshot_path=shot_path, log_files=None, logger=logger)
                logger.error("Dispatched select failure email.")
            except Exception as me:
                logger.error(f"Failed to send select failure email: {me}")

            raise RuntimeError(f"{field_label}: unable to select option (element problem)")
    except Exception as e:
        logger.error(f"{field_label}: select failed @ {selector} | {e}")
        raise

# ---------- NEW: Get autofilled input value helper ----------
async def get_autofilled_input_value(
    page: Page,
    *,
    logger: logging.Logger,
    label: str = "Get input value",
    selector: Optional[str] = None,
    selector_key: Optional[str] = None,
    selectors: Optional[Dict[str, Any]] = None,
    timeout_ms: int = 10000,
) -> Optional[str]:
    """
    Read and return the 'value' of an input element. Accepts either a raw selector string
    or a selector_key to lookup from a selectors dict. Logs the found value.
    Returns the string value or None if the element has no value.
    """
    if selector_key:
        if selectors is None:
            logger.error(f"{label}: selector_key='{selector_key}' provided but 'selectors' dict is None.")
            raise ValueError(f"{label}: selectors dict required when using selector_key")
        target = ensure_selector_present(selectors, selector_key, logger)
    else:
        target = (selector or "").strip()

    if not target:
        logger.error(f"{label}: no selector or selector_key provided.")
        raise ValueError(f"{label}: missing selector for get_autofilled_input_value")

    # Wait for the input to be visible so value is available
    try:
        loc = await wait_for_visible(page, target, label, logger, timeout_ms=timeout_ms)
    except Exception as e:
        logger.error(f"{label}: element not visible -> {target} | {e}")
        raise

    try:
        # Try to read value via evaluation (preferred); fallback to get_attribute('value')
        try:
            value = await loc.evaluate("el => el.value")
        except Exception:
            value = await loc.get_attribute("value")
        value_str = None if value is None else str(value)
        logger.info(f"{label}: autofilled value -> '{value_str}' (selector={target})")
        return value_str
    except Exception as e:
        logger.error(f"{label}: failed to read value -> {target} | {e}")
        raise

# ---------- High-level dispatcher (loop driver) ----------

async def run_actions(
    page: Page,
    *,
    actions: Sequence[Dict[str, Any]],
    selectors: Dict[str, Any],
    df,  # pandas.DataFrame
    logger: logging.Logger,
    default_timeout_ms: int = 20000,
    run_id: Optional[str] = None,
):
    """
    Iterate a list of action dicts and execute each with detailed logging.
    Now supports an action-level boolean "required" flag:
      - If required=True and the action fails, the exception is re-raised (stop flow).
      - If required=False (default) and the action fails, the error is logged as info and the flow continues.
    """
    for i, action in enumerate(actions, start=1):
        atype = (action.get("type") or "").lower()
        label = action.get("label") or atype.capitalize()
        timeout_ms = int(action.get("timeout_ms", default_timeout_ms))
        required = bool(action.get("required", False))

        try:
            # --- EARLY checks: determine action value(s) BEFORE touching selectors ---
            # For 'fill' actions, resolve the value early and skip if empty (to avoid waiting)
            if atype == "fill":
                if "value" in action:
                    value = action["value"]
                else:
                    value_col = action.get("value_col")
                    if not value_col:
                        logger.error(f"{label}: no value or value_col provided for fill.")
                        raise ValueError(f"{label}: no value or value_col")
                    value = df.iloc[0][value_col]

                if value is None or str(value).strip() == "":
                    if required:
                        logger.error(f"{label}: required field missing value; aborting.")
                        raise ValueError(f"No value for {label}")
                    else:
                        logger.info(f"{label}: no value provided; skipping without waiting")
                        continue  # skip resolving selector / waiting

            # For 'select' actions, resolve the selection value early and skip if empty
            if atype == "select":
                sel_value = action.get("value")
                if sel_value is None:
                    value_col = action.get("value_col")
                    if not value_col:
                        logger.error(f"{label}: no value or value_col provided for select.")
                        raise ValueError(f"{label}: no value or value_col")
                    sel_value = df.iloc[0][value_col]

                # Treat empty strings or None as "no value" and skip if not required
                if sel_value is None or str(sel_value).strip() == "":
                    if required:
                        logger.error(f"{label}: required select missing value; aborting.")
                        raise ValueError(f"No value for {label}")
                    else:
                        logger.info(f"{label}: no value provided; skipping select without waiting")
                        continue  # skip selector resolution / wait

            # Only now resolve selector for actions that need it
            selector = None
            if atype in ("fill", "select", "click", "wait_visible", "wait_not_visible"):
                key = action.get("key")
                if not key:
                    logger.error(f"Action #{i} ({atype}): missing 'key' for selector lookup.")
                    raise ValueError(f"Action #{i} missing key")
                selector = ensure_selector_present(selectors, key, logger)

            # --- Execute action (fill/select/click/waits) ---
            if atype == "fill":
                # Log attempt before doing the expensive wait/fill
                mask_flag = bool(action.get("mask", False))
                display_val = "***" if mask_flag else str(value)
                logger.info(f"{label}: trying to fill with '{display_val}'")
                await fill_field(page, selector, value, label, logger, mask=mask_flag, timeout_ms=timeout_ms)

            elif atype == "select":
                # Log attempt before doing the expensive wait/select
                display_sel = str(sel_value)
                logger.info(f"{label}: trying to select '{display_sel}'")
                # use the sel_value resolved above and follow selection strategy
                select_by = (action.get("select_by") or "value").lower()
                try:
                    if select_by == "label":
                        await select_option(page, selector, label, logger, label=str(sel_value), timeout_ms=timeout_ms)
                    elif select_by == "index":
                        await select_option(page, selector, label, logger, index=int(sel_value), timeout_ms=timeout_ms)
                    else:
                        try:
                            await select_option(page, selector, label, logger, value=str(sel_value), timeout_ms=timeout_ms)
                        except Exception as e_val:
                            logger.debug(f"{label}: select by value failed -> {e_val}; attempting select by label as fallback.")
                            await select_option(page, selector, label, logger, label=str(sel_value), timeout_ms=timeout_ms)
                except Exception:
                    raise

            elif atype == "click":
                validation_check = bool(action.get("validation_check", False))
                
                # Check if this is a conditional checkbox with value_col
                value_col = action.get("value_col")
                if value_col:
                    # Check if DataFrame has the column and get the value
                    if hasattr(df, 'columns') and value_col in df.columns and not df.empty:
                        df_value = str(df.iloc[0][value_col]).strip().lower()
                        if df_value == "yes":
                            logger.info(f"{label}: checkbox condition met (value='{df_value}') - clicking")
                        else:
                            logger.info(f"{label}: checkbox condition not met (value='{df_value}') - skipping click")
                            continue  # Skip this action
                    else:
                        logger.info(f"{label}: checkbox column '{value_col}' not found in DataFrame - skipping click")
                        continue  # Skip this action
                
                logger.info(f"{label}: trying to click")
                # pass run_id down so validation screenshot ends up in the run folder
                await click_element(page, selector, label, logger, timeout_ms=timeout_ms, validation_check=validation_check, run_id=run_id)

            elif atype == "wait_visible":
                await wait_for_visible(page, selector, label, logger, timeout_ms=timeout_ms)

            elif atype == "wait_not_visible":
                await wait_for_not_visible(page, logger=logger, selector=selector, label=label, timeout_ms=timeout_ms)

            elif atype == "wait_text":
                if "text" in action:
                    text = action["text"]
                else:
                    text_from = action.get("text_from")
                    if not text_from:
                        logger.error(f"{label}: wait_text requires 'text' or 'text_from'.")
                        raise ValueError(f"{label}: missing 'text'/'text_from'")
                    text = selectors.get(text_from)
                if not text:
                    logger.error(f"{label}: no text found for wait_text.")
                    raise ValueError(f"{label}: empty text for wait_text")
                await wait_for_text(page, str(text), label, logger, timeout_ms=timeout_ms)
            else:
                logger.error(f"Action #{i}: unknown type '{atype}'")
                raise ValueError(f"Unknown action type: {atype}")

            logger.debug(f"Action #{i} ({atype}) completed")

        except Exception as e:
            # Respect the action-level 'required' flag:
            if required:
                logger.error(f"{label}: required action failed -> {e}")
                # Reraise so callers (process flows) can decide to stop the run entirely.
                raise
            else:
                # Non-fatal: log at INFO and continue with remaining actions
                logger.info(f"{label}: optional action skipped/failed -> {e}")
                logger.debug(f"Action #{i} ({atype}) non-fatal exception detail: {e}")
                continue

async def notify_process_error(
    *,
    page: Optional[Page],
    logger: logging.Logger,
    run_id: Optional[str],
    subject: str,
    body: str,
    shot_name: str = "error.png",
    flag_validation: bool = False,
    extra_log_files: Optional[list[Path]] = None,
    request_id: Optional[str] = None,
):
    """
    Centralized helper to:
      - save a screenshot into data/logs/{run_id}/<shot_name>
      - optionally write validation flag file data/logs/{run_id}/validation_error.flag
      - attach all submitted documents if request_id is provided
      - send an error email via send_email_helper.send_error_email
    Non-fatal helper: logs internal failures but does not raise.
    """
    shot_path = None
    try:
        if run_id:
            run_dir = Path(f"data/logs/{run_id}")
            run_dir.mkdir(parents=True, exist_ok=True)
            shot_path = run_dir / shot_name
            if page is not None:
                await page.screenshot(path=str(shot_path), full_page=True)
            logger.error(f"Saved process error screenshot: {shot_path}")
        else:
            # fallback location
            fallback_dir = Path("data/outputs/error_screenshots")
            fallback_dir.mkdir(parents=True, exist_ok=True)
            shot_path = fallback_dir / shot_name
            if page is not None:
                await page.screenshot(path=str(shot_path), full_page=True)
            logger.error(f"Saved process error screenshot (fallback): {shot_path}")
    except Exception as se:
        logger.error(f"Failed to capture process error screenshot: {se}")
        shot_path = None

    # write validation flag if requested (main checks this)
    try:
        if flag_validation and run_id:
            flag_path = Path(f"data/logs/{run_id}/validation_error.flag")
            flag_path.write_text(body or subject or "validation error")
            logger.debug(f"Wrote validation flag file: {flag_path}")
    except Exception as fe:
        logger.debug(f"Failed to write validation flag file: {fe}")

    # NOTE: Log files are NOT attached to error emails (removed as per CR update)
    # Only screenshots and submitted documents are attached
    try:
        # send email (best-effort)
        await send_email_helper.send_error_email(
            subject, 
            body, 
            screenshot_path=shot_path, 
            log_files=None,  # Not sending log files
            logger=logger,
            request_id=request_id
        )
        logger.error("Dispatched process error email via notify_process_error.")
    except Exception as me:
        logger.error(f"Failed to send process error email: {me}")

async def upload_files_via_drop(
    page: Page,
    *,
    files: Sequence[Dict[str, Any]],
    drop_selector: str = "div[id^='DragnDrop__'].dropzone",
    logger: logging.Logger,
    run_id: Optional[str] = None,
    wait_between: float = 2.0,
) -> None:
    """
    Upload multiple files into a dropzone by simulating drag & drop.
    - files: sequence of dicts { "path": dir_or_file, "file_name": basename_or_full_or_stem, "doc_type": str|None, "expiry_date": str|None }
    Resolves file paths (dir + filename, absolute file, or cwd fallback). If file_name has no extension,
    it will search for any matching stem.* in the provided directory (or cwd). Uploads sequentially,
    logs File Name / Document Type / Expiry Date per-file and waits `wait_between` seconds between files.
    """
    from fnmatch import fnmatch

    def find_by_stem_in_dir(dir_path: Path, stem: str) -> Optional[Path]:
        try:
            # direct exact match (with any extension)
            for p in dir_path.iterdir():
                if p.is_file() and p.stem.lower() == stem.lower():
                    return p
            # fallback: glob any extension (first match)
            for p in dir_path.glob(f"{stem}.*"):
                if p.is_file():
                    return p
        except Exception:
            return None
        return None

    for entry in files:
        # validate entry
        if not isinstance(entry, dict):
            logger.warning(f"Skipping invalid document entry (not a dict): {entry}")
            continue

        path_field = entry.get("path") or ""
        file_name_field = (entry.get("file_name") or entry.get("filename") or "").strip()
        doc_type = entry.get("doc_type")
        expiry = entry.get("expiry_date")

        resolved: Optional[Path] = None
        try:
            # If file_name_field is empty, skip
            if not file_name_field:
                logger.warning(f"Skipping document entry with empty file_name: {entry}")
                continue

            # If path_field points to a file -> use it
            if path_field:
                p = Path(path_field)
                if p.exists() and p.is_file():
                    resolved = p
                elif p.exists() and p.is_dir():
                    # if file_name_field includes extension, try exact
                    cand = p / file_name_field
                    if cand.exists() and cand.is_file():
                        resolved = cand
                    else:
                        # if caller passed stem only (no suffix) -> find by stem
                        if Path(file_name_field).suffix == "":
                            found = find_by_stem_in_dir(p, Path(file_name_field).stem)
                            if found:
                                resolved = found
                        else:
                            # try to find case-insensitive match in dir
                            for f in p.iterdir():
                                if f.is_file() and f.name.lower() == file_name_field.lower():
                                    resolved = f
                                    break

            # if not resolved, check file_name as absolute/relative path
            if resolved is None:
                cand2 = Path(file_name_field)
                if cand2.exists() and cand2.is_file():
                    resolved = cand2

            # fallback: try cwd / path_field / file_name and handle stem-only
            if resolved is None:
                # if path_field looks like a relative directory
                try:
                    if path_field:
                        cand3 = Path.cwd() / path_field
                        if cand3.exists() and cand3.is_dir():
                            if Path(file_name_field).suffix == "":
                                found = find_by_stem_in_dir(cand3, Path(file_name_field).stem)
                                if found:
                                    resolved = found
                            else:
                                cand = cand3 / file_name_field
                                if cand.exists() and cand.is_file():
                                    resolved = cand
                except Exception:
                    pass

            # final fallback: try cwd / file_name (and stem matching)
            if resolved is None:
                cand4 = Path.cwd()
                if Path(file_name_field).suffix == "":
                    found = find_by_stem_in_dir(cand4, Path(file_name_field).stem)
                    if found:
                        resolved = found
                else:
                    cand = cand4 / file_name_field
                    if cand.exists() and cand.is_file():
                        resolved = cand

        except Exception as e:
            logger.debug(f"Error while resolving document path (path='{path_field}' file_name='{file_name_field}'): {e}")
            resolved = None

        if resolved is None or not resolved.exists():
            logger.warning(f"Document file not found, skipping: path='{path_field}' file_name='{file_name_field}'")
            continue

        file_path = resolved
        file_name = file_path.name

        # Check file size and compress if needed (CR: Compress documents > 5 MB)
        from src.utils.document_compressor import compress_document, get_file_size_mb
        
        original_size_mb = get_file_size_mb(file_path)
        if original_size_mb > 5.0:
            logger.info(f"File {file_name} ({original_size_mb:.2f} MB) exceeds 5 MB limit, compressing...")
            compressed_file, was_compressed = compress_document(file_path, logger=logger)
            if was_compressed:
                file_path = compressed_file
                file_name = file_path.name
                logger.info(f"Using compressed file: {file_name} ({get_file_size_mb(file_path):.2f} MB)")
            else:
                logger.warning(f"Compression not available or failed for {file_name}, uploading original file")

        # Log metadata before attempt
        logger.info(f"Uploading document -> File Name: '{file_name}'; Document Type: '{doc_type or 'N/A'}'; Expiry Date: '{expiry or 'N/A'}'")

        try:
            b64 = base64.b64encode(file_path.read_bytes()).decode()
            params = {"b64": b64, "filename": file_name, "selector": drop_selector}
            result = await page.evaluate(
                """async (params) => {
                    const { b64, filename, selector } = params;
                    try {
                        const binary = atob(b64);
                        const len = binary.length;
                        const bytes = new Uint8Array(len);
                        for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
                        const file = new File([bytes], filename, { type: 'application/octet-stream' });

                        let dt;
                        try {
                            dt = new DataTransfer();
                            dt.items.add(file);
                        } catch (e) {
                            dt = { files: [file], items: [] };
                        }

                        let target = null;
                        
                        // Handle both CSS selectors and XPath selectors
                        if (selector.startsWith('//') || selector.startsWith('(//')) {
                            // XPath selector
                            try {
                                const result = document.evaluate(selector, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                target = result.singleNodeValue;
                            } catch (e) {
                                console.warn('XPath evaluation failed:', e);
                            }
                        } else {
                            // CSS selector
                            try {
                                target = document.querySelector(selector);
                            } catch (e) {
                                console.warn('CSS selector failed:', e);
                            }
                        }
                        
                        // Fallback to common dropzone selectors
                        if (!target) {
                          target = document.querySelector('.dropzone') || 
                                  document.querySelector('[class*="dropzone"]') ||
                                  document.querySelector('[id*="DragnDrop"]') ||
                                  document.body;
                        }
                        
                        if (!target) return { ok: false, reason: 'no-target' };

                        const makeEvent = (name) => {
                            try {
                                return new DragEvent(name, { bubbles: true, cancelable: true, dataTransfer: dt });
                            } catch (e) {
                                const evt = document.createEvent('Event');
                                evt.initEvent(name, true, true);
                                evt.dataTransfer = dt;
                                return evt;
                            }
                        };

                        target.dispatchEvent(makeEvent('dragenter'));
                        target.dispatchEvent(makeEvent('dragover'));
                        target.dispatchEvent(makeEvent('drop'));

                        return { ok: true };
                    } catch (err) {
                        return { ok: false, reason: String(err) };
                    }
                }""",
                params,
            )

            if isinstance(result, dict) and result.get("ok"):
                logger.info(f"Document dropped -> '{file_name}'")
                # After successful drop: wait for table row to be fully rendered, then set DocType and Expiry Date
                try:
                    # Add extra wait for first document to ensure table is properly initialized
                    await asyncio.sleep(0.3)
                    
                    edit_res = await page.evaluate(
                        """async (p) => {
                            const { filename, doc_type, expiry } = p;
                            const filename_noext = filename.replace(/\\.[^/.]+$/, '');
                            
                            // Wait for table rows to be available with retry logic
                            let target = null;
                            let attempts = 0;
                            const maxAttempts = 10;
                            
                            while (!target && attempts < maxAttempts) {
                                const rows = Array.from(document.querySelectorAll('table[id^=\"DocumentDetailsTable\"] .jqgrow'));
                                
                                for (const r of rows) {
                                    try {
                                        const og = r.querySelector('[aria-describedby$=\"_OgFileName\"]');
                                        const fn = r.querySelector('[aria-describedby$=\"_FileName\"]');
                                        if (og && og.title && og.title === filename) { target = r; break; }
                                        if (fn) {
                                            const title = (fn.title || fn.getAttribute('title') || (fn.innerText || '').trim());
                                            if (title === filename_noext || title === filename || title.includes(filename_noext)) { target = r; break; }
                                        }
                                        if (r.innerText && r.innerText.indexOf(filename_noext) !== -1) { target = r; break; }
                                    } catch (ee) { /* continue */ }
                                }
                                
                                if (!target) {
                                    attempts++;
                                    await new Promise(r => setTimeout(r, 300));
                                }
                            }
                            
                            if (!target) return { ok: false, reason: 'row-not-found-after-retry' };

                            // 1) Click doc-type cell to enable edit/select with retry logic
                            const docCell = target.querySelector('[aria-describedby$=\"_DocType\"]');
                            if (!docCell) return { ok: false, reason: 'doctype-cell-not-found' };
                            
                            // Double-click the cell to ensure it's in edit mode
                            try { 
                                docCell.click(); 
                                await new Promise(r => setTimeout(r, 100));
                                docCell.click();
                            } catch(e){}
                            await new Promise(r => setTimeout(r, 500));
                            
                            // Try multiple selectors to find the select element
                            let sel = docCell.querySelector('select[name=\"DocType\"]') || 
                                     docCell.querySelector('select') ||
                                     document.querySelector('select[name=\"DocType\"]') ||
                                     document.querySelector('td[aria-describedby$=\"_DocType\"] select');
                            
                            // If select not found, try clicking again and wait longer
                            if (!sel) {
                                try { 
                                    docCell.focus();
                                    docCell.click(); 
                                } catch(e){}
                                await new Promise(r => setTimeout(r, 700));
                                sel = docCell.querySelector('select[name=\"DocType\"]') || 
                                     docCell.querySelector('select') ||
                                     document.querySelector('select[name=\"DocType\"]') ||
                                     document.querySelector('td[aria-describedby$=\"_DocType\"] select');
                            }
                            
                            if (doc_type && sel) {
                                const opts = Array.from(sel.options || []);
                                const lowerDoc = (doc_type || '').toString().trim().toLowerCase();
                                let optMatch = opts.find(o => ((o.value||'').toString().toLowerCase() === lowerDoc))
                                               || opts.find(o => ((o.text||'').toString().toLowerCase().indexOf(lowerDoc) !== -1))
                                               || opts.find(o => (o.value||'').toString() === (doc_type||'').toString().toUpperCase())
                                               || opts.find(o => ((o.text||'').toString().toLowerCase() === lowerDoc));
                                               
                                if (!optMatch) return { ok: false, reason: 'doctype-option-not-found', available_options: opts.map(o => ({value: o.value, text: o.text})) };
                                
                                try {
                                    sel.focus();
                                    await new Promise(r => setTimeout(r, 100));
                                    sel.value = optMatch.value;
                                    sel.dispatchEvent(new Event('input', { bubbles: true }));
                                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                                    await new Promise(r => setTimeout(r, 100));
                                    // press Enter on select
                                    try {
                                        sel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                                        sel.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
                                    } catch(e){}
                                    await new Promise(r => setTimeout(r, 200));
                                } catch(e){
                                    return { ok: false, reason: 'doctype-set-failed', error: e.toString() };
                                }
                            } else if (doc_type && !sel) {
                                return { ok: false, reason: 'doctype-select-not-found-after-retry' };
                            }

                            // 2) Set expiry cell (click -> input -> value -> Enter)
                            try {
                                const expCell = target.querySelector('[aria-describedby$=\"_ExpiryDate\"]');
                                if (expCell && expiry) {
                                    try { 
                                        expCell.click(); 
                                        await new Promise(r => setTimeout(r, 100));
                                        expCell.click();
                                    } catch(e){}
                                    await new Promise(r => setTimeout(r, 300));
                                    let inp = expCell.querySelector('input[type=\"text\"], input[type=\"date\"], input');
                                    if (inp) {
                                        try {
                                            inp.focus();
                                            await new Promise(r => setTimeout(r, 50));
                                            inp.value = expiry || '';
                                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                                            await new Promise(r => setTimeout(r, 100));
                                            try {
                                                inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
                                                inp.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
                                            } catch(e){}
                                            try { inp.blur(); } catch(e){}
                                        } catch(e){}
                                    } else {
                                        try { expCell.title = expiry || ''; } catch(e){}
                                    }
                                }
                            } catch(e){}

                            return { ok: true };
                        }""",
                        {"filename": file_name, "doc_type": (doc_type or ""), "expiry": (expiry or "")}
                    )

                    if isinstance(edit_res, dict) and edit_res.get("ok"):
                        logger.info(f"Document metadata set -> File Name: '{file_name}'; Document Type: '{doc_type or 'N/A'}'; Expiry Date: '{expiry or 'N/A'}'")
                    else:
                        logger.warning(f"Failed to set metadata for '{file_name}': {edit_res}")
                except Exception as ee:
                    logger.error(f"Error while setting document metadata for '{file_name}': {ee}")
            else:
                logger.warning(f"Document upload reported failure for {file_name}: {result}")
        except Exception as e:
            logger.error(f"Document upload failed for '{file_name}': {e}")

        # wait between files to let the UI process uploads
        try:
            await asyncio.sleep(wait_between)
        except Exception:
            await asyncio.sleep(0.1)
