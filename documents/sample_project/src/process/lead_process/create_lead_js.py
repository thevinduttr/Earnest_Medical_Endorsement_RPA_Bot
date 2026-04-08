from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step, get_autofilled_input_value, upload_files_via_drop
from src.utils.load_data import load_yaml_file
from src.process.select_client import select_client_process

async def create_lead_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
) -> None:
    """
    Optimized Create Lead Flow:
      1. Open Tab
      2. Select Client (Standard UI)
      3. Fill Lead Details (JS Injection) - INSTANT
      4. Upload Documents
      5. Save (Robust Click)
      6. Scrape Ref No & Cleanup
    """
    logger.info("Create Lead process started (JS Injection Mode)")
    selectors = selectors_group or {}
    row = df.iloc[0]

    # --- Step 1: Open New Lead Tab ---
    pre_upload_actions = [{"type": "click", "key": "tab", "label": "Open New Lead Tab"}]
    await run_actions(page, actions=pre_upload_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)

    # --- Step 2: Select Client (Keep existing logic) ---
    # This likely uses a search popup, so we keep it as standard UI interaction
    await select_client_process(page=page, df=df, logger=logger)
    
    # Wait for the main form to settle after selecting the client
    await asyncio.sleep(2)

    # --- Step 3: Prepare Data Payload (Organized) ---
    
    # === LEAD REQUIREMENT DETAILS PAYLOAD ===
    lead_requirements_payload = {
        # Business Details
        "NewLead.LeadType": row.get("BusinessType", ""),
        "NewLead.Class": row.get("Class", ""),
        "NewLead.PolicyType": row.get("PolicyTypeCRM", ""),
        "NewLead.InsuranceCompany": row.get("InsuranceCompany", ""),
        "NewLead.Classification": row.get("Classification", ""),
        "NewLead.Source": row.get("Source", ""),
        "NewLead.POS": row.get("POS", ""),
        
        # Assignment Details
        "NewLead.SalesUserId": row.get("SalesUser", ""),
        "NewLead.AssignToGroup": row.get("AssignToGroup", ""),
        "NewLead.AssignToUser": row.get("AssignToUser", ""),
        
        # Dates and Remarks
        "NewLead.LeadGenerationDate": row.get("LeadGenerationDate", ""),
        "NewLead.DueDate": row.get("DueDate", ""),
        "NewLead.Remarks": row.get("Remarks", ""),
    }

    # Merge all payloads
    payload = {
        **lead_requirements_payload,
    }

    # Clean empty values
    payload = {k: v for k, v in payload.items() if v and v != "nan" and v != "None"}

    # --- Execute JS Injection with Enhanced Fuzzy Matching ---
    js_script = """
    (data) => {
        console.log("🚀 Starting Lead Form Injection...");
        let results = { success: [], failed: [], details: [] };

        for (const [name, value] of Object.entries(data)) {
            const cleanValue = String(value).trim();
            const el = document.querySelector(`[name="${name}"]`);
            
            if (el) {
                // 1. Force Focus (Critical for validation)
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
                        // Dispatch sequence of events to simulate human interaction
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true })); // Important!
                        if (window.jQuery) { 
                            try { $(el).trigger('change').trigger('blur'); } catch(e){} 
                        }
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
                    // Standard Inputs
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
    
    try:
        logger.info("=" * 60)
        logger.info("JS INJECTION - Filling all lead form fields")
        logger.info(f"Total fields to inject: {len(payload)}")
        logger.info("=" * 60)
        
        results = await page.evaluate(js_script, payload)
        
        # Log results
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
        logger.error(f"JS Injection Failed: {e}")
        raise

    # --- Step 4: Save Lead (First Save) ---
    first_save_actions = [{"type": "click", "key": "save_button", "label": "Save Lead"}]
    try:
        await run_actions(page, actions=first_save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    except Exception as e:
        logger.error(f"Error during first save action: {e}")
        raise

    # --- Step 5: Upload Documents ---
    try:
        documents = [
            # Emirates ID document
            {
                "path": "data/attachments",
                "file_name": "EMIRATES_ID",
                "doc_type": "Other Docs",
                "expiry_date": row.get("EmiratesIDExpiryDate")
            },
            
            # Driving License document
            {
                "path": "data/attachments",
                "file_name": "DRIVING_LICENSE",
                "doc_type": "Other Docs",
                "expiry_date": row.get("LicenseExpiryDate")
            },
            
            # Vehicle documents
            {
                "path": "data/attachments",
                "file_name": "PCD_HYSA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "MULKIYA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "E_MULKIYA_HYSA",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "VCC",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "KAVAK_QUOTATION",
                "doc_type": "Other Docs",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "ALBA_QUOTATION",
                "doc_type": "Other Docs",
                "expiry_date": ""
            }
        ]

        if documents:
            logger.info(f"Uploading {len(documents)} document(s) from provided list.")
            upload_selector = selectors.get("upload_document_field", "div[id^='DragnDrop__'].dropzone")
            await upload_files_via_drop(
                page,
                files=documents,
                drop_selector=upload_selector,
                logger=logger,
                run_id=run_id,
                wait_between=2.5,
            )
        else:
            logger.info("No 'documents' variable provided; skipping document upload.")
            
    except Exception as e:
        logger.error(f"Document upload failed (continuing): {e}")

    # --- Step 6: Save Lead Again (Final Save with validation) ---
    final_save_actions = [{"type": "click", "key": "save_button", "label": "Save New Lead", "validation_check": True, "required": True}]
    try:
        await run_actions(page, actions=final_save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    except Exception as e:
        logger.error(f"Error during final save action: {e}")
        raise

    # --- Step 7: Scrape Lead RefNo (After Save) ---
    try:
        # NOTE: Ensure 'requirement_lead_ref_no' is in your YAML selectors
        if "requirement_lead_ref_no" in selectors:
            lead_ref = await get_autofilled_input_value(
                page, logger=logger, selector_key="requirement_lead_ref_no",
                selectors=selectors, label="Prospect RefNo", timeout_ms=10000
            )
            logger.info(f"Scraped Lead RefNo: {lead_ref}")
            df.at[0, "lead_refr_no"] = lead_ref
    except Exception as e:
        logger.debug(f"Could not scrape Lead RefNo: {e}")

    # --- Step 8: Cleanup ---
    close_actions = [
        {"type": "click", "key": "tab", "label": "New Lead Tab"},
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

    logger.info("Create Lead process completed (JS Injection Mode)")