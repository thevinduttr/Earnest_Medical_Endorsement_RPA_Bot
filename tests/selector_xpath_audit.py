from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from playwright.async_api import Page, async_playwright

from src.portals.sukoon.add_process.batch_process.batch_add_member import _open_batch_member_page
from src.portals.sukoon.add_process.manual_process.manual_add_member import _open_manual_member_page
from src.portals.sukoon.main_process.login import login
from src.utils.load_data import load_json_file, load_section_from_yaml, load_yaml_file


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("selector_xpath_audit")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


async def _generate_xpath_for_selector(page: Page, selector: str) -> str | None:
    js = """
    (selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;

      function xpath(node) {
        if (!node || node.nodeType !== 1) return '';
        if (node.id) return `//*[@id=\"${node.id}\"]`;
        const siblings = node.parentNode ? Array.from(node.parentNode.children).filter(n => n.tagName === node.tagName) : [];
        const index = siblings.length > 1 ? `[${siblings.indexOf(node) + 1}]` : '';
        const segment = `${node.tagName.toLowerCase()}${index}`;
        const parent = xpath(node.parentNode);
        return parent ? `${parent}/${segment}` : `/${segment}`;
      }

      return xpath(el);
    }
    """
    try:
        return await page.evaluate(js, selector)
    except Exception:
        return None


async def _audit_selectors(page: Page, section_name: str, selectors: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for key, selector in selectors.items():
        selector_str = str(selector).strip()
        if not selector_str:
            results.append(
                {
                    "section": section_name,
                    "key": key,
                    "selector": selector,
                    "match_count": 0,
                    "status": "FAIL",
                    "reason": "Empty selector",
                    "generated_xpath": None,
                }
            )
            continue

        count = 0
        visible_count = 0
        try:
            loc = page.locator(selector_str)
            count = await loc.count()
            for i in range(count):
                try:
                    if await loc.nth(i).is_visible():
                        visible_count += 1
                except Exception:
                    continue
        except Exception as exc:
            results.append(
                {
                    "section": section_name,
                    "key": key,
                    "selector": selector_str,
                    "match_count": 0,
                    "visible_count": 0,
                    "status": "FAIL",
                    "reason": f"Locator evaluation error: {exc}",
                    "generated_xpath": None,
                }
            )
            continue

        generated_xpath = await _generate_xpath_for_selector(page, selector_str)

        if count > 0:
            status = "PASS"
            reason = "Matched in DOM"
        else:
            status = "FAIL"
            reason = "No matches in DOM"

        results.append(
            {
                "section": section_name,
                "key": key,
                "selector": selector_str,
                "match_count": count,
                "visible_count": visible_count,
                "status": status,
                "reason": reason,
                "generated_xpath": generated_xpath,
            }
        )

    return results


async def main() -> int:
    logger = _make_logger()

    config = load_yaml_file("config/base.yml")
    login_values = load_json_file("config/json_values/login.json")

    login_selectors = load_section_from_yaml("locators/sukoon/main/login_page.yml", section="login")
    dashboard_selectors = load_section_from_yaml("locators/sukoon/main/dashboard_page.yml", section="dashboard")
    manual_selectors = load_section_from_yaml(
        "locators/sukoon/add_process/manual_add_member.yml", section="manual_add_member"
    )
    batch_selectors = load_section_from_yaml(
        "locators/sukoon/add_process/batch_add_member.yml", section="batch_add_member"
    )

    base_url = str(config.get("paths", {}).get("base_url") or "https://medical.sukoon.com/")

    run_id = datetime.now().strftime("xpath_audit_%Y-%m-%d_%H-%M-%S")
    out_dir = Path("data/outputs") / "xpath_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{run_id}.json"

    all_results: List[Dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 945})
        page = await context.new_page()

        try:
            await page.goto(base_url, wait_until="domcontentloaded")

            await login(
                page=page,
                login_values=login_values,
                login_selectors=login_selectors,
                dashboard_selectors=dashboard_selectors,
                logger=logger,
            )

            await _open_manual_member_page(page, manual_selectors, logger)
            all_results.extend(await _audit_selectors(page, "manual_add_member", manual_selectors))

            await page.goto("https://medical.sukoon.com/PolicyServicing/Dashboard/Overview", wait_until="domcontentloaded")
            await _open_batch_member_page(page, batch_selectors, logger)
            all_results.extend(await _audit_selectors(page, "batch_add_member", batch_selectors))

        finally:
            await context.close()
            await browser.close()

    failures = [r for r in all_results if r.get("status") != "PASS"]
    report = {
        "run_id": run_id,
        "report_file": str(report_path),
        "total": len(all_results),
        "passed": len(all_results) - len(failures),
        "failed": len(failures),
        "results": all_results,
    }

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info("XPath/selector audit report written: %s", report_path)
    logger.info("Audit summary -> total=%s passed=%s failed=%s", report["total"], report["passed"], report["failed"])

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
