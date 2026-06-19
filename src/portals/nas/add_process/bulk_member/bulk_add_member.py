from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
from pathlib import Path
import re
from typing import Any, Dict

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from src.portals.nas.add_process.member.master_contract_page import (
    DEFAULT_ACCORDION_TEXT,
    _normalize_text,
)
from src.services.census_service.nas.common import (
    normalize_contract_name as normalize_bulk_contract_name,
)
from src.utils.support_functions import ensure_selector_present


PAYER_NAMES = {
    "LIVA": "Liva Insurance B.S.C. (C) - LIVA - Nas",
    "QIC": "Qatar Insurance Company - QIC - NAS",
}

_NAS_ATTACHMENT_FIELDS = {
    "visa_copy",
    "passport_copy",
    "national_id_copy",
    "continuity_certificate",
    "member_certificate",
    "declaration_attachment",
    "other_attachment",
}
_NAS_ATTACHMENT_ALLOWED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".pdf",
}
_NAS_ATTACHMENT_MAX_BYTES = 3 * 1024 * 1024


class NasBulkValidationDownloadError(RuntimeError):
    def __init__(self, message: str, downloaded_file: Path):
        super().__init__(message)
        self.downloaded_file = Path(downloaded_file)


@dataclass(frozen=True)
class NasBulkAddResult:
    processed_count: int
    member_screenshots: list[Path]


def resolve_payer_name_from_email_filename(filename: str | None) -> str | None:
    searchable = re.sub(r"[^A-Z0-9]+", " ", str(filename or "").upper())
    codes = {code for code in PAYER_NAMES if re.search(rf"\b{re.escape(code)}\b", searchable)}
    if len(codes) == 1:
        return PAYER_NAMES[codes.pop()]
    return None


def _canonical_contract_text(value: Any) -> str:
    normalized = normalize_bulk_contract_name(value).upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", normalized).split())


def _safe_file_part(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    return normalized.strip("_")[:80] or fallback


def _canonical_member_name(value: Any) -> str:
    return " ".join(
        re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).split()
    )


async def _wait_after_click(page: Page, timeout_ms: int = 15000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    await asyncio.sleep(0.5)


async def _first_visible_enabled(locator: Locator) -> Locator | None:
    count = await locator.count()
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible() and await candidate.is_enabled():
                return candidate
        except Exception:
            continue
    return None


async def _active_timeline_step(page: Page, selector: str) -> str:
    active_pane = page.locator(selector).first
    if not await active_pane.is_visible():
        return ""
    return str(await active_pane.get_attribute("data-step") or "").strip()


async def _wait_for_timeline_step_change(
    page: Page,
    active_pane_selector: str,
    previous_step: str,
    timeout_ms: int = 30000,
) -> str:
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        current_step = await _active_timeline_step(page, active_pane_selector)
        if current_step and current_step != previous_step:
            return current_step
        await asyncio.sleep(0.25)
    raise RuntimeError(
        f"NAS timeline did not advance from step {previous_step or 'unknown'}"
    )


def _build_member_attachment_plan(
    documents: list[dict[str, str]],
) -> list[tuple[str, Path]]:
    planned: list[tuple[str, Path]] = []
    occupied_fields: set[str] = set()

    for document in documents:
        field_name = str(
            document.get("nas_field") or "other_attachment"
        ).strip()
        if field_name not in _NAS_ATTACHMENT_FIELDS:
            field_name = "other_attachment"

        if field_name in occupied_fields:
            if "other_attachment" not in occupied_fields:
                field_name = "other_attachment"
            else:
                raise RuntimeError(
                    "NAS has no available attachment field for document "
                    f"'{document.get('document_type') or document.get('path')}'"
                )

        file_path = Path(str(document.get("path") or "")).expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"NAS member attachment was not found: {file_path}")
        if file_path.suffix.lower() not in _NAS_ATTACHMENT_ALLOWED_EXTENSIONS:
            raise ValueError(
                "NAS member attachment type is not allowed: "
                f"{file_path.name}"
            )
        if file_path.stat().st_size > _NAS_ATTACHMENT_MAX_BYTES:
            raise ValueError(
                "NAS member attachment exceeds the portal's 3 MB limit: "
                f"{file_path.name}"
            )

        occupied_fields.add(field_name)
        planned.append((field_name, file_path))

    return planned


