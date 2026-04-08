import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import pandas as pd

# Data loaders & validation
from src.utils.load_data import load_section_from_yaml
from src.utils.error_handler import ValidationError

from src.process.dashboard import open_client_search, open_client_create

from src.process.client_process.search_client_api import search_client_process
# from src.process.client_process.search_client import search_client_process
# OLD: from src.process.client_process.create_client import create_client_process
from src.process.client_process.create_client_js import create_client_process

# NOTE: removed @handle_process_errors decorator so ValidationError is not swallowed here
async def client_flow(page, df, dashboard_selectors, logger, run_id) -> bool:
    await open_client_search(page, df, dashboard_selectors, logger)

    search_client_selectors = load_section_from_yaml("locators/client/search_client.yml", section="search_client")
    try:
        is_new, match_info = await search_client_process(page=page, df=df, selectors_group=search_client_selectors, logger=logger, run_id=run_id)
    except ValidationError as ve:
        logger.error(f"ValidationError in search_client_process -> re-raising to stop run: {ve}")
        raise
    except Exception as e:
        logger.error(f"search_client_process failed: {e}")
        # re-raise unexpected exceptions so main can decide to stop as well
        raise

    # Store client status information in dataframe for use in success emails
    if isinstance(df, pd.DataFrame) and not df.empty:
        if is_new:
            df.at[0, '_client_status'] = 'new'
            df.at[0, '_client_matched_by'] = None
            df.at[0, '_client_matched_value'] = None
        else:
            df.at[0, '_client_status'] = 'existing'
            if match_info:
                df.at[0, '_client_matched_by'] = match_info.get('matched_by', 'Unknown')
                df.at[0, '_client_matched_value'] = match_info.get('matched_value', 'N/A')
                df.at[0, '_client_match_count'] = match_info.get('match_count', 0)

    # is_new = True

    if is_new:
        logger.info("Search result: NEW customer detected. Proceeding to create customer.")
        
        # Create the client (call create flow)
        try:
            # call create flow and ensure ValidationError bubbles up
            await create_client_flow(page, df, dashboard_selectors, logger, run_id=run_id)
            logger.info("Create client flow completed.")
        except ValidationError as ve:
            logger.error(f"ValidationError in create_client_flow -> re-raising to stop run: {ve}")
            raise
        except Exception as e:
            logger.error(f"Create client flow failed: {e}")
            # re-raise unexpected exceptions so main can decide to stop
            raise
    else:
        logger.info("Search result: Existing customer found. Match information stored in dataframe.")
        logger.info("Client will be selected during Lead/Prospect creation process.")

    # Always return True to continue with Prospect/Lead creation
    return True

# NOTE: removed @handle_process_errors decorator so ValidationError from create_client_process is not intercepted
async def create_client_flow(page, df, dashboard_selectors, logger, run_id: str | None = None):
    await open_client_create(page, df, dashboard_selectors, logger)

    # load create client selectors and run the create process
    create_client_selectors = load_section_from_yaml("locators/client/create_client.yml", section="create_client")
    # forward run_id into create_client_process
    # OLD: await create_client_process(page=page, df=df, selectors_group=create_client_selectors, logger=logger, run_id=run_id)
    await create_client_process(page=page, df=df, selectors_group=create_client_selectors, logger=logger, run_id=run_id)