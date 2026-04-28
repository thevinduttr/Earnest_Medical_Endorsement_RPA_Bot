from __future__ import annotations
from typing import Dict, Any, List, Optional
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page
from src.utils.support_functions import run_actions, upload_files_via_drop, check_validation_summary, notify_process_error
from src.utils.error_handler import ValidationError

"""
Enhanced Vehicle Creation with Fuzzy Matching
============================================

This module supports intelligent matching for vehicle Make and Model dropdowns:

1. **Exact Match**: First attempts exact value and text matching
2. **Fuzzy Match**: If exact match fails, uses string similarity algorithms
3. **Smart Matching**: Handles common typos like "toyote" → "toyota"
4. **Logging**: Highlights fuzzy matches with 🔍 emoji and similarity scores
5. **Threshold**: Only accepts matches with ≥60% similarity score

Features:
- Levenshtein distance calculation for string similarity
- Substring matching for partial matches
- Enhanced logging with color-coded messages
- Detailed fuzzy match reporting with similarity percentages
"""

async def create_vehicle_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
) -> Dict[str, Any]:
    """
    Create Vehicle process with fuzzy matching support.
    
    Returns:
        Dict containing fuzzy match information including:
        - fuzzy_matches: List of fuzzy matches applied
        - total_fuzzy_matches: Count of fuzzy matches
        - match_summary: Human-readable summary
    """
    logger.info("Create Vehicle process started (2-Stage JS Injection)")
    selectors = selectors_group or {}
    row = df.iloc[0]
    
    # Initialize fuzzy match tracking
    all_fuzzy_matches = []

    # --- Step 1: Open Vehicle Modal ---
    pre_upload_actions = [
        {"type": "click", "key": "create_vehicle_button", "label": "Open Create Vehicle Modal"},
        {"type": "click", "key": "modal", "label": "Open Create Vehicle Modal"}, 
    ]
    await run_actions(page, actions=pre_upload_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
    await asyncio.sleep(0.5) # Wait for modal

    # --- REUSABLE JS INJECTOR WITH FUZZY MATCHING ---
    js_injector = """
    (data) => {
        // Normalize string by removing spaces, hyphens, and special characters
        function normalizeString(str) {
            return str.toLowerCase().trim().replace(/[\\s\\-_\\.]/g, '');
        }
        
        // Fuzzy matching function using similarity score
        function calculateSimilarity(str1, str2) {
            const s1 = str1.toLowerCase().trim();
            const s2 = str2.toLowerCase().trim();
            
            // Exact match gets highest score
            if (s1 === s2) return 1.0;
            
            // Normalized comparison (handles "CR V" vs "CR-V" vs "CRV")
            const n1 = normalizeString(str1);
            const n2 = normalizeString(str2);
            if (n1 === n2) return 0.98; // Near-perfect match after normalization
            
            // Check if normalized versions contain each other
            if (n1.includes(n2) || n2.includes(n1)) return 0.92;
            
            // Check if one string contains the other (original)
            if (s1.includes(s2) || s2.includes(s1)) return 0.9;
            
            // Calculate similarity for both original and normalized strings
            const originalScore = levenshteinSimilarity(s1, s2);
            const normalizedScore = levenshteinSimilarity(n1, n2);
            
            // Return the better score (normalized often gives better results for special chars)
            return Math.max(originalScore, normalizedScore);
        }
        
        function levenshteinSimilarity(str1, str2) {
            const longer = str1.length > str2.length ? str1 : str2;
            const shorter = str1.length > str2.length ? str2 : str1;
            
            if (longer.length === 0) return 1.0;
            
            const distance = levenshteinDistance(longer, shorter);
            return (longer.length - distance) / longer.length;
        }
        
        function levenshteinDistance(str1, str2) {
            const matrix = Array(str2.length + 1).fill().map(() => Array(str1.length + 1).fill());
            
            for (let i = 0; i <= str1.length; i++) matrix[0][i] = i;
            for (let j = 0; j <= str2.length; j++) matrix[j][0] = j;
            
            for (let j = 1; j <= str2.length; j++) {
                for (let i = 1; i <= str1.length; i++) {
                    const substitutionCost = str1[i - 1] === str2[j - 1] ? 0 : 1;
                    matrix[j][i] = Math.min(
                        matrix[j][i - 1] + 1,     // insertion
                        matrix[j - 1][i] + 1,     // deletion
                        matrix[j - 1][i - 1] + substitutionCost // substitution
                    );
                }
            }
            return matrix[str2.length][str1.length];
        }
        
        function findBestMatch(searchValue, options) {
            let allMatches = [];  // Track ALL matches above threshold
            const minThreshold = 0.6; // Minimum similarity threshold
            
            // First pass: collect all matches above threshold
            for (let i = 0; i < options.length; i++) {
                const optionText = options[i].text.trim();
                const optionValue = options[i].value.trim();
                
                // Skip empty/placeholder options
                if (!optionText || optionText === '--Select--') continue;
                
                // Check similarity with both text and value
                const textScore = calculateSimilarity(searchValue, optionText);
                const valueScore = calculateSimilarity(searchValue, optionValue);
                const maxScore = Math.max(textScore, valueScore);
                
                if (maxScore >= minThreshold) {
                    allMatches.push({
                        index: i,
                        text: optionText,
                        value: optionValue,
                        score: maxScore,
                        matchedAgainst: textScore > valueScore ? 'text' : 'value',
                        lengthDiff: Math.abs(optionText.length - searchValue.length)
                    });
                }
            }
            
            if (allMatches.length === 0) return null;
            
            // Sort by: 1) highest score, 2) smallest length difference, 3) shortest text
            allMatches.sort((a, b) => {
                // First: higher score wins
                if (Math.abs(b.score - a.score) > 0.01) return b.score - a.score;
                // If scores are within 1%, prefer closer length match
                if (a.lengthDiff !== b.lengthDiff) return a.lengthDiff - b.lengthDiff;
                // If same length diff, prefer shorter option text
                return a.text.length - b.text.length;
            });
            
            const bestMatch = allMatches[0];
            
            // Check if there are multiple matches with very similar scores (within 2%)
            const similarMatches = allMatches.filter(m => 
                Math.abs(m.score - bestMatch.score) <= 0.02
            );
            
            if (similarMatches.length > 1) {
                bestMatch.multipleMatches = similarMatches.map(m => ({
                    text: m.text,
                    score: m.score
                }));
                bestMatch.warning = `Multiple similar matches found: ${similarMatches.map(m => `"${m.text}" (${(m.score*100).toFixed(0)}%)`).join(', ')}. Selected: "${bestMatch.text}"`;
            }
            
            return bestMatch;
        }
        
        let results = { success: [], failed: [], details: [], fuzzyMatches: [], multipleMatchWarnings: [] };
        
        for (const [name, value] of Object.entries(data)) {
            const cleanValue = String(value).trim();
            const el = document.querySelector(`[name="${name}"]`);
            
            if (el) {
                el.focus();
                
                if (el.tagName === 'SELECT') {
                    let found = false;
                    let matchType = 'exact';
                    
                    // Step 1: Try exact value match
                    el.value = cleanValue; 
                    if (el.value === cleanValue) found = true;

                    // Step 2: Try exact text match (case insensitive)
                    if (!found) {
                        for (let i = 0; i < el.options.length; i++) {
                            if (el.options[i].text.trim().toLowerCase() === cleanValue.toLowerCase()) {
                                el.selectedIndex = i;
                                found = true;
                                matchType = 'exact_text';
                                results.details.push(`✓ ${name} matched exact text "${cleanValue}"`);
                                break;
                            }
                        }
                    }
                    
                    // Step 3: Try fuzzy matching (only for Make and Model fields)
                    if (!found && (name.includes('Make') || name.includes('Model'))) {
                        const bestMatch = findBestMatch(cleanValue, el.options);
                        
                        if (bestMatch) {
                            el.selectedIndex = bestMatch.index;
                            found = true;
                            matchType = 'fuzzy';
                            
                            // Log fuzzy match with highlighting
                            const logMessage = `🔍 FUZZY MATCH for ${name}: "${cleanValue}" → "${bestMatch.text}" (${(bestMatch.score * 100).toFixed(1)}% similarity, matched against ${bestMatch.matchedAgainst})`;
                            results.details.push(`⚠️ ${logMessage}`);
                            
                            // Log multiple match warning if applicable
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
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                        if (window.jQuery) { try { $(el).trigger('change').trigger('blur'); } catch(e){} }
                        results.success.push({ field: name, matchType: matchType });
                    } else {
                        results.failed.push(name);
                        if (name.includes('Make') || name.includes('Model')) {
                            results.details.push(`❌ ${name}: No suitable match found for "${cleanValue}" (tried exact and fuzzy matching)`);
                        } else {
                            results.details.push(`⚠️ ${name}: Text "${cleanValue}" not found`);
                        }
                    }
                } 
                else if (el.type === 'checkbox' || el.type === 'radio') {
                    const isTrue = (cleanValue.toUpperCase() === 'YES' || cleanValue.toUpperCase() === 'TRUE' || cleanValue === '1');
                    if (isTrue && !el.checked) { el.click(); results.success.push({ field: name, matchType: 'exact' }); }
                    else if (!isTrue && el.checked) { el.click(); results.success.push({ field: name, matchType: 'exact' }); }
                }
                else {
                    el.value = cleanValue;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                    results.success.push({ field: name, matchType: 'exact' });
                }
            } else {
                results.failed.push(name);
                results.details.push(`✗ ${name} (ELEMENT NOT FOUND)`);
            }
        }
        return results;
    }
    """

    # --- STAGE 1: Inject "Make" Only ---
    # This triggers the loading of Models
    payload_stage_1 = {
        "Vehicle.Make": row.get("Make", ""), 
    }
    payload_stage_1 = {k: v for k, v in payload_stage_1.items() if v and v != "nan" and v != "None"}

    try:
        logger.info("Stage 1: Injecting Make...")
        results = await page.evaluate(js_injector, payload_stage_1)
        
        # Process results with enhanced logging for fuzzy matches
        for detail in results.get("details", []): 
            if "🔍 FUZZY MATCH" in detail:
                logger.warning(f"🟡 {detail}")  # Highlight fuzzy matches in yellow
            elif "❌" in detail:
                logger.error(detail)
            elif "✗" in detail:
                logger.warning(detail)
            else:
                logger.info(detail)
                
        # Log fuzzy match summary if any
        fuzzy_matches = results.get("fuzzyMatches", [])
        if fuzzy_matches:
            all_fuzzy_matches.extend(fuzzy_matches)
            logger.warning(f"🔍 Stage 1 Summary: {len(fuzzy_matches)} fuzzy match(es) applied")
            for match in fuzzy_matches:
                logger.warning(f"   → {match['field']}: '{match['original']}' matched to '{match['matched']}' ({match['score']*100:.1f}% similarity)")
    except Exception as e:
        logger.error(f"Stage 1 failed: {e}")

    # --- CRITICAL WAIT ---
    logger.info("Waiting 3s for Model options to load...")
    await asyncio.sleep(1)

    # --- STAGE 2: Inject "The Rest" ---
    # Now that 'Make' is set, 'Model' options should be available
    payload_stage_2 = {
        "Vehicle.Model": row.get("Model", ""),
        "Vehicle.YearOfManufacture": row.get("YearOfManufacture", ""), 
        "Vehicle.Variant": row.get("Variant", ""), 
        "Vehicle.SeatingCapacity": row.get("SeatingCapacity", ""),
        "Vehicle.BodyType": row.get("BodyType", ""),
        "Vehicle.FuelType": row.get("FuelType", ""),
        "Vehicle.PlateCategory": row.get("PlateCategory", ""),
        "Vehicle.PlateColour": row.get("PlateColour", ""),
        # "Vehicle.EmptyWeight": row.get("EmptyWeight", ""),
        "Vehicle.VehicleColour": row.get("VehicleColour", ""),
        "Vehicle.EngineNo": row.get("EngineNumber", ""),
        "Vehicle.ChassisNo": row.get("ChassisNumber", ""),
        "Vehicle.VehicleValue": row.get("VehicleValue", ""),
        "Vehicle.AnnualMileage": row.get("VehicleAnnualMileage", ""),
        "Vehicle.BankName": row.get("BankName", ""),
        "Vehicle.POS": row.get("POS", ""),
        "Vehicle.Origin": row.get("Origin", ""),

        # Registration
        "Vehicle.Emirate": row.get("Emirate", ""),
        "Vehicle.DateOfFirstRegistration": row.get("DateOfFirstRegistration", ""),
        "Vehicle.TCFNo": row.get("TCFNo", ""),

        # Checkboxes
        "Vehicle.IsModified": row.get("IsModified", "No"),
        "Vehicle.IsNonGCC": row.get("IsNonGCC", "No"),
        "Vehicle.IsImportedVehicle": row.get("IsImportedVehicle", "No"),
        "Vehicle.IsThirdParty": row.get("IsThirdParty", "No"),
        "Vehicle.IsUninsured": row.get("IsUninsured", "No"),
    }
    payload_stage_2 = {k: v for k, v in payload_stage_2.items() if v and v != "nan" and v != "None"}

    try:
        logger.info("Stage 2: Injecting Model & Remaining Fields...")
        results = await page.evaluate(js_injector, payload_stage_2)
        
        # Process results with enhanced logging for fuzzy matches
        for detail in results.get("details", []): 
            if "🔍 FUZZY MATCH" in detail:
                logger.warning(f"🟡 {detail}")  # Highlight fuzzy matches in yellow
            elif "❌" in detail:
                logger.error(detail)
            elif "✗" in detail:
                logger.warning(detail)
            else:
                logger.info(detail)
                
        # Log fuzzy match summary if any
        fuzzy_matches = results.get("fuzzyMatches", [])
        if fuzzy_matches:
            all_fuzzy_matches.extend(fuzzy_matches)
            logger.warning(f"🔍 Stage 2 Summary: {len(fuzzy_matches)} fuzzy match(es) applied")
            for match in fuzzy_matches:
                logger.warning(f"   → {match['field']}: '{match['original']}' matched to '{match['matched']}' ({match['score']*100:.1f}% similarity)")
                
        # Log success summary
        success_count = len(results.get("success", []))
        failed_count = len(results.get("failed", []))
        fuzzy_count = len(fuzzy_matches)
        
        if fuzzy_count > 0:
            logger.info(f"✅ Stage 2 Complete: {success_count} successful ({fuzzy_count} fuzzy), {failed_count} failed")
    except Exception as e:
        logger.error(f"Stage 2 failed: {e}")


    # --- Step 3: Upload Documents ---
    try:
        import os
        
        documents = [
            {"path": "data/attachments", "file_name": "PCD_HYSA", "doc_type": "Registration Card 1", "expiry_date": ""},
            {"path": "data/attachments", "file_name": "MULKIYA", "doc_type": "Registration Card 1", "expiry_date": ""},
            {"path": "data/attachments", "file_name": "E_MULKIYA_HYSA", "doc_type": "Registration Card 1", "expiry_date": ""},
            {"path": "data/attachments", "file_name": "VCC", "doc_type": "Registration Card 1", "expiry_date": ""},
            {"path": "data/attachments", "file_name": "KAVAK_QUOTATION", "doc_type": "Registration Card 1", "expiry_date": ""},
            {"path": "data/attachments", "file_name": "ALBA_QUOTATION", "doc_type": "Registration Card 1", "expiry_date": ""}
        ]
        
        # Check for availability and upload only the first available document
        available_document = None
        for doc in documents:
            file_path = os.path.join(doc["path"], doc["file_name"])
            # Check for common file extensions
            for ext in [".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ""]:
                full_path = file_path + ext
                if os.path.exists(full_path):
                    available_document = doc.copy()
                    available_document["file_name"] = doc["file_name"] + ext
                    logger.info(f"Found available document: {available_document['file_name']}")
                    break
            if available_document:
                break
        
        if available_document:
            logger.info(f"Uploading single available vehicle document: {available_document['file_name']}")
            upload_selector = selectors.get("upload_document_field", "(//div[starts-with(@id,'DragnDrop__') and contains(@class,'dropzone')])[2]")
            await upload_files_via_drop(page, files=[available_document], drop_selector=upload_selector, logger=logger, run_id=run_id, wait_between=2.5)
        else:
            logger.warning("No vehicle documents found in the specified paths")
    except Exception as e:
        logger.error(f"Document upload failed: {e}")

    # --- Step 4: Save ---
    # validation_check=False because the success toast is unreliable for vehicle creation.
    # We manually check for validation errors below instead.
    logger.info("Saving Vehicle...")
    save_actions = [{"type": "click", "key": "save_button", "label": "Save Vehicle", "validation_check": False, "required": True}]
    try:
        await run_actions(page, actions=save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
        await asyncio.sleep(1.5)  # Wait for potential validation errors to appear

        # Manual error-only check (skip success toast, only catch validation errors)
        is_error, error_message = await check_validation_summary(
            page=page,
            logger=logger,
            label="Post-Save Vehicle validation check",
            run_id=run_id
        )
        if is_error:
            from src.utils import send_email as send_email_helper

            request_id = send_email_helper.extract_request_id_from_run_id(run_id) if run_id else None
            await notify_process_error(
                page=page,
                logger=logger,
                run_id=run_id,
                subject=f"[{run_id}] Validation error after Save Vehicle",
                body=error_message,
                shot_name="vehicle_validation_error.png",
                flag_validation=True,
                request_id=request_id,
            )
            logger.error(f"Vehicle save validation error: {error_message}")
            raise ValidationError(error_message)

        logger.info("Vehicle save completed (no validation errors detected)")
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error during create-vehicle save action: {e}")
        raise

    # --- Step 5: Conditional Close Modal ---
    try:
        close_modal_selector = selectors.get("close_modal_button")
        if close_modal_selector:
            close_modal_locator = page.locator(close_modal_selector)
            if await close_modal_locator.count() > 0 and await close_modal_locator.is_visible():
                logger.info("Close modal button is visible, clicking it...")
                close_modal_actions = [{"type": "click", "key": "close_modal_button", "label": "Close Vehicle Modal"}]
                await run_actions(page, actions=close_modal_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
                await asyncio.sleep(0.5)
            else:
                logger.info("Close modal button is not visible, skipping...")
        else:
            logger.debug("No close_modal_button selector found in config")
    except Exception as e:
        logger.warning(f"Close modal button action failed (continuing): {e}")

    logger.info("Create vehicle process completed")
    
    # Store fuzzy match data in DataFrame for email reporting
    if all_fuzzy_matches:
        fuzzy_summary = f"{len(all_fuzzy_matches)} automatic corrections applied: " + \
                       ", ".join([f"{m['field']} ({m['score']*100:.0f}%)" for m in all_fuzzy_matches])
        df.at[0, 'vehicle_fuzzy_matches'] = fuzzy_summary
        
        # Store detailed fuzzy match data for logging/debugging
        df.at[0, 'vehicle_fuzzy_details'] = str(all_fuzzy_matches)
        logger.info(f"📧 Fuzzy matches will be reported in completion email: {fuzzy_summary}")
    else:
        df.at[0, 'vehicle_fuzzy_matches'] = None
        
    # Return fuzzy match summary for further processing
    return {
        'fuzzy_matches': all_fuzzy_matches,
        'total_fuzzy_matches': len(all_fuzzy_matches),
        'match_summary': fuzzy_summary if all_fuzzy_matches else "No fuzzy matching required"
    }