from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page
import base64

from src.utils.support_functions import run_actions, wait_for_next_step, upload_files_via_drop
from src.utils.load_data import load_yaml_file

async def create_client_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
) -> None:
    logger.info("Create Client process started (JS Injection Mode)")
    selectors = selectors_group or {}
    row = df.iloc[0]

    # --- Step 1: Open New Client Tab ---
    open_tab_actions = [{"type": "click", "key": "tab", "label": "Open New Client Tab"}]
    await run_actions(page, actions=open_tab_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    await asyncio.sleep(2) 

    # --- Step 2: Prepare Data Payloads (Organized by Section) ---
    
    # Determine Title based on Gender if Title is empty or null
    title_value = row.get("Title", "")
    if pd.isna(title_value) or str(title_value).strip().lower() in ["", "nan", "none", "null"]:
        gender = str(row.get("Gender", "")).strip().upper()
        if gender in ["M", "MALE"]:
            title_value = "Mr"
        elif gender in ["F", "FEMALE"]:
            title_value = "Ms"
        else:
            title_value = ""  # Leave empty if gender is unknown/null
    else:
        title_value = str(title_value).strip()  # Use existing title from Excel
    
    # === CLIENT DETAILS PAYLOAD ===
    client_details_payload = {
        "Client.ClientType": row.get("ClientType", ""),
        "Client.Title": title_value,
        "Client.FirstName": row.get("FirstName", ""),
        "Client.LastName": row.get("LastName", ""),
        "Client.ClientName": f"{row.get('FirstName', '')} {row.get('LastName', '')}",
        "Client.Gender": "M" if str(row.get("Gender", "")).lower().startswith("m") else "F",
        "Client.DOB": row.get("DateOfBirth", ""),
        "Client.EmirateId": str(row.get("EmiratesID", "")),
        "Client.EmirateIdExpiryDate": row.get("EmiratesIDExpiryDate", ""),
        "Client.OtherId": str(row.get("OtherID", "")),  # Other ID
        "Client.CreditLimit": "0" if str(row.get("ClientType", "")).strip().lower() == "individual" else "",
        "Client.CreditDays": "0" if str(row.get("ClientType", "")).strip().lower() == "individual" else "",
        "Client.PaymentOption": "Cash" if str(row.get("ClientType", "")).strip().lower() == "individual" else "",
        "Client.MaritalStatus": row.get("MaritalStatus", ""),
        "Client.AnniversaryDate": row.get("DateOfAnniversary", ""),  # Date of Anniversary
        "Client.Occupation": row.get("Occupation", ""),
        "Client.AnnualIncome": row.get("AnnualIncome", ""),
        "Client.Designation": row.get("Designation", ""),
        "Client.PassportNo": str(row.get("PassportNo", "")),
        "Client.VATRegistrationNumber": str(row.get("VATRegistrationNumber", "")),  # VAT No
        "Client.Suspended": row.get("Suspended", "NO"),
        "Client.SuspendedComment": str(row.get("SuspendedComments", "")),  # Suspended Comments
        "Client.TCFNo": str(row.get("TCFNo", "")),  # TCF No
        "Client.TCFEmirate": row.get("LicenseIssuePlace", ""),  # TCF Emirate (uses same value as License Issue Place)
    }
    
    # === AML DETAILS PAYLOAD (Optional - currently not executed in main code) ===
    aml_details_payload = {
        "Client.AMLVerified": "Y" if row.get("AMLVerified", "").upper() == "YES" else "N",
        "Client.AMLStatus": row.get("AMLStatus", ""),
        "Client.AMLReviewDate": row.get("AMLReviewDate", ""),
        "Client.AMLRemarks": str(row.get("AMLRemarks", "")),
    }
    
    # === LICENSE DETAILS PAYLOAD ===
    license_details_payload = {
        "Client.LicenseIssueDate": row.get("LicenseIssueDate", ""),
        "Client.LicenseExpiryDate": row.get("LicenseExpiryDate", ""),
        "Client.LicenseNumber": str(row.get("LicenseNumber", "")),  # License Number
        "Client.LicenseIssuePlace": row.get("LicenseIssuePlace", ""),  # License Issue Place
    }
    
    # === CONTACT DETAILS PAYLOAD ===
    contact_details_payload = {
        "Client.Address": row.get("Address", ""),
        # "Client.Pin": str(row.get("POBox", "")),  # PO Box
        "Client.Nationality": row.get("Nationality", ""),
        "Client.Emirate": row.get("Emirate", ""),  # Emirate
        "Client.LandlineNo": str(row.get("Landline", "")),
        "Client.FaxNo": str(row.get("FaxNo", "")),  # Fax No
        "tempMobileNoWithDialCode": str(row.get("Mobile_CRM", "")),
        "Client.OtherContactDetails": str(row.get("OtherContactDetails", "")),  # Other Contact Details
        "Client.EmailId": str(row.get("Email_CRM", "")),
    }
    
    # === OTHER DETAILS PAYLOAD ===
    other_details_payload = {
        "Client.ContactPersonName": str(row.get("ContactPersonName", "")),  # Contact Person Name
        "Client.ContactPersonDesignation": str(row.get("ContactPersonDesignation", "")),  # Contact Person Designation
        "Client.DefaultUserId": "Earnest-Direct (EarnestDirect)",  # Sales User (Always set to default)
        "Client.GroupClientFlag": row.get("GroupClient", "N"),  # Group Client
        "Client.POS": row.get("POS", ""),  # POS
        "Client.ClientCode": str(row.get("ClientCode", "")),  # Client Code
        "Client.Source": row.get("Source", ""),  # Source
        "Client.BrokerCode": "EARNESTINS",
        "Client.DefaultContact": "1",
    }

    # Merge all payloads
    payload = {
        **client_details_payload,
        # **aml_details_payload,  # Uncomment if AML fields are needed
        **license_details_payload,
        **contact_details_payload,
        **other_details_payload,
    }

    # Clean empty values
    payload = {k: v for k, v in payload.items() if v and v != "nan" and v != "None"}

    # --- Step 3: Execute JS Injection (Organized by Sections) ---
    js_script = """
    (data) => {
        console.log("🚀 Starting Strong JS Injection...");
        let results = { success: [], failed: [], details: [], fuzzyMatches: [], multipleMatchWarnings: [] };

        // Normalize string: remove spaces, hyphens, underscores, dots for comparison
        function normalizeString(str) {
            return str.toLowerCase().trim().replace(/[\\s\\-_\\.]/g, '');
        }

        // Calculate similarity between two strings (with normalization)
        function calculateSimilarity(str1, str2) {
            const s1 = str1.toLowerCase().trim();
            const s2 = str2.toLowerCase().trim();

            if (s1 === s2) return 1.0;

            // Normalized comparison (handles "United Arab Emirates" vs "U.A.E" etc)
            const n1 = normalizeString(str1);
            const n2 = normalizeString(str2);
            if (n1 === n2) return 0.98;
            if (n1.includes(n2) || n2.includes(n1)) return 0.92;

            if (s1.includes(s2) || s2.includes(s1)) return 0.9;

            const original = levenshteinSimilarity(s1, s2);
            const normalized = levenshteinSimilarity(n1, n2);
            return Math.max(original, normalized);
        }

        function levenshteinSimilarity(s1, s2) {
            const longer  = s1.length >= s2.length ? s1 : s2;
            const shorter = s1.length >= s2.length ? s2 : s1;
            if (longer.length === 0) return 1.0;
            return (longer.length - levenshteinDistance(longer, shorter)) / longer.length;
        }

        function levenshteinDistance(s1, s2) {
            const matrix = Array(s2.length + 1).fill(null).map(() => Array(s1.length + 1).fill(null));
            for (let i = 0; i <= s1.length; i++) matrix[0][i] = i;
            for (let j = 0; j <= s2.length; j++) matrix[j][0] = j;
            for (let j = 1; j <= s2.length; j++) {
                for (let i = 1; i <= s1.length; i++) {
                    const cost = s1[i-1] === s2[j-1] ? 0 : 1;
                    matrix[j][i] = Math.min(
                        matrix[j][i-1] + 1,
                        matrix[j-1][i] + 1,
                        matrix[j-1][i-1] + cost
                    );
                }
            }
            return matrix[s2.length][s1.length];
        }

        // Find best fuzzy match from a SELECT element's options
        function findBestMatch(searchValue, options) {
            const minThreshold = 0.6;
            let allMatches = [];

            for (let i = 0; i < options.length; i++) {
                const optText  = options[i].text.trim();
                const optValue = options[i].value.trim();
                if (!optText || optText === '--Select--') continue;

                const textScore  = calculateSimilarity(searchValue, optText);
                const valueScore = calculateSimilarity(searchValue, optValue);
                const maxScore   = Math.max(textScore, valueScore);

                if (maxScore >= minThreshold) {
                    allMatches.push({
                        index: i,
                        text: optText,
                        value: optValue,
                        score: maxScore,
                        matchedAgainst: textScore >= valueScore ? 'text' : 'value',
                        lengthDiff: Math.abs(optText.length - searchValue.length)
                    });
                }
            }

            if (allMatches.length === 0) return null;

            // Sort: highest score → closest length → shortest text
            allMatches.sort((a, b) => {
                if (Math.abs(b.score - a.score) > 0.01) return b.score - a.score;
                if (a.lengthDiff !== b.lengthDiff) return a.lengthDiff - b.lengthDiff;
                return a.text.length - b.text.length;
            });

            const best = allMatches[0];
            const similar = allMatches.filter(m => Math.abs(m.score - best.score) <= 0.02);
            if (similar.length > 1) {
                best.multipleMatches = similar.map(m => ({ text: m.text, score: m.score }));
                best.warning = `Multiple similar matches: ${similar.map(m => `"${m.text}" (${(m.score*100).toFixed(0)}%)`).join(', ')}. Selected: "${best.text}"`;
            }
            return best;
        }

        // Fields that use fuzzy matching (add field name substrings here)
        const fuzzyFields = ['Nationality'];

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
                            const optText  = el.options[i].text.trim().toLowerCase();
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

                    // Strategy 5: Partial text match
                    if (!found) {
                        for (let i = 0; i < el.options.length; i++) {
                            const optText    = el.options[i].text.trim().toLowerCase();
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

                    // Strategy 6: Levenshtein Fuzzy Match (Nationality and other configured fields)
                    if (!found && fuzzyFields.some(f => name.includes(f))) {
                        const bestMatch = findBestMatch(cleanValue, el.options);
                        if (bestMatch) {
                            el.selectedIndex = bestMatch.index;
                            found = true;
                            matchType = 'fuzzy-levenshtein';

                            results.details.push(`⚠️ 🔍 FUZZY MATCH for ${name}: "${cleanValue}" → "${bestMatch.text}" (${(bestMatch.score * 100).toFixed(1)}% similarity, matched against ${bestMatch.matchedAgainst})`);

                            if (bestMatch.warning) {
                                results.details.push(`⚠️ MULTIPLE MATCHES: ${bestMatch.warning}`);
                                results.multipleMatchWarnings.push({
                                    field: name,
                                    searchValue: cleanValue,
                                    selectedOption: bestMatch.text,
                                    allMatches: bestMatch.multipleMatches
                                });
                            }

                            results.fuzzyMatches.push({
                                field: name,
                                original: cleanValue,
                                matched: bestMatch.text,
                                score: bestMatch.score,
                                matchedAgainst: bestMatch.matchedAgainst,
                                hadMultipleMatches: !!bestMatch.multipleMatches,
                                alternativeMatches: bestMatch.multipleMatches || []
                            });
                        }
                    }

                    if (found) {
                        el.dispatchEvent(new Event('input',  { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur',   { bubbles: true }));
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
                    el.dispatchEvent(new Event('input',  { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur',   { bubbles: true }));
                    
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
        logger.info("JS INJECTION - Filling all client form fields")
        logger.info(f"Total fields to inject: {len(payload)}")
        logger.info("=" * 60)
        
        results = await page.evaluate(js_script, payload)
        
        # Log results
        logger.info(f"✓ Successfully injected: {len(results.get('success', []))} fields")
        if results.get("failed"):
            logger.warning(f"⚠️ Failed to inject: {len(results['failed'])} fields")
            
        for detail in results.get("details", []):
            if "🔍 FUZZY MATCH" in detail:
                logger.warning(f"🟡 {detail}")  # Highlight fuzzy matches
            elif "MULTIPLE MATCHES" in detail:
                logger.warning(detail)
            elif "✗" in detail or "⚠️" in detail:
                logger.warning(detail)
            else:
                logger.debug(detail)

        # Log fuzzy match summary
        fuzzy_matches = results.get("fuzzyMatches", [])
        if fuzzy_matches:
            logger.warning(f"🔍 Fuzzy Match Summary: {len(fuzzy_matches)} automatic correction(s) applied")
            for match in fuzzy_matches:
                logger.warning(f"   → {match['field']}: '{match['original']}' matched to '{match['matched']}' ({match['score']*100:.1f}% similarity)")
                if match.get('hadMultipleMatches'):
                    alts = ", ".join([f'"{m["text"]}" ({m["score"]*100:.0f}%)' for m in match['alternativeMatches']])
                    logger.warning(f"     ⚠️ Multiple similar options were found: {alts}")
                
        logger.info("=" * 60)
            
    except Exception as e:
        logger.error(f"JS Injection Failed: {e}")
        raise

    # --- Step 4: Upload Documents ---
    try:
        documents = [
            # Emirates ID document
            {
                "path": "data/attachments",
                "file_name": "EMIRATES_ID",
                "doc_type": "Emirates ID",
                "expiry_date": row.get("EmiratesIDExpiryDate")
            },
            
            # Driving License document
            {
                "path": "data/attachments",
                "file_name": "DRIVING_LICENSE",
                "doc_type": "UAE DL",
                "expiry_date": row.get("LicenseExpiryDate")
            },
            
            # Other document
            {
                "path": "data/attachments",
                "file_name": "OTHER_DOCUMENT",
                "doc_type": "Other docs",
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

    # --- Step 5: Save Client (using run_actions for validation) ---
    save_actions = [{"type": "click", "key": "save_button", "label": "Save", "validation_check": True, "required": True}]
    try:
        await run_actions(page, actions=save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    except Exception as e:
        logger.error(f"Error during create-client save action: {e}")
        raise

    # --- Step 6: Cleanup ---
    close_actions = [
        {"type": "click", "key": "tab", "label": "Open New Client Tab"},
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
    
    logger.info("Create Client process completed (JS Injection Mode).")