from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.services.census_service.sukoon.common import load_request_members_dataframe
from src.services.db_service.azure_db_connection import AzureSQLConnection

# Locators for SearchBeneficiary.aspx
FAMILY_SEARCH_SELECTORS = {
    "search_view_button": "#cphNasHrMasterBody_btnSearchView",
    "card_id_search_input": "#cphNasHrMasterBody_txtCardIDSearch",
    "name_search_input": "#cphNasHrMasterBody_txtNameSearch",
    "search_beneficiaries_button": "#cphNasHrMasterBody_btnSearchBeneficiaries",
    "member_name_row": "#cphNasHrMasterBody_rptMembers_lblMemberName_0",
    "family_member_name_link": "#aFamilyMemberName",
    "details_container": "#cphNasHrMasterBody_upMembersSearch",
    "card_id_h6": "#cphNasHrMasterBody_upMembersSearch h6:nth-of-type(1)",
    "close_details_span": "#cphNasHrMasterBody_upMembersSearch > div > div.row > div > span",
}


def resolve_principal_name(row: dict, all_members: list, policy_number: str, logger: logging.Logger) -> str | None:
    """
    Tries to resolve the name of the principal member associated with the given family member row.
    """
    # 1. Search the request's members for a principal (Employee/Principal relation)
    principals = [
        m for m in all_members
        if str(m.get("Relation") or "").strip().upper() in {"EMPLOYEE", "PRINCIPAL", ""}
    ]

    # Try unique match by SponsorId matching StaffId
    sponsor_id = str(row.get("SponsorId") or "").strip()
    if sponsor_id:
        for p in principals:
            p_staff_id = str(p.get("StaffId") or "").strip()
            if p_staff_id and p_staff_id == sponsor_id:
                name = " ".join(part for part in (p.get("FirstName"), p.get("MiddleName"), p.get("LastName")) if part)
                logger.info(f"Resolved principal name '{name}' from request using SponsorId matching StaffId.")
                return name

    # If there's exactly one principal in the request, assume it's the principal
    if len(principals) == 1:
        p = principals[0]
        name = " ".join(part for part in (p.get("FirstName"), p.get("MiddleName"), p.get("LastName")) if part)
        logger.info(f"Resolved principal name '{name}' as the unique principal in the same request.")
        return name

    # 2. If SponsorId contains letters and spaces (a name format), use it directly
    if sponsor_id and any(c.isalpha() for c in sponsor_id) and len(sponsor_id.split()) > 1:
        logger.info(f"Using SponsorId '{sponsor_id}' directly as principal name.")
        return sponsor_id

    # 3. Query the DB to find historical principal records matching SponsorId under the same policy
    if sponsor_id:
        query = """
        SELECT TOP 1 FirstName, MiddleName, LastName
        FROM [dbo].[EndorsementRequestsMemberData]
        WHERE (StaffId = ? OR EmiratesId = ? OR UnifiedNo = ? OR UserId = ?)
          AND PolicyNumber = ?
          AND Relation IN ('Employee', 'Principal', '', 'Others')
        ORDER BY CreatedAt DESC
        """
        try:
            with AzureSQLConnection(logger=logger) as db_connection:
                conn = db_connection.connect()
                cursor = conn.cursor()
                cursor.execute(query, [sponsor_id, sponsor_id, sponsor_id, sponsor_id, policy_number])
                row_db = cursor.fetchone()
                if row_db:
                    name = " ".join(part for part in row_db if part)
                    logger.info(f"Resolved principal name '{name}' from past records matching SponsorId='{sponsor_id}'.")
                    return name
        except Exception as e:
            logger.warning(f"Failed DB principal lookup for SponsorId '{sponsor_id}': {e}")

    return None


def update_member_principal_card_no(request_id: str, user_id: str, principal_card_no: str, logger: logging.Logger) -> None:
    """
    Updates the PrincipalCardNo column in the DB for the given request_id and user_id.
    """
    query = """
    UPDATE [dbo].[EndorsementRequestsMemberData]
    SET PrincipalCardNo = ?,
        UpdatedAt = SYSUTCDATETIME()
    WHERE RequestId = ? AND UserId = ?
    """
    with AzureSQLConnection(logger=logger) as db_connection:
        conn = db_connection.connect()
        cursor = conn.cursor()
        cursor.execute(query, [principal_card_no, request_id, user_id])
        conn.commit()
        logger.info(f"Updated database | RequestId={request_id} | UserId={user_id} | PrincipalCardNo={principal_card_no}")


