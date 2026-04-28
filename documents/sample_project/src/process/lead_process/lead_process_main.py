import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

from src.utils.error_handler import ValidationError
from src.services.db_service.data_service import DataService

# Data loaders & validation
from src.utils.load_data import load_section_from_yaml

from src.process.dashboard import open_lead_create

# from src.process.lead_process.create_lead import create_lead_process
from src.process.lead_process.create_lead_js import create_lead_process

from src.utils.send_email import send_success_email

async def lead_flow(page, df, dashboard_selectors, logger, run_id: str | None = None) -> bool:
    await open_lead_create(page, df, dashboard_selectors, logger)

    # load create lead selectors and run the create process
    create_lead_selectors = load_section_from_yaml("locators/lead/create_lead.yml", section="create_lead")
    try:
        await create_lead_process(page=page, df=df, selectors_group=create_lead_selectors, logger=logger, run_id=run_id)
        
        # Check if lead reference number exists
        lead_ref_no = df.at[0, 'lead_refr_no'] if 'lead_refr_no' in df.columns else None
        
        if lead_ref_no:
            logger.info(f"Lead reference number generated successfully: {lead_ref_no}")
            
            # Update database with lead reference number
            try:
                db_service = DataService(run_id=run_id, main_logger=logger)
                # Fixed: The lead process should use 'RequestId' instead of 'Id' to ensure it looks in the correct attachments folder
                raw_request_id = df.at[0, 'RequestId']
                request_id = str(int(raw_request_id))

                success = db_service.update_table_record(
                    table_name="Customers",
                    record_id=request_id,
                    updates={"LeadRefNo": lead_ref_no}
                )
                if success:
                    logger.info(f"Database updated with lead reference number for request ID: {request_id}")
                
                # Check for opt-out status
                optout_data = None
                try:
                    optout_data = db_service.check_optout_status(request_id)
                    if optout_data:
                        logger.info(f"OptOut detected for request ID: {request_id} - OptOutId: {optout_data['OptOutId']}")
                    else:
                        logger.info(f"No opt-out found for request ID: {request_id}")
                except Exception as optout_check_error:
                    logger.warning(f"Failed to check opt-out status: {optout_check_error}")
                
                # Send success email notification
                try:
                    await send_success_email(
                        process_type="lead",
                        df=df,
                        ref_no=lead_ref_no,
                        request_id=request_id,
                        optout_data=optout_data,
                        logger=logger
                    )
                    logger.info("Success email notification sent")
                except Exception as email_error:
                    logger.warning(f"Failed to send success email: {email_error}")
                
                return True
            except Exception as db_error:
                logger.error(f"Failed to update database with lead reference: {db_error}")
                return False
        else:
            logger.error("Lead reference number not generated - process failed")
            return False

    except ValidationError as ve:
        logger.error(f"ValidationError in lead_flow -> re-raising to stop run: {ve}")
        raise
    except Exception as e:
        logger.error(f"lead_flow failed: {e}")
        raise
