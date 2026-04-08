from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def fill_upload_member_files_section(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    upload_paths: Dict[str, Any],
    logger: logging.Logger,
):
    logger.info("Upload member files section started")

    run_values: Dict[str, Any] = dict(values or {})
    run_values.update(upload_paths or {})

    actions: List[Dict[str, Any]] = [
        {
            "type": "upload",
            "key": "supporting_document_input",
            "label": "Upload Supporting File 1",
            "value_key": "supporting_file_1",
            "required": False,
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "upload",
            "key": "supporting_document_input",
            "label": "Upload Supporting File 2",
            "value_key": "supporting_file_2",
            "required": False,
            "wait_for_load": True,
            "wait_for_loader": True,
            "timeout_ms": 30000,
        },
        {
            "type": "fill",
            "key": "upload_comments",
            "label": "Upload Comments",
            "value_key": "upload_comments",
            "required": False,
        },
    ]

    await run_actions(
        page,
        actions=actions,
        selectors=selectors,
        values=run_values,
        logger=logger,
        enforce_session_active=True,
    )

    if bool(values.get("click_reset_after_upload", False)):
        await run_actions(
            page,
            actions=[
                {
                    "type": "click",
                    "key": "step4_reset_button",
                    "label": "Reset Upload Section",
                    "wait_for_load": True,
                    "wait_for_loader": True,
                    "timeout_ms": 30000,
                }
            ],
            selectors=selectors,
            values=run_values,
            logger=logger,
            enforce_session_active=True,
        )

    logger.info("Upload member files section completed")
