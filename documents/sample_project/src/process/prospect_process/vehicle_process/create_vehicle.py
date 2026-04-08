from __future__ import annotations
from typing import Dict, Any, List, Optional, Sequence
from pathlib import Path
import asyncio
import pandas as pd
import logging
from playwright.async_api import Page

from src.utils.support_functions import run_actions, wait_for_next_step , upload_files_via_drop
from src.utils.load_data import load_yaml_file

async def create_vehicle_process(
    page: Page,
    df: pd.DataFrame,
    selectors_group: Dict[str, Any] | None,
    logger: logging.Logger,
    run_id: str | None = None,
) -> None:
    """
    Create Client flow — explicit action list executed in order:
      11. open New Client tab (if selector)
      12. fill client details
      13. fill AML verification fields
      14. fill contact details
      15. fill other details
      16. upload document(s) if provided in df
      17. click Save
      18. close New client tab
    """
    logger.info("Create Vehicle process started")
    selectors = selectors_group or {}

    # --- Pre-upload actions (open tab) ---
    pre_upload_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "create_vehicle_button", "label": "Open Create Vehicle Modal"},
        {"type": "click", "key": "modal", "label": "Open Create Vehicle Modal"},
    ]

    general_details_actions: List[Dict[str, Any]] = [
        {"type": "select", "key": "general_make", "label": "Make", "value_col": "Make"},
        {"type": "select", "key": "general_model", "label": "Model", "value_col": "Model"},
        {"type": "fill",   "key": "general_registration_number", "label": "Variant", "value_col": "Variant"},
        {"type": "fill",   "key": "general_make_year", "label": "Year Of Manufacture", "value_col": "YearOfManufacture"},

        {"type": "fill",   "key": "general_seating_capacity", "label": "Seating Capacity", "value_col": "SeatingCapacity"},
        {"type": "select", "key": "general_body_type", "label": "Body Type", "value_col": "BodyType"},
        {"type": "select", "key": "general_fuel_type", "label": "Fuel Type", "value_col": "FuelType"},
        {"type": "fill",   "key": "general_plate_category", "label": "Plate Category", "value_col": "PlateCategory"},

        {"type": "select", "key": "general_plate_colour", "label": "Plate Colour", "value_col": "PlateColour"},
        {"type": "fill", "key": "general_empty_weight", "label": "Empty Weight", "value_col": "EmptyWeight"},
        # {"type": "fill", "key": "general_gross_weight", "label": "Gross Weight", "value_col": "Weight"},
        {"type": "select", "key": "general_vehicle_colour", "label": "Vehicle Colour", "value_col": "VehicleColour"},
        {"type": "fill",   "key": "general_engine_number", "label": "Engine Number", "value_col": "EngineNumber"},
        {"type": "fill",   "key": "general_chassis_number", "label": "Chassis Number", "value_col": "ChassisNumber"},
        {"type": "fill",   "key": "general_vehicle_value", "label": "Vehicle Value", "value_col": "VehicleValue"},
        {"type": "select", "key": "general_vehicle_annual_mileage", "label": "Vehicle Annual Mileage", "value_col": "VehicleAnnualMileage"},
        {"type": "select", "key": "general_bank_name", "label": "Bank Name", "value_col": "BankName"},
        {"type": "select", "key": "general_pos", "label": "POS", "value_col": "POS"},
        {"type": "select", "key": "general_country_of_manufacture", "label": "Country of Manufacture", "value_col": "Origin"},
    ]
    
    registration_details_actions: List[Dict[str, Any]] = [
        {"type": "select",   "key": "registration_emirate", "label": "Emirate", "value_col": "Emirate"},
        {"type": "fill",     "key": "registration_date_of_first_registration", "label": "Date of First Registration", "value_col": "DateOfFirstRegistration"},
        {"type": "fill",     "key": "registration_tcf_no", "label": "TCF No", "value_col": "TCFNo"},
    ]
    
    other_details_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "other_is_modified", "label": "Is Modified", "value_col": "IsModified"},
        {"type": "click", "key": "other_is_non_gcc_vehicle", "label": "Is Non GCC", "value_col": "IsNonGCC"},
        {"type": "click", "key": "other_is_imported_vehicle", "label": "Is Imported Vehicle", "value_col": "IsImportedVehicle"},
        {"type": "click", "key": "other_is_third_party", "label": "Is Third Party", "value_col": "IsThirdParty"},
        {"type": "click", "key": "other_is_uninsured", "label": "Is Uninsured", "value_col": "IsUninsured"},
    ]
    
    save_actions: List[Dict[str, Any]] = [
        {"type": "click", "key": "save_button", "label": "Save Vehicle", "validation_check": True},
    ]

    # helper to only run actions whose keys exist in YAML
    def _filter(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [a for a in actions if a.get("key") and a.get("key") in selectors]

    # Execute sections
    for section_name, actions in [
        ("pre-upload",      _filter(pre_upload_actions)),
        ("general-details",  _filter(general_details_actions)),
        ("registration-details",  _filter(registration_details_actions)),
        ("other-details",  _filter(other_details_actions)),
    ]:
        if actions:
            try:
                await run_actions(page, actions=actions, selectors=selectors, df=df, logger=logger)
            except Exception as e:
                logger.error(f"Error during create-vehicle {section_name} actions: {e}")
                
    # --- Upload documents (optional) ---
    try:
        # Sample documents list (edit to match your files). Use file_name WITHOUT extension (helper will find passport.*)
        documents = [
            #registration card 1 documents
            {
                "path": "data/attachments",
                "file_name": "VCC",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "MULKIYA",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "MULKIYA_FRONT",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "E_MULKIYA_HYSA",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "KAVAK_QUOTATION",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            {
                "path": "data/attachments",
                "file_name": "ALBA_QUOTATION",
                "doc_type": "Registration Card 1",
                "expiry_date": ""
            },
            
            # registration card 2 documents
            {
                "path": "data/attachments",
                "file_name": "MULKIYA_BACK",
                "doc_type": "Registration Card 2",
                "expiry_date": ""
            }
        ]

        provided = locals().get("documents") or documents
        if not provided:
            logger.info("No 'documents' variable provided; skipping document upload.")
        else:
            logger.info(f"Uploading {len(provided)} document(s) from provided list.")
            # Get upload selector from YAML instead of hardcoding
            upload_selector = selectors.get("upload_document_field", "(//div[starts-with(@id,'DragnDrop__') and contains(@class,'dropzone')])[2]")
            await upload_files_via_drop(
                page,
                files=provided,
                drop_selector=upload_selector,
                logger=logger,
                run_id=run_id,
                wait_between=2.5,
            )
    except Exception as e:
        logger.error(f"Document upload failed (continuing): {e}")
        
    # --- Save action ---
    if save_actions:
        try:
            await run_actions(page, actions=save_actions, selectors=selectors, df=df, logger=logger, run_id=run_id)
        except Exception as e:
            logger.error(f"Error during create-client save action: {e}")
            raise

    logger.info("Create vehicle process completed")