async def _wait_for_attachment_upload(
    page: Page,
    completion_selector: str,
    expected_filename: str,
    timeout_ms: int = 60000,
) -> None:
    completion = page.locator(completion_selector).first
    await completion.wait_for(state="attached", timeout=timeout_ms)
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        current_value = str(await completion.input_value() or "").strip()
        if Path(current_value).name.casefold() == expected_filename.casefold():
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"NAS attachment upload did not complete for {expected_filename}"
    )


async def _upload_member_attachments(
    page: Page,
    selectors: Dict[str, Any],
    documents: list[dict[str, str]],
    member_name: str,
    member_user_id: str,
    logger: logging.Logger,
) -> None:
    plan = _build_member_attachment_plan(documents)
    if not plan:
        logger.info(
            "No NAS attachments available for member | Member=%s | UserId=%s",
            member_name,
            member_user_id or "-",
        )
        return

    for field_name, file_path in plan:
        input_selector = ensure_selector_present(
            selectors,
            f"attachment_{field_name}_input",
            logger,
        )
        completion_selector = ensure_selector_present(
            selectors,
            f"attachment_{field_name}_complete",
            logger,
        )
        file_input = page.locator(input_selector).first
        await file_input.wait_for(state="attached", timeout=30000)
        await file_input.set_input_files(str(file_path))
        await _wait_for_attachment_upload(
            page=page,
            completion_selector=completion_selector,
            expected_filename=file_path.name,
        )
        logger.info(
            "Uploaded NAS member attachment | Member=%s | UserId=%s | "
            "Field=%s | File=%s",
            member_name,
            member_user_id or "-",
            field_name,
            file_path.name,
        )


