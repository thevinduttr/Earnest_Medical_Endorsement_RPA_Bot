from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def fill_sponsor_details_section(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
):
    logger.info("Sponsor details section started")

    actions: List[Dict[str, Any]] = [
        {
            "type": "select",
            "key": "sponsor_type",
            "label": "Sponsor Type",
            "value_key": "sponsor_type",
        },
        {
            "type": "fill",
            "key": "sponsor_uid",
            "label": "Sponsor UID",
            "value_key": "sponsor_uid",
        },
        {
            "type": "fill",
            "key": "sponsor_contact_number",
            "label": "Sponsor Contact Number",
            "value_key": "sponsor_contact_number",
        },
        {
            "type": "fill",
            "key": "sponsor_email",
            "label": "Sponsor Email",
            "value_key": "sponsor_email",
        },
        {
            "type": "click",
            "key": "step3_next_button",
            "label": "Sponsor Next",
            "wait_for_load": True,
            "wait_for_loader": True,
            "next_key": "supporting_document_input",
            "next_label": "Upload Section Ready",
            "next_timeout_ms": 30000,
            "timeout_ms": 30000,
            "post_wait_ms": 500,
        },
    ]

    await run_actions(
        page,
        actions=actions,
        selectors=selectors,
        values=values,
        logger=logger,
        enforce_session_active=True,
        skip_empty_values=True,
    )

    logger.info("Sponsor details section completed")
