import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

# Data loaders & validation
from src.utils.load_data import load_section_from_yaml

from src.process.prospect_process.vehicle_process.search_select_vehicle import search_select_vehicle_process
# from src.process.prospect_process.vehicle_process.create_vehicle import create_vehicle_process
from src.process.prospect_process.vehicle_process.create_vehicle_js import create_vehicle_process

async def vehicle_flow(page, df, dashboard_selectors, logger, run_id: str | None = None) -> bool:
    search_vehicle_selectors = load_section_from_yaml("locators/prospect/vehicle/search_vehicle.yml", section="search_vehicle")
    is_new_vehicle = await search_select_vehicle_process(page=page, df=df, selectors_group=search_vehicle_selectors, logger=logger, run_id=run_id)

    if is_new_vehicle:
        logger.info("Search result: NEW vehicle detected. Proceeding to create vehicle.")

        # Create the vehicle (call create flow)
        try:
            fuzzy_match_result = await create_vehicle_flow(page, df, dashboard_selectors, logger, run_id=run_id)
            logger.info("Create vehicle flow completed.")
            if fuzzy_match_result and fuzzy_match_result.get('total_fuzzy_matches', 0) > 0:
                logger.info(f"📧 Vehicle creation included {fuzzy_match_result['total_fuzzy_matches']} fuzzy matches for email reporting")
        except Exception as e:
            logger.error(f"Create vehicle flow failed: {e}")
            raise  # Re-raise to prevent continuing with prospect save
    else:
        logger.info("Search result: Existing or duplicate vehicle(s) found. Skipping creation and cannot process others.")

    return is_new_vehicle

async def create_vehicle_flow(page, df, dashboard_selectors, logger, run_id: str | None = None):
    # load create vehicle selectors and run the create process
    create_vehicle_selectors = load_section_from_yaml("locators/prospect/vehicle/create_vehicle.yml", section="create_vehicle")
    fuzzy_match_result = await create_vehicle_process(page=page, df=df, selectors_group=create_vehicle_selectors, logger=logger, run_id=run_id)
    return fuzzy_match_result