async def _select_bulk_policy(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    payer_selector = ensure_selector_present(selectors, "payer_accordion", logger)
    payer_name = (
        _normalize_text(values.get("resolved_payer_name"))
        or _normalize_text(values.get("accordion_text"))
        or DEFAULT_ACCORDION_TEXT
    )
    payer = None
    payer_candidates = page.locator(payer_selector)
    await payer_candidates.first.wait_for(state="visible", timeout=60000)
    for index in range(await payer_candidates.count()):
        candidate = payer_candidates.nth(index)
        if _normalize_text(await candidate.inner_text()).casefold() == payer_name.casefold():
            payer = candidate
            break
    if payer is None:
        raise RuntimeError(f"NAS bulk payer accordion not found: {payer_name}")

    await payer.click()
    await _wait_after_click(page)
    logger.info("NAS bulk payer selected: %s", payer_name)

    policy_filter_selector = ensure_selector_present(selectors, "policy_filter", logger)
    policy_filter = page.locator(policy_filter_selector).first
    filter_value = _normalize_text(values.get("company_name"))
    try:
        if filter_value and await policy_filter.is_visible():
            await policy_filter.fill(filter_value)
            await asyncio.sleep(0.5)
            logger.info("NAS bulk policy filter filled: %s", filter_value)
    except Exception:
        logger.warning("NAS bulk policy filter was not available; continuing with card matching")

    card_selector = ensure_selector_present(selectors, "policy_card", logger)
    contract_link_selector = ensure_selector_present(selectors, "policy_contract_link", logger)
    upload_button_selector = ensure_selector_present(selectors, "upload_members_button", logger)
    raw_contract_name = _normalize_text(values.get("contract_name"))
    contract_name = normalize_bulk_contract_name(raw_contract_name)
    canonical_contract_name = _canonical_contract_text(contract_name)
    if raw_contract_name != contract_name:
        logger.info(
            "NAS bulk contract name normalized | Raw=%s | MatchValue=%s",
            raw_contract_name,
            contract_name,
        )

    cards = page.locator(card_selector)
    await cards.first.wait_for(state="visible", timeout=60000)
    matched_cards: list[tuple[int, Locator]] = []
    for index in range(await cards.count()):
        card = cards.nth(index)
        upload_button = await _first_visible_enabled(card.locator(upload_button_selector))
        if upload_button is None:
            continue

        card_text = _normalize_text(await card.inner_text())
        if contract_name:
            link_texts = [
                _normalize_text(text)
                for text in await card.locator(contract_link_selector).all_inner_texts()
            ]
            candidate_texts = [_canonical_contract_text(card_text)]
            candidate_texts.extend(_canonical_contract_text(text) for text in link_texts)
            if not any(canonical_contract_name in candidate for candidate in candidate_texts):
                continue

        matched_cards.append((len(card_text), upload_button))

    if matched_cards:
        _, upload_button = min(matched_cards, key=lambda item: item[0])
        await upload_button.click()
        await _wait_after_click(page)
        logger.info(
            "NAS bulk upload policy selected%s",
            f": {contract_name}" if contract_name else "",
        )
        return

    visible_buttons = page.locator(upload_button_selector)
    visible_matches: list[Locator] = []
    for index in range(await visible_buttons.count()):
        candidate = visible_buttons.nth(index)
        if await candidate.is_visible() and await candidate.is_enabled():
            visible_matches.append(candidate)

    if len(visible_matches) == 1:
        await visible_matches[0].click()
        await _wait_after_click(page)
        logger.warning("NAS bulk policy selected using the only visible Upload Members button")
        return

    raise RuntimeError(
        "NAS bulk Upload Members button could not be uniquely matched"
        + (f" for ContractName: {contract_name}" if contract_name else "")
    )


async def _upload_bulk_excel(
    page: Page,
    selectors: Dict[str, Any],
    excel_path: str,
    download_dir: Path,
    logger: logging.Logger,
) -> None:
    resolved_path = Path(excel_path).expanduser().resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(
            "NAS bulk member Excel file was not found. "
            f"Expected: {resolved_path}. Set NAS_BULK_MEMBER_FILE to override this path."
        )

    file_input_selector = ensure_selector_present(selectors, "excel_file_input", logger)
    save_button_selector = ensure_selector_present(selectors, "import_save_button", logger)
    member_links_selector = ensure_selector_present(selectors, "member_links", logger)

    file_input = page.locator(file_input_selector).first
    await file_input.wait_for(state="attached", timeout=60000)
    await file_input.set_input_files(str(resolved_path))
    logger.info("NAS bulk member Excel uploaded: %s", resolved_path)

    save_button = page.locator(save_button_selector).first
    await save_button.wait_for(state="visible", timeout=30000)

    download_task = asyncio.create_task(
        page.wait_for_event("download", timeout=60000)
    )
    member_page_task = asyncio.create_task(
        page.locator(member_links_selector).first.wait_for(
            state="visible",
            timeout=60000,
        )
    )

    await save_button.click()
    await _wait_after_click(page, timeout_ms=30000)

    try:
        done, _ = await asyncio.wait(
            {download_task, member_page_task},
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
                        or "nas_bulk_validation_errors.xlsx"
                    )
                ).name
                output_path = download_dir / f"nas_validation_{suggested_name}"
                await download.save_as(str(output_path))
                logger.error(
                    "NAS bulk upload validation workbook downloaded: %s",
                    output_path,
                )
                raise NasBulkValidationDownloadError(
                    "NAS rejected the uploaded member Excel file and returned a "
                    "validation workbook. Review the attached Excel file and "
                    "correct the invalid member data.",
                    downloaded_file=output_path,
                )

        if member_page_task in done:
            member_page_task.result()
        else:
            raise RuntimeError(
                "NAS bulk import Save completed, but neither a validation workbook "
                "download nor the member timeline page appeared"
            )
    finally:
        for task in (download_task, member_page_task):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, PlaywrightTimeoutError):
                await task

    logger.info("NAS bulk import saved; member timeline page is ready")


