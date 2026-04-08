from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page

from src.utils.support_functions import run_actions, upload_files_via_drop, wait_for_next_step, get_autofilled_input_value
from src.utils.load_data import load_section_from_yaml, load_yaml_file

from src.process.select_client import select_client_process
from src.process.prospect_process.vehicle_process.vehicle_process_main import vehicle_flow

async def create_prospect_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
    optout_data: Optional[Dict[str, Any]] = None,
) -> None:
    logger.info("Create Prospect process started (Cascading JS Injection Mode)")
    if optout_data:
        logger.info(f"OptOut data received - will set RenewalProcessingStatus to OPTOUT")
    selectors = selectors_group or {}
    row = df.iloc[0]

    # --- Step 1: Open Tab ---
    pre_upload_actions = [{"type": "click", "key": "tab", "label": "New Prospect Tab"}]
    await run_actions(page, actions=pre_upload_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)

    # --- Step 2: Select Client ---
    await select_client_process(page=page, df=df, logger=logger, run_id=run_id)
    await asyncio.sleep(2) 

    # --- SHARED JS INJECTOR FUNCTION (Enhanced Fuzzy Matching) ---
    js_injector = """
    (data) => {
        let results = { success: [], failed: [], details: [] };
        for (const [name, value] of Object.entries(data)) {
            const cleanValue = String(value).trim();
            const el = document.querySelector(`[name="${name}"]`);
            
            if (el) {
                el.focus();
                
                if (el.tagName === 'SELECT') {
                    let found = false;
                    let matchType = '';
                    
                    // Strategy 1: Try exact value match first
                    el.value = cleanValue;
                    if (el.value === cleanValue) {
                        found = true;
                        matchType = 'exact-value';
                    }

                    // Strategy 2: Try exact value match (uppercase)
                    if (!found) {
                        el.value = cleanValue.toUpperCase();
                        if (el.value === cleanValue.toUpperCase()) {
                            found = true;
                            matchType = 'exact-value-uppercase';
                        }
                    }

                    // Strategy 3: Exact text match (case-insensitive)
                    if (!found) {
                        for (let i = 0; i < el.options.length; i++) {
                            if (el.options[i].text.trim().toLowerCase() === cleanValue.toLowerCase()) {
                                el.selectedIndex = i;
                                found = true;
                                matchType = 'exact-text';
                                results.details.push(`✓ ${name} matched text "${cleanValue}" -> val "${el.value}"`);
                                break;
                            }
                        }
                    }

                    // Strategy 4: Partial match - value contains input
                    if (!found) {
                        for (let i = 0; i < el.options.length; i++) {
                            const optValue = el.options[i].value.toLowerCase();
                            const optText = el.options[i].text.trim().toLowerCase();
                            const searchTerm = cleanValue.toLowerCase();
                            
                            if (optValue.includes(searchTerm) || searchTerm.includes(optValue)) {
                                el.selectedIndex = i;
                                found = true;
                                matchType = 'partial-value';
                                results.details.push(`✓ ${name} partial matched "${cleanValue}" -> "${el.options[i].text}" (${el.value})`);
                                break;
                            }
                        }
                    }

                    // Strategy 5: Best fuzzy match - text contains input
                    if (!found) {
                        for (let i = 0; i < el.options.length; i++) {
                            const optText = el.options[i].text.trim().toLowerCase();
                            const searchTerm = cleanValue.toLowerCase();
                            
                            if (optText.includes(searchTerm) || searchTerm.includes(optText)) {
                                el.selectedIndex = i;
                                found = true;
                                matchType = 'partial-text';
                                results.details.push(`✓ ${name} fuzzy matched "${cleanValue}" -> "${el.options[i].text}" (${el.value})`);
                                break;
                            }
                        }
                    }

                    if (found) {
                        // Crucial: These events trigger the NEXT dropdown to load
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        if (window.jQuery) { try { $(el).trigger('change').trigger('blur'); } catch(e){} }
                        results.success.push(name);
                    } else {
                        results.details.push(`⚠️ ${name}: No match found for "${cleanValue}"`);
                        results.failed.push(name);
                    }
                } 
                else if (el.type === 'radio') {
                     const radio = document.querySelector(`[name="${name}"][value="${cleanValue}"]`);
                     if(radio) { radio.click(); results.success.push(name); }
                }
                else {
                    el.value = cleanValue;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    
                    if (el.classList.contains('datepicker') && window.jQuery) {
                         try { $(el).datepicker('setDate', cleanValue); } catch(e){}
                    }
                    results.success.push(name);
                }
            } else {
                results.failed.push(name);
                results.details.push(`✗ ${name} (NOT FOUND)`);
            }
        }
        return results;
    }
    """

    # --- STAGE 1: Inject "Drivers" (Business Type & Class) ---
    # These fields must be filled first to trigger the loading of Policy Type
    payload_stage_1 = {
        "NewBusinessGen.BusinessGenType": row.get("BusinessType", ""),
        "NewBusinessGen.Class": row.get("Class", ""),
        # Independent fields (can be filled now to save time)
        "NewBusinessGen.Source": row.get("Source", ""),
        "NewBusinessGen.POS": row.get("POS", ""),
        "NewBusinessGen.Location": row.get("LocationRegion", ""), 
    }
    # Clean empty values
    payload_stage_1 = {k: v for k, v in payload_stage_1.items() if v and v != "nan" and v != "None"}

    try:
        logger.info("=" * 60)
        logger.info("STAGE 1 INJECTION - Business Type & Class")
        logger.info(f"Total fields to inject: {len(payload_stage_1)}")
        logger.info("=" * 60)
        
        results = await page.evaluate(js_injector, payload_stage_1)
        
        logger.info(f"✓ Successfully injected: {len(results.get('success', []))} fields")
        if results.get("failed"):
            logger.warning(f"⚠️ Failed to inject: {len(results['failed'])} fields")
            
        for detail in results.get("details", []):
            if "✗" in detail or "⚠️" in detail:
                logger.warning(detail)
            else:
                logger.debug(detail)
                
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Stage 1 Injection failed: {e}")
        raise

    # --- CRITICAL WAIT: Allow the website to fetch Policy Types from server ---
    logger.info("Waiting 3 seconds for Policy Type options to load...")
    await asyncio.sleep(1) 

    # --- STAGE 2: Inject "Dependents" (Policy Type & Others) ---
    # Now that the dropdown options are loaded, we can select the Policy Type
    payload_stage_2 = {
        "NewBusinessGen.PolicyType": row.get("PolicyTypeCRM", ""),
        "NewBusinessGen.Classification": row.get("Classification", ""),
        "NewBusinessGen.Competitor": row.get("Competitor", ""),  # Competitor
        "NewBusinessGen.ClientRefNo": str(row.get("ClientRefNo", "")),  # Client Ref No
        
        # User Assignments
        "NewBusinessGen.SalesUserId": row.get("SalesUser", ""),     
        "NewBusinessGen.AssignToGroup": row.get("AssignToGroup", ""),
        "NewBusinessGen.AssignToUser": row.get("AssignToUser", ""),
        
        # Client License Experience
        "Client.LicenseExperience": row.get("LicenseExperience_CRM", ""),

    }
    
    # Add RenewalProcessingStatus as OPTOUT if opt-out detected
    if optout_data:
        payload_stage_2["NewBusinessGen.RenewalProcessingStatus"] = "OPTOUT"
        logger.info("✓ Setting RenewalProcessingStatus to OPTOUT due to opt-out request")
    payload_stage_2 = {k: v for k, v in payload_stage_2.items() if v and v != "nan" and v != "None"}

    try:
        logger.info("=" * 60)
        logger.info("STAGE 2 INJECTION - Policy Type & Assignments")
        logger.info(f"Total fields to inject: {len(payload_stage_2)}")
        logger.info("=" * 60)
        
        results = await page.evaluate(js_injector, payload_stage_2)
        
        logger.info(f"✓ Successfully injected: {len(results.get('success', []))} fields")
        if results.get("failed"):
            logger.warning(f"⚠️ Failed to inject: {len(results['failed'])} fields")
            
        for detail in results.get("details", []):
            if "✗" in detail or "⚠️" in detail:
                logger.warning(detail)
            else:
                logger.debug(detail)
                
        logger.info("=" * 60)
    except Exception as e:
        logger.error(f"Stage 2 Injection failed: {e}")
        raise


    # --- Step 4: Save Prospect (using run_actions for validation) ---
    save_actions = [{"type": "click", "key": "save_button", "label": "Save New Prospect", "validation_check": True, "required": True}]
    try:
        await run_actions(page, actions=save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    except Exception as e:
        logger.error(f"Error during create-prospect save action: {e}")
        raise

    # --- Step 5: Scrape RefNo ---
    try:
        if "general_prospect_ref_no" in selectors:
            prospect_ref = await get_autofilled_input_value(
                page, logger=logger, selector_key="general_prospect_ref_no",
                selectors=selectors, label="Prospect RefNo", timeout_ms=10000
            )
            logger.info(f"Scraped Prospect RefNo: {prospect_ref}")
            df.at[0, "crm_ref_no"] = prospect_ref
    except Exception as e:
        logger.debug(f"Could not scrape Prospect RefNo: {e}")

    await asyncio.sleep(2)

    # --- Step 6: Vehicle Flow ---
    # Check AppStatus to determine if vehicle flow should be executed
    row = df.iloc[0]
    app_status = str(row.get("AppStatus", "")).strip().upper()
    
    if app_status == "LEAD PROSPECT":
        logger.info(f"AppStatus is '{app_status}' - Skipping Vehicle Flow (Prospect only, no vehicle)")
        logger.info("Prospect will be created without vehicle registration")
    else:
        logger.info(f"AppStatus is '{app_status}' - Starting Vehicle Flow...")
        dashboard_selectors = load_section_from_yaml("locators/main/dashboard_page.yml", section="dashboard")
        await vehicle_flow(page, df, dashboard_selectors, logger, run_id=run_id)


    # --- Step 7: Upload Documents ---
    try:
        documents = [] 
        provided = locals().get("documents") or documents
        if provided:
            logger.info(f"Uploading {len(provided)} documents...")
            upload_selector = selectors.get("upload_document_field", "div[id^='DragnDrop__'].dropzone")
            await upload_files_via_drop(page, files=provided, drop_selector=upload_selector, logger=logger, run_id=run_id, wait_between=2.5)
    except Exception as e:
        logger.error(f"Document upload failed: {e}")
    
    # --- Step 8: Save Prospect Again (using run_actions for validation) ---
    save_actions = [{"type": "click", "key": "save_button", "label": "Save New Prospect", "validation_check": True, "required": True}]
    try:
        await run_actions(page, actions=save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    except Exception as e:
        logger.error(f"Error during create-prospect save action: {e}")
        raise


    # --- Step 9: Cleanup ---
    close_actions = [
        {"type": "click", "key": "tab", "label": "New Prospect Tab"},
        {"type": "click", "key": "close_tab_button", "label": "Remove Tab"}
    ]
    await run_actions(page, actions=close_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    
    # Optional: wait for a next-step element (e.g., dashboard link) if your flow requires
    dashboard_path = Path("locators/main/dashboard_page.yml")
    dashboard_yml = load_yaml_file(dashboard_path)
    dashboard_cfg = dashboard_yml.get("dashboard", {})
    dashboard_xpath = dashboard_cfg.get("xpath")
    if dashboard_xpath:
        try:
            await wait_for_next_step(page, logger=logger, label="Dashboard page ready", selector=dashboard_xpath, timeout_ms=45000)
        except Exception as e:
            logger.debug(f"Dashboard next-step wait failed (continuing): {e}")

    logger.info("Create Prospect process completed (Cascading JS Injection Mode)")