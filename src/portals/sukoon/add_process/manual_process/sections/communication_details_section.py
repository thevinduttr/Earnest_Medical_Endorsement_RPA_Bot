from __future__ import annotations

from typing import Any, Dict, List
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


async def fill_communication_details_section(
    page: Page,
    selectors: Dict[str, Any],
    values: Dict[str, Any],
    logger: logging.Logger,
):
    logger.info("Communication details section started")

    actions: List[Dict[str, Any]] = [
        {
            "type": "select",
            "key": "communication_residential_location",
            "label": "Residential Location",
            "value_key": "residential_location",
        },
        {
            "type": "select",
            "key": "communication_work_location",
            "label": "Work Location",
            "value_key": "work_location",
        },
        {
            "type": "fill",
            "key": "communication_email",
            "label": "Communication Email",
            "value_key": "communication_email",
        },
        {
            "type": "fill",
            "key": "communication_mobile_number",
            "label": "Communication Mobile Number",
            "value_key": "communication_mobile_number",
        },
        {
            "type": "click",
            "key": "step2_next_button",
            "label": "Communication Next",
            "wait_for_load": True,
            "wait_for_loader": True,
            "next_key": "sponsor_type",
            "next_label": "Sponsor Section Ready",
            "next_timeout_ms": 30000,
            "timeout_ms": 30000,
            "post_wait_ms": 400,
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

    logger.info("Communication details section completed")