async def _submit_member_timeline(
    page: Page,
    selectors: Dict[str, Any],
    member_id: str,
    member_name: str,
    member_index: int,
    member_user_id: str,
    member_documents: list[dict[str, str]],
    screenshot_dir: Path,
    logger: logging.Logger,
    skip_submit: bool = False,
    max_steps: int = 12,
) -> Path:
    next_selector = ensure_selector_present(selectors, "timeline_next_button", logger)
    submit_selector = ensure_selector_present(selectors, "timeline_submit_button", logger)
    attachments_pane_selector = ensure_selector_present(
        selectors,
        "attachments_pane",
        logger,
    )
    notes_pane_selector = ensure_selector_present(selectors, "notes_pane", logger)
    actions_pane_selector = ensure_selector_present(selectors, "actions_pane", logger)
    active_pane_selector = ensure_selector_present(
        selectors,
        "active_timeline_pane",
        logger,
    )

    member_link = page.locator(f"#{member_id}")
    await member_link.wait_for(state="visible", timeout=30000)
    await member_link.click()
    await _wait_after_click(page)
    logger.info("NAS bulk member opened: %s", member_name)

    attachments_uploaded = False
    notes_visited = False
    for step_number in range(1, max_steps + 1):
        attachments_pane = page.locator(attachments_pane_selector).first
        if not attachments_uploaded and await attachments_pane.is_visible():
            await _upload_member_attachments(
                page=page,
                selectors=selectors,
                documents=member_documents,
                member_name=member_name,
                member_user_id=member_user_id,
                logger=logger,
            )
            attachments_uploaded = True

        if await page.locator(notes_pane_selector).first.is_visible():
            notes_visited = True

        submit_button = await _first_visible_enabled(page.locator(submit_selector))
        if submit_button is not None:
            if member_documents and not attachments_uploaded:
                raise RuntimeError(
                    "NAS member reached Submit before the Attachments tab was processed: "
                    f"{member_name}"
                )
            if not notes_visited:
                raise RuntimeError(
                    "NAS member reached Submit before the Notes tab was visited: "
                    f"{member_name}"
                )
            if not await page.locator(actions_pane_selector).first.is_visible():
                raise RuntimeError(
                    "NAS Submit request button appeared outside the Actions tab: "
                    f"{member_name}"
                )
            evidence_state = "reviewed" if skip_submit else "submitted"
            if skip_submit:
                logger.warning(
                    "NAS bulk member reached Submit but click was skipped for testing: "
                    "%s | TimelineSteps=%s",
                    member_name,
                    step_number - 1,
                )
            else:
                await submit_button.click()
                await _wait_after_click(page, timeout_ms=30000)
                logger.info(
                    "NAS bulk member submitted: %s | TimelineSteps=%s",
                    member_name,
                    step_number - 1,
                )

            screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_name = (
                f"member_{member_index:03d}_"
                f"{_safe_file_part(member_user_id, 'unmapped')}_"
                f"{_safe_file_part(member_name, 'member')}_"
                f"{evidence_state}.jpg"
            )
            screenshot_path = screenshot_dir / screenshot_name
            await page.screenshot(
                path=str(screenshot_path),
                type="jpeg",
                quality=55,
                full_page=True,
            )
            logger.info(
                "Saved NAS member evidence screenshot | Member=%s | UserId=%s | Path=%s",
                member_name,
                member_user_id or "-",
                screenshot_path,
            )
            return screenshot_path

        next_button = await _first_visible_enabled(page.locator(next_selector))
        if next_button is None:
            raise RuntimeError(
                f"NAS bulk member timeline stalled for '{member_name}': "
                "neither Next nor Submit is visible and enabled"
            )

        previous_step = await _active_timeline_step(page, active_pane_selector)
        await next_button.click()
        current_step = await _wait_for_timeline_step_change(
            page=page,
            active_pane_selector=active_pane_selector,
            previous_step=previous_step,
            timeout_ms=30000,
        )
        logger.info(
            "NAS bulk member timeline advanced: %s | Loop=%s | FromStep=%s | ToStep=%s",
            member_name,
            step_number,
            previous_step or "-",
            current_step,
        )

    raise RuntimeError(
        f"NAS bulk member Submit did not appear within {max_steps} timeline steps "
        f"for '{member_name}'"
    )


