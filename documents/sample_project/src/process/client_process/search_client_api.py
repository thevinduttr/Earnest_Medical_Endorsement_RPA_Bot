from __future__ import annotations
from typing import Dict, Any, List, Optional
import pandas as pd
import logging
from pathlib import Path
import asyncio
from playwright.async_api import Page

# Import your existing utilities
from src.utils.support_functions import wait_for_next_step, run_actions
from src.utils.load_data import load_yaml_file

async def search_client_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str,
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Perform the Search Client process via API and return:
      - (True, None)  -> No duplicates found (New customer)
      - (False, match_info) -> Duplicates found (Existing customer with match details)
    """
    logger.info("Search Client process (API Mode) started")

    # Define tab closing action for cleanup
    close_tab_action = [
        {"type": "click", "key": "tab", "label": "Opened Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"}
    ]
    
    # 1. Prepare Search Data
    search_data = {}
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0]
            
            # Extract and merge firstname and lastname for client name
            first_name = str(row.get("FirstName", "") or "").strip()
            last_name = str(row.get("LastName", "") or "").strip()
            
            # Create client name by merging firstname and lastname
            client_name = ""
            if first_name and last_name:
                client_name = f"{first_name} {last_name}".strip()
            elif first_name:
                client_name = first_name
            elif last_name:
                client_name = last_name
            
            search_data = {
                "emirates_id": str(row.get("EmiratesID", "") or "").strip(),
                "mobile": str(row.get("Mobile_CRM", "") or "").strip(),
                "email": str(row.get("Email_CRM", "") or "").strip(),
                "client_name": client_name,
            }
    except Exception as e:
        logger.error(f"Failed to read values from df: {e}")
        return False

    # 2. Scrape Session Key
    session_key = None
    table_selector = 'table[id^="tableClient__ClientSearchModel"]'
    try:
        try:
            await page.wait_for_selector(table_selector, timeout=15000)
        except:
            logger.warning("Search grid not found immediately.")

        table_el = page.locator(table_selector).first
        table_id = await table_el.get_attribute("id")
        if table_id:
            session_key = table_id.replace("tableClient__", "")
            logger.info(f"Scraped Session Key: {session_key}")
    except Exception as e:
        logger.error(f"Failed to scrape Session Key: {e}")

    if not session_key:
        logger.error("CRITICAL: Could not find __SESSIONKEY. API call will fail.")
        return False

    # 3. API Search Strategy
    checks_to_run = [
        ("Emirates ID", "ClientSearch.EmirateId", search_data.get("emirates_id")),
        ("Mobile",      "ClientSearch.MobileNo",  search_data.get("mobile")),
        ("Email",       "ClientSearch.EmailId",   search_data.get("email")),
        ("Client Name", "ClientSearch.ClientName", search_data.get("client_name"))
    ]

    api_url = "https://eibcms-uat.earnestins.ae/ClientSearch/GetClientData"
    duplicate_found = False
    match_info = None
    
    for label, param_key, value in checks_to_run:
        if not value: continue

        logger.info(f"API Checking {label}: '{value}'")
        
        # Build API Params
        current_params = {
            "SearchFlag": "ADS",
            "ClearCallType": "Y",
            "__SESSIONKEY": session_key,
            "ColumnSelection": "ClientType,OtherContactDetails,Address,GroupClient,GroupClientFlag,Broker,BirthDate,AnniversaryDate",
            "ClientSearch.ClientCode": "",
            "ClientSearch.ClientName": "",
            "ClientSearch.IsGroupClient": "",
            "ClientSearch.IsEmirate_TLExpired": "false",
            "ClientSearchTableLoaded": "",
            "ClientSearch.EmirateId": "",
            "ClientSearch.MobileNo": "",
            "ClientSearch.EmailId": "",
        }
        current_params[param_key] = value

        try:
            response = await page.request.post(
                api_url,
                params=current_params,
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest"}
            )

            if not response.ok: continue

            data = await response.json()
            records_count = data.get("records", 0)
            rows = data.get("rows", [])

            if records_count > 0:
                logger.info(f"Existing customer found by {label}: '{value}' ({records_count} matches). Will proceed with selecting existing client.")
                
                # Store match information
                match_info = {
                    "matched_by": label,
                    "matched_value": value,
                    "match_count": records_count
                }
                
                # Close Tab & Continue (no email sent as per CR update)
                try:
                    await run_actions(page, actions=close_tab_action, selectors=selectors_group, df=df, logger=logger, run_id=run_id)
                except Exception: pass
                
                duplicate_found = True
                break 

        except Exception as e:
            logger.error(f"Error checking {label}: {e}")

    if duplicate_found:
        return False, match_info
    else:
        logger.info("API Check: No duplicates found. (New Customer)")
        try:
            await run_actions(page, actions=close_tab_action, selectors=selectors_group, df=df, logger=logger, run_id=run_id)
            await asyncio.sleep(0.3)
        except Exception: pass
        return True, None