from __future__ import annotations

from typing import Any, Dict
import logging

from playwright.async_api import Page

from src.utils.support_functions import run_actions


def _resolve_dashboard_action(process_key: str) -> Dict[str, Any]:
    process = str(process_key or "").strip().lower()
    if process == "add_individual":
        return {
            "key": "add_member_button",
            "label": "NAS Add Member",
            "next_key": "accordion_header",
            "next_label": "NAS Company Accordion",
        }

    if process == "add_batch":
        return {
            "key": "add_bulk_member_button",
            "label": "NAS Add Bulk Members",
            "next_key": None,
            "next_label": None,
        }

    if process == "add_family":
        return {
            "key": "add_bulk_member_button",
            "label": "NAS Add Bulk Members",
            "next_key": None,
            "next_label": None,
        }

    if process == "delete_bulk":
        return {
            "key": "cancel_bulk_member_button",
            "label": "NAS Cancel Bulk Members",
            "next_key": "import_choose_file_button",
            "next_label": "NAS Bulk Delete Import",
        }

    raise ValueError(f"Unsupported NAS request dashboard process: {process_key}")


async def open_request_dashboard_page(
    page: Page,
    selectors: Dict[str, Any],
    process_key: str,
    logger: logging.Logger,
) -> None:
    action = _resolve_dashboard_action(process_key)
    logger.info(f"NAS request dashboard started | ProcessKey={process_key}")

    click_action = {
        "type": "click",
        "key": action["key"],
        "label": action["label"],
        "timeout_ms": 60000,
        "wait_for_load": True,
        "wait_for_loader": False,
    }
    if action["next_key"]:
        click_action.update(
            {
                "next_key": action["next_key"],
                "next_label": action["next_label"],
                "next_timeout_ms": 60000,
            }
        )

    await run_actions(
        page,
        actions=[click_action],
        selectors=selectors,
        values={},
        logger=logger,
    )

    logger.info(f"NAS request dashboard completed | ProcessKey={process_key}")

