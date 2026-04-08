import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

from src.utils.error_handler import ValidationError

# Data loaders & validation
from src.utils.load_data import load_section_from_yaml

from src.process.dashboard import open_prospect_create

# from src.process.prospect_process.create_prospect import create_prospect_process
from src.process.prospect_process.create_prospect_js import create_prospect_process

from src.services.db_service.data_service import DataService
from src.utils.send_email import send_success_email

# NOTE: removed @handle_process_errors decorator so ValidationError is not swallowed here
async def prospect_flow(page, df, dashboard_selectors, logger, run_id: str | None = None) -> bool:
    # Check for opt-out status BEFORE creating prospect
    optout_data = None
    db_service = None
    try:
        db_service = DataService(run_id=run_id, main_logger=logger)
        raw_request_id = df.at[0, 'RequestId']
        request_id = str(int(raw_request_id))
        
        optout_data = db_service.check_optout_status(request_id)
        if optout_data:
            logger.info(f"OptOut detected for request ID: {request_id} - OptOutId: {optout_data['OptOutId']}. Will set RenewalProcessingStatus to OPTOUT.")
        else:
            logger.info(f"No opt-out found for request ID: {request_id}")
    except Exception as optout_check_error:
        logger.warning(f"Failed to check opt-out status before prospect creation: {optout_check_error}")
    
    await open_prospect_create(page, df, dashboard_selectors, logger)

    # load create prospect selectors and run the create process
    create_prospect_selectors = load_section_from_yaml("locators/prospect/create_prospect.yml", section="create_prospect")
    try:
        await create_prospect_process(page=page, df=df, selectors_group=create_prospect_selectors, logger=logger, run_id=run_id, optout_data=optout_data)
        
        # Check if prospect reference number exists
        prospect_ref_no = df.at[0, 'crm_ref_no'] if 'crm_ref_no' in df.columns else None
        
        if prospect_ref_no:
            logger.info(f"Prospect reference number generated successfully: {prospect_ref_no}")
            
            # Update database with prospect reference number
            try:
                if not db_service:
                    db_service = DataService(run_id=run_id, main_logger=logger)
                # Fixed: Convert float RequestId to int then to string to avoid decimal issues
                raw_request_id = df.at[0, 'RequestId']
                request_id = str(int(raw_request_id))
                success = db_service.update_table_record(
                    table_name="Customers",
                    record_id=request_id,
                    updates={"ProspectRefNo": prospect_ref_no}
                )
                if success:
                    logger.info(f"Database updated with prospect reference number for request ID: {request_id}")
                
                # Send success email notification
                try:
                    await send_success_email(
                        process_type="prospect",
                        df=df,
                        ref_no=prospect_ref_no,
                        request_id=request_id,
                        optout_data=optout_data,
                        logger=logger
                    )
                    logger.info("Success email notification sent")
                except Exception as email_error:
                    logger.warning(f"Failed to send success email: {email_error}")
                
                return True
            except Exception as db_error:
                logger.error(f"Failed to update database with prospect reference: {db_error}")
                return False
        else:
            logger.error("Prospect reference number not generated - process failed")
            return False

    except ValidationError as ve:
        logger.error(f"ValidationError in prospect_flow -> re-raising to stop run: {ve}")
        raise
    except Exception as e:
        logger.error(f"prospect_flow failed: {e}")
        raise

    logger.info(f"Create Prospect flow completed and CRM ref no stored in DF: {df.at[0, 'crm_ref_no']}")