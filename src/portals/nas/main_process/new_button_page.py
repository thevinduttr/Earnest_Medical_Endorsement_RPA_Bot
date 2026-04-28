from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def open_new_member_page(
    page: Page,
    selectors: Dict[str, Any],
    logger: logging.Logger,
) -> None:
    logger.info("NAS new button page started")

    await run_actions(
        page,
        actions=[
            {
                "type": "click",
                "key": "new_button",
                "label": "NAS New Button",
                "timeout_ms": 60000,
                "wait_for_load": True,
                "wait_for_loader": False,
                "next_key": "add_member_button",
                "next_label": "NAS Add Member Button",
                "next_timeout_ms": 60000,
            },
        ],
        selectors=selectors,
        values={},
        logger=logger,
    )

    logger.info("NAS new button page completed")