async def _submit_all_imported_members(
    page: Page,
    selectors: Dict[str, Any],
    member_user_ids: list[str],
    expected_member_names: list[str],
    member_documents_by_user: dict[str, list[dict[str, str]]],
    screenshot_dir: Path,
    logger: logging.Logger,
    skip_submit: bool = False,
) -> NasBulkAddResult:
    member_links_selector = ensure_selector_present(selectors, "member_links", logger)
    member_links = page.locator(member_links_selector)
    await member_links.first.wait_for(state="visible", timeout=60000)

    members: list[tuple[str, str]] = []
    for index in range(await member_links.count()):
        link = member_links.nth(index)
        member_id = str(await link.get_attribute("id") or "").strip()
        member_name = _normalize_text(await link.inner_text()) or f"Member {index + 1}"
        if member_id:
            members.append((member_id, member_name))

    if not members:
        raise RuntimeError("NAS bulk import displayed no member records")

    logger.info("NAS bulk members discovered: %s", len(members))
    screenshots: list[Path] = []
    for member_index, (member_id, member_name) in enumerate(members, start=1):
        member_user_id = (
            member_user_ids[member_index - 1]
            if member_index <= len(member_user_ids)
            else ""
        )
        expected_member_name = (
            expected_member_names[member_index - 1]
            if member_index <= len(expected_member_names)
            else ""
        )
        if expected_member_name:
            expected_canonical = _canonical_member_name(expected_member_name)
            actual_canonical = _canonical_member_name(member_name)
            if (
                expected_canonical not in actual_canonical
                and actual_canonical not in expected_canonical
            ):
                raise RuntimeError(
                    "NAS imported member order does not match the generated census | "
                    f"Index={member_index} | UserId={member_user_id} | "
                    f"Expected={expected_member_name} | Portal={member_name}"
                )
        screenshot = await _submit_member_timeline(
            page=page,
            selectors=selectors,
            member_id=member_id,
            member_name=member_name,
            member_index=member_index,
            member_user_id=member_user_id,
            member_documents=member_documents_by_user.get(member_user_id, []),
            screenshot_dir=screenshot_dir,
            logger=logger,
            skip_submit=skip_submit,
        )
        screenshots.append(screenshot)

    if skip_submit:
        logger.info(
            "NAS bulk member timelines reviewed without submission: %s",
            len(members),
        )
    else:
        logger.info("NAS bulk member timelines submitted: %s", len(members))
    return NasBulkAddResult(
        processed_count=len(members),
        member_screenshots=screenshots,
    )


async def run_bulk_add_member(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    download_dir: Path,
    logger: logging.Logger,
) -> NasBulkAddResult:
    logger.info("NAS bulk add-member process started")
    excel_path = str(values.get("batch_member_file") or "").strip()
    if not excel_path:
        raise ValueError("NAS batch_member_file is required for bulk member upload")

    skip_submit = bool(values.get("skip_member_submit", False))
    if skip_submit:
        logger.warning(
            "NAS bulk member Submit clicks are disabled for this testing run"
        )

    await _select_bulk_policy(page, selectors, values, logger)
    await _upload_bulk_excel(
        page,
        selectors,
        excel_path,
        download_dir,
        logger,
    )
    result = await _submit_all_imported_members(
        page,
        selectors,
        member_user_ids=[
            str(value).strip()
            for value in values.get("member_user_ids", [])
            if str(value).strip()
        ],
        expected_member_names=[
            str(value).strip()
            for value in values.get("member_names", [])
            if str(value).strip()
        ],
        member_documents_by_user={
            str(user_id): list(documents)
            for user_id, documents in dict(
                values.get("member_documents_by_user") or {}
            ).items()
        },
        screenshot_dir=Path(download_dir) / "member_screenshots",
        logger=logger,
        skip_submit=skip_submit,
    )
    logger.info(
        "NAS bulk add-member process completed | Members=%s | Submitted=%s",
        result.processed_count,
        not skip_submit,
    )
    return result
