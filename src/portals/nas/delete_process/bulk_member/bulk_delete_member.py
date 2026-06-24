from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.portals.nas.add_process.bulk_member.bulk_add_member import (
    NasBulkValidationDownloadError,
)
from src.utils.support_functions import ensure_selector_present


@dataclass(frozen=True)
class NasBulkDeleteResult:
    uploaded_file: Path
    evidence_screenshot: Path | None


def _safe_file_part(value: Any, fallback: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in str(value or "").strip()
    )
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized[:80] or fallback


def _resolve_delete_excel_path(values: Dict[str, Any]) -> Path:
    excel_path = str(values.get("batch_delete_member_file") or "").strip()
    if not excel_path:
        raise ValueError("NAS batch_delete_member_file is required for bulk delete upload")

    resolved_path = Path(excel_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(
            "NAS bulk delete Excel file was not found. "
            f"Expected: {resolved_path}. Set NAS_BULK_DELETE_MEMBER_FILE to override this path."
        )
    return resolved_path


async def _wait_after_click(page: Page, timeout_ms: int = 15000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    await asyncio.sleep(0.5)


async def run_bulk_delete_member(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    download_dir: Path,
    logger: logging.Logger,
) -> NasBulkDeleteResult:
    logger.info("NAS bulk delete-member process started")
    resolved_path = _resolve_delete_excel_path(values)

    file_input_selector = ensure_selector_present(selectors, "excel_file_input", logger)
    save_button_selector = ensure_selector_present(selectors, "import_save_button", logger)
    confirmation_dialog_selector = ensure_selector_present(
        selectors,
        "confirmation_dialog",
        logger,
    )
    confirmation_close_selector = ensure_selector_present(
        selectors,
        "confirmation_close_button",
        logger,
    )

    file_input = page.locator(file_input_selector).first
    await file_input.wait_for(state="attached", timeout=60000)
    await file_input.set_input_files(str(resolved_path))
    logger.info("NAS bulk delete Excel uploaded: %s", resolved_path)

    save_button = page.locator(save_button_selector).first
    await save_button.wait_for(state="visible", timeout=30000)

    download_task = asyncio.create_task(page.wait_for_event("download", timeout=60000))
    confirmation_task = asyncio.create_task(
        page.locator(confirmation_dialog_selector).first.wait_for(
            state="visible",
            timeout=60000,
        )
    )

    await save_button.click()
    await _wait_after_click(page, timeout_ms=30000)

    evidence_screenshot: Path | None = None
    try:
        done, _ = await asyncio.wait(
            {download_task, confirmation_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if download_task in done and not download_task.cancelled():
            try:
                download = download_task.result()
            except PlaywrightTimeoutError:
                download = None

            if download is not None:
                download_dir = Path(download_dir).resolve()
                download_dir.mkdir(parents=True, exist_ok=True)
                suggested_name = Path(
                    str(
                        download.suggested_filename
                        or "nas_bulk_delete_validation_errors.xlsx"
                    )
                ).name
                output_path = download_dir / f"nas_delete_validation_{suggested_name}"
                await download.save_as(str(output_path))
                logger.error("NAS bulk delete validation workbook downloaded: %s", output_path)
                raise NasBulkValidationDownloadError(
                    "NAS rejected the uploaded delete Excel file and returned a "
                    "validation workbook. Review the attached Excel file and "
                    "correct the invalid member deletion data.",
                    downloaded_file=output_path,
                )

        if confirmation_task in done:
            confirmation_task.result()
        else:
            raise RuntimeError(
                "NAS bulk delete Save completed, but neither a confirmation dialog "
                "nor a validation workbook appeared"
            )

        screenshot_dir = Path(download_dir).resolve()
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        evidence_screenshot = (
            screenshot_dir / f"nas_bulk_delete_{_safe_file_part(resolved_path.stem, 'result')}.jpg"
        )
        await page.screenshot(
            path=str(evidence_screenshot),
            type="jpeg",
            quality=65,
            full_page=True,
        )
        logger.info("Saved NAS bulk delete evidence screenshot: %s", evidence_screenshot)

        close_button = page.locator(confirmation_close_selector).first
        await close_button.wait_for(state="visible", timeout=30000)
        await close_button.click()
        await _wait_after_click(page)
        logger.info("NAS bulk delete confirmation dialog closed")

    finally:
        for task in (download_task, confirmation_task):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, PlaywrightTimeoutError):
                await task

    logger.info("NAS bulk delete-member process completed")
    return NasBulkDeleteResult(
        uploaded_file=resolved_path,
        evidence_screenshot=evidence_screenshot,
    )