async def run_family_member_search(
    page: Page,
    request_id: str,
    request_user_ids: list[str],
    run_dir: Path,
    logger: logging.Logger,
) -> None:
    """
    Orchestrates the principal card number search, details extraction, screenshot capture, and database updates.
    """
    logger.info("NAS family member search process started")

    # Load all request members
    members_df = load_request_members_dataframe(
        request_id=request_id,
        portal_name="NAS",
        request_type="ADD",
        include_user_ids=request_user_ids,
        logger=logger,
    )
    all_members = members_df.to_dict(orient="records")

    # Filter for family members (e.g. Spouse/Child/Others)
    family_members = [
        m for m in all_members
        if str(m.get("Relation") or "").strip().upper() not in {"EMPLOYEE", "PRINCIPAL", ""}
    ]

    if not family_members:
        logger.info("No family members found in this request; skipping search")
        return

    logger.info(f"Discovered {len(family_members)} family members to resolve")

    for member in family_members:
        user_id = str(member.get("UserId") or "").strip()
        first_name = str(member.get("FirstName") or "").strip()
        last_name = str(member.get("LastName") or "").strip()
        member_name = f"{first_name} {last_name}".strip()

        # Check if PrincipalCardNo is already present
        existing_card_no = str(member.get("PrincipalCardNo") or "").strip()
        if existing_card_no:
            logger.info(f"Family member {member_name} (UserId {user_id}) already has PrincipalCardNo: {existing_card_no}")
            continue

        policy_number = str(member.get("PolicyNumber") or "").strip()
        principal_name = resolve_principal_name(member, all_members, policy_number, logger)
        if not principal_name:
            logger.warning(f"Could not resolve principal name for family member {member_name} (UserId {user_id})")
            continue

        try:
            # 1. Navigate to search beneficiary page if not there
            if "SearchBeneficiary.aspx" not in page.url:
                search_view_btn = page.locator(FAMILY_SEARCH_SELECTORS["search_view_button"]).first
                await search_view_btn.wait_for(state="visible", timeout=30000)
                await search_view_btn.click()
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(1.0)

            # 2. Enter principal name
            name_input = page.locator(FAMILY_SEARCH_SELECTORS["name_search_input"]).first
            await name_input.wait_for(state="visible", timeout=30000)
            await name_input.fill(principal_name)

            card_input = page.locator(FAMILY_SEARCH_SELECTORS["card_id_search_input"]).first
            await card_input.fill("")

            # 3. Click Search Beneficiaries button
            search_btn = page.locator(FAMILY_SEARCH_SELECTORS["search_beneficiaries_button"]).first
            await search_btn.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2.0)

            # 4. Click result row
            member_name_row = page.locator(FAMILY_SEARCH_SELECTORS["member_name_row"]).first
            await member_name_row.wait_for(state="visible", timeout=30000)
            await member_name_row.click()
            await asyncio.sleep(1.0)

            # 5. Click the name link to view details
            family_link = page.locator(FAMILY_SEARCH_SELECTORS["family_member_name_link"]).first
            await family_link.wait_for(state="visible", timeout=30000)
            await family_link.click()
            await asyncio.sleep(1.5)

            # 6. Wait for details view and extract Card ID
            details_container = page.locator(FAMILY_SEARCH_SELECTORS["details_container"]).first
            await details_container.wait_for(state="visible", timeout=30000)

            card_id_h6 = page.locator(FAMILY_SEARCH_SELECTORS["card_id_h6"]).first
            await card_id_h6.wait_for(state="visible", timeout=30000)
            h6_text = await card_id_h6.inner_text()

            # Parse the Card ID: e.g. "MMFD-AFA8-H8H4-DHAM , Active since 17/Jun/2026 ,"
            card_id = h6_text.split(",")[0].strip()
            logger.info(f"Extracted Card ID '{card_id}' for principal '{principal_name}'")

            # 7. Take evidence screenshot
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", principal_name)
            screenshot_path = run_dir / f"principal_{safe_name}_details.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"Saved principal search screenshot to {screenshot_path}")

            # 8. Close details view
            close_span = page.locator(FAMILY_SEARCH_SELECTORS["close_details_span"]).first
            await close_span.click()
            await asyncio.sleep(1.0)

            # 9. Update the DB row
            update_member_principal_card_no(request_id, user_id, card_id, logger)

        except Exception as exc:
            logger.exception(f"Error searching principal '{principal_name}' for family member {member_name}: {exc}")
            raise

    # Navigate back to dashboard to restore state
    try:
        if "Dashboard.aspx" not in page.url:
            await page.goto("https://ntouch.nnhs.ae/BrokerConnect/Distributors/Dashboard.aspx", wait_until="domcontentloaded")
            await asyncio.sleep(1.0)
    except Exception as e:
        logger.warning(f"Failed to navigate back to dashboard: {e}")

    logger.info("NAS family member search process completed")
