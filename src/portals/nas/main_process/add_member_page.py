from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def open_add_member_page(
    page: Page,
    selectors: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS add member page started")

    await run_actions(
        page,
        actions=[
            {
                "type": "click",
                "key": "add_member_button",
                "label": "NAS Add Member",
                "timeout_ms": 60000,
                "wait_for_load": True,
                "wait_for_loader": False,
                "next_key": "accordion_header",
                "next_label": "NAS Company Accordion",
                "next_timeout_ms": 60000,
            },
        ],
        selectors=selectors,
        values={},
        logger=logger,
    )

    logger.info("NAS add member page completed")
