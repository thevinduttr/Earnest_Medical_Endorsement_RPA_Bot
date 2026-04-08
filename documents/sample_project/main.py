import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from typing import Dict, Any, Optional, Tuple, List
import logging

# Processes
from src.process.login import login

from src.process.client_process.client_process_main import client_flow
from src.process.lead_process.lead_process_main import lead_flow
from src.process.prospect_process.prospect_process_main import prospect_flow

# new: process-level email helper
from src.utils.send_email import send_error_email as send_error_email_helper
from src.utils.support_functions import notify_process_error

# Data loaders & validation
from src.utils.load_data import (
    load_yaml_file,
    load_section_from_yaml,   # choose YAML group: 'login' and 'dashboard'
    load_json_df,
    get_yml_value,
    validate_config_yaml,
    validate_required_df,
)

# Database service
from src.services.db_service.data_service import DataService, DatabaseConnectionError

# Data mapping utilities
from src.utils.data_mapper import DataMapper, apply_nationality_mapping

# formatting utilities
from src.utils.date_formatter import format_standard_date_columns
# from src.utils.mobile_formatter import format_standard_mobile_columns

# Logging
from src.utils.logger import init_run_loggers, make_run_id

# Mailer
from src.utils.mailer import send_error_email_with_screenshots

# Attachment manager
from src.utils.attachment_manager import download_request_attachments, log_attachment_summary

# Clear folders utility
from src.utils.clear_foders_files import clear_attachments_folder

# Playwright Tracing
from src.utils.playwright_tracer import PlaywrightTracer, get_trace_viewer_command

# add ValidationError import
from src.utils.error_handler import ValidationError

def _load_configuration(run_id: str, request_id: str, loggers: dict = None):
    """
    Load and validate all configuration files.
    Args:
        run_id: str - The run identifier for logging
        request_id: str - The request ID to load data for
        loggers: dict - Dictionary containing logger instances
    """
    cfg = load_yaml_file("config/base.yml")
    validate_config_yaml(cfg, required_keys=["paths.base_url"])
    
    login_selectors = load_section_from_yaml("locators/main/login_page.yml", section="login")
    dashboard_selectors = load_section_from_yaml("locators/main/dashboard_page.yml", section="dashboard")
    
    # Initialize database service with run_id and main logger for comprehensive logging
    db_service = DataService(run_id=run_id, main_logger=loggers["main"])
    
    # Get bot_id from config
    bot_id = get_yml_value(cfg, "bot_details.id", "1")
    
    # Load credentials from database with filtering
    # You can modify these parameters as needed or get them from config
    df_credentials = db_service.load_credentials(
        bot_id=bot_id,
        request_type="CRM",
        portal="CRM"
    )
    validate_required_df(df_credentials, required_cols=["Username", "Password"])
    
    # Load client data from database using generic table loader
    df_data = db_service.load_table_data(table_name="Customers", record_id=request_id)
    
    # Apply data mappings to transform database values to CRM-compatible values
    try:
        # Apply nationality mapping using the convenience function
        df_data = apply_nationality_mapping(
            df=df_data, 
            db_service=db_service, 
            logger=loggers["main"] if loggers else None
        )
        
        # Format date columns to remove time components
        df_data = format_standard_date_columns(
            df=df_data,
            logger=loggers["main"] if loggers else None
        )
        
        # Mobile number formatting disabled - numbers entered as-is from database
        # df_data = format_standard_mobile_columns(
        #     df=df_data,
        #     logger=loggers["main"] if loggers else None
        # )
        
    except Exception as e:
        error_msg = f"Error applying data mappings or date formatting: {str(e)}"
        if loggers and "main" in loggers:
            loggers["main"].error(error_msg)
        else:
            print(error_msg)
    
    email_cfg = load_yaml_file("config/email.yml")
    
    return cfg, login_selectors, dashboard_selectors, df_credentials, df_data, email_cfg


def _update_crm_status_based_on_result(
    db_service: DataService, 
    request_id: str, 
    process_success: bool, 
    run_id: str, 
    main_log: logging.Logger, 
    process_name: str
) -> bool:
    """
    Updates CRM status based on validation errors and process success.
    
    Args:
        db_service: DataService instance
        request_id: Request ID to update
        process_success: Boolean indicating if the process was successful
        run_id: Run ID for validation flag checking
        main_log: Logger instance
        process_name: Name of the process (for logging)
    
    Returns:
        bool: True if status was updated to SUCCESS, False if updated to FAILED
    """
    try:
        # Validate db_service parameter
        if db_service is None:
            main_log.error(f"Database service is None in {process_name} status update")
            return False
            
        # Check if db_service has the required method
        if not hasattr(db_service, 'update_crm_status'):
            main_log.error(f"Database service missing update_crm_status method in {process_name}")
            return False
        
        # Check for validation errors
        validation_flag = Path(f"data/logs/{run_id}/validation_error.flag")
        has_validation_error = validation_flag.exists()
        
        # Both conditions must be met for SUCCESS: no validation errors AND process success
        if not has_validation_error and process_success:
            main_log.info(f"{process_name} process completed successfully with reference number and no validation errors")
            try:
                result = db_service.update_crm_status(request_id, "SUCCESS")
                if result:
                    main_log.info(f"Updated CRMStatus to SUCCESS for request_id: {request_id}")
                    return True
                else:
                    main_log.error(f"Failed to update CRMStatus to SUCCESS (method returned False) for request_id: {request_id}")
                    return False
            except Exception as db_err:
                main_log.error(f"Failed to update CRMStatus to SUCCESS for request_id {request_id}: {db_err}")
                main_log.error(f"Database service type: {type(db_service)}")
                return False
        else:
            # Update to FAILED if either condition fails
            if has_validation_error:
                main_log.error(f"Validation error detected in {process_name.lower()} process - updating CRM status to FAILED")
            elif not process_success:
                main_log.error(f"{process_name} process completed but no reference number generated - updating CRM status to FAILED")
            else:
                main_log.error(f"{process_name} process failed - updating CRM status to FAILED")
            
            try:
                result = db_service.update_crm_status(request_id, "FAILED")
                if result:
                    main_log.info(f"Updated CRMStatus to FAILED for request_id: {request_id}")
                    return False
                else:
                    main_log.error(f"Failed to update CRMStatus to FAILED (method returned False) for request_id: {request_id}")
                    return False
            except Exception as db_err:
                main_log.error(f"Failed to update CRMStatus to FAILED for request_id {request_id}: {db_err}")
                main_log.error(f"Database service type: {type(db_service)}")
                return False
                
    except Exception as e:
        main_log.error(f"Unexpected error in _update_crm_status_based_on_result for {process_name}: {e}")
        return False


def _handle_process_exception(
    db_service: DataService, 
    request_id: str, 
    main_log: logging.Logger, 
    process_name: str, 
    exception: Exception
) -> bool:
    """
    Handles exceptions that occur during process execution and updates CRM status accordingly.
    
    Args:
        db_service: DataService instance
        request_id: Request ID to update
        main_log: Logger instance
        process_name: Name of the process (for logging)
        exception: The exception that occurred
    
    Returns:
        bool: True if this was a ValidationError (should stop processing), False otherwise
    """
    try:
        # Validate db_service parameter
        if db_service is None:
            main_log.error(f"Database service is None in {process_name} exception handler")
            return False
            
        if isinstance(exception, ValidationError):
            try:
                result = db_service.update_crm_status(request_id, "FAILED")
                if result:
                    main_log.info(f"Updated CRMStatus to FAILED due to ValidationError in {process_name.lower()} process for request_id: {request_id}")
                else:
                    main_log.error(f"Failed to update CRMStatus (method returned False) for ValidationError in {process_name} for request_id: {request_id}")
            except Exception as db_err:
                main_log.error(f"Failed to update CRMStatus to FAILED for request_id {request_id}: {db_err}")
                main_log.error(f"Database service type: {type(db_service)}")
            return True  # Stop processing for ValidationError
        else:
            # For other errors, also update to FAILED
            try:
                result = db_service.update_crm_status(request_id, "FAILED")
                if result:
                    main_log.info(f"Updated CRMStatus to FAILED due to {process_name.lower()} process error for request_id: {request_id}")
                else:
                    main_log.error(f"Failed to update CRMStatus (method returned False) for {process_name} error for request_id: {request_id}")
            except Exception as db_err:
                main_log.error(f"Failed to update CRMStatus to FAILED for request_id {request_id}: {db_err}")
                main_log.error(f"Database service type: {type(db_service)}")
            return False  # Continue processing for other errors
            
    except Exception as e:
        main_log.error(f"Unexpected error in _handle_process_exception for {process_name}: {e}")
        return False


async def _run_automation_flows(page, df_data, dashboard_selectors, loggers, run_id, request_id):
    screenshots = []
    # Initialize database service for status updates
    db_service = DataService(run_id=run_id, main_logger=loggers["main"])
    
    # Client Flow
    try:
        is_new = await client_flow(page, df_data, dashboard_selectors, logger=loggers["client"], run_id=run_id)
        
        # immediate stop if validation flag present (helper writes this flag)
        try:
            flag = Path(f"data/logs/{run_id}/validation_error.flag")
            if flag.exists():
                loggers["main"].error(f"Validation error detected in client process (flag file present) — stopping run and updating CRM status to FAILED (run_id={run_id}).")
                try:
                    db_service.update_crm_status(request_id, "FAILED")
                    loggers["main"].info(f"Updated CRMStatus to FAILED due to validation error for request_id: {request_id}")
                except Exception as db_err:
                    loggers["main"].error(f"Failed to update CRMStatus to FAILED for request_id {request_id}: {db_err}")
                return screenshots, True
        except Exception:
            pass

        # Note: Client flow now handles both new client creation and existing client selection
        # Process continues to Prospect/Lead creation in either case
        
        shot_search = Path(f"data/logs/{run_id}/after-client-search.png")
        await page.screenshot(path=str(shot_search), full_page=True)
        screenshots.append(shot_search)

    except Exception as e:
        # Handle exception and update CRM status
        should_stop = _handle_process_exception(
            db_service=db_service,
            request_id=request_id,
            main_log=loggers["main"],
            process_name="Client",
            exception=e
        )
        
        if should_stop:
            return screenshots, True
            
        await notify_process_error(page=page, logger=loggers["client"], run_id=run_id, subject=f"[{run_id}] Client process error", body=f"Client flow failed: {e}", shot_name="client_error.png", request_id=request_id)
        # continue to downstream decision (downstream may skip if needed)

    # Downstream flows based on crm_status
    try:
        crm_status = ""
        try:
            if hasattr(df_data, "iloc") and len(df_data) > 0:
                crm_status = str(df_data.iloc[0].get("AppStatus", "")).strip().upper()
        except Exception:
            crm_status = ""

        main_log = loggers["main"]
        main_log.info(f"Determined crm_status='{crm_status}' for downstream processing")

        if crm_status == "LEAD":
            try:
                lead_success = await lead_flow(page, df_data, dashboard_selectors, logger=loggers["lead"], run_id=run_id)
                
                # Update CRM status based on validation and process success
                _update_crm_status_based_on_result(
                    db_service=db_service,
                    request_id=request_id,
                    process_success=lead_success,
                    run_id=run_id,
                    main_log=main_log,
                    process_name="Lead"
                )
                    
                shot_lead = Path(f"data/logs/{run_id}/after-lead.png")
                await page.screenshot(path=str(shot_lead), full_page=True)
                screenshots.append(shot_lead)
            except Exception as e:
                # Handle exception and update CRM status
                should_stop = _handle_process_exception(
                    db_service=db_service,
                    request_id=request_id,
                    main_log=main_log,
                    process_name="Lead",
                    exception=e
                )
                
                if should_stop:
                    return screenshots, True
                
                await notify_process_error(page=page, logger=loggers["lead"], run_id=run_id, 
                                        subject=f"[{run_id}] Lead process error", 
                                        body=str(e), shot_name="lead_error.png", request_id=request_id)
        elif crm_status in ["PROSPECT", "LEAD PROSPECT"]:
            try:
                prospect_success = await prospect_flow(page, df_data, dashboard_selectors, logger=loggers["prospect"], run_id=run_id)
                
                # Update CRM status based on validation and process success
                _update_crm_status_based_on_result(
                    db_service=db_service,
                    request_id=request_id,
                    process_success=prospect_success,
                    run_id=run_id,
                    main_log=main_log,
                    process_name="Prospect"
                )
                
                shot_prospect = Path(f"data/logs/{run_id}/after-prospect.png")
                await page.screenshot(path=str(shot_prospect), full_page=True)
                screenshots.append(shot_prospect)
            except Exception as e:
                # Handle exception and update CRM status
                should_stop = _handle_process_exception(
                    db_service=db_service,
                    request_id=request_id,
                    main_log=main_log,
                    process_name="Prospect",
                    exception=e
                )
                
                if should_stop:
                    return screenshots, True
                
                await notify_process_error(page=page, logger=loggers["prospect"], run_id=run_id, 
                                        subject=f"[{run_id}] Prospect process error", 
                                        body=str(e), shot_name="prospect_error.png", request_id=request_id)
        else:
            main_log.info(f"No downstream flow executed for crm_status='{crm_status}'. Skipping lead/prospect steps.")
    except Exception as e:
        loggers["main"].error(f"Downstream flow decision/execution error: {e}")

    return screenshots, False


async def run():
    while True:  # Continuous loop
        try:
            # Get bot_id from config
            cfg = load_yaml_file("config/base.yml")
            bot_id = get_yml_value(cfg, "bot_details.id", "UNKNOWN")
            
            # Create DB service instance for getting request_id and cleanup
            db_service = DataService()
            
            # Reset any stuck requests from previous runs (optional - helps with crash recovery)
            try:
                reset_count = db_service.reset_stuck_requests(max_processing_hours=2)
                if reset_count > 0:
                    print(f"Reset {reset_count} stuck requests to allow processing by any bot")
            except Exception as cleanup_error:
                print(f"Warning: Could not reset stuck requests: {cleanup_error}")
            
            request_id = db_service.get_next_request_id(bot_id=bot_id)
            
            if not request_id:
                print("No requests available. Waiting 30 seconds...")
                await asyncio.sleep(30)  # Wait before checking again
                continue
            
            # Initialize run + loggers with bot context
            run_id = make_run_id(bot_id=bot_id, request_id=request_id)
            loggers = init_run_loggers(
                run_id=run_id,
                bot_id=bot_id,
                request_id=request_id,
                debug=True
            )
            
            main_logger = loggers["main"]
            main_logger.info(f"Run started ({run_id.split('/')[-1].split('-')[-1]})")

            # Clear attachments folder before processing
            main_logger.info("Clearing attachments folder before processing new request")
            clear_success = clear_attachments_folder(logger=main_logger)
            if not clear_success:
                main_logger.warning("Failed to clear attachments folder, but continuing with processing")

            # Load configuration with request_id
            cfg, login_selectors, dashboard_selectors, df_credentials, df_data, email_cfg = _load_configuration(
                run_id=run_id,
                request_id=request_id,
                loggers=loggers
            )
            
            # Download attachments for this request
            main_logger.info(f"Downloading attachments for request ID: {request_id}")
            try:
                attachment_result = await download_request_attachments(
                    request_id=request_id,
                    logger=main_logger
                )
                log_attachment_summary(attachment_result, main_logger)
                
                if attachment_result["success"]:
                    main_logger.info(f"Attachment download completed successfully for request {request_id}")
                else:
                    main_logger.warning(f"Attachment download encountered issues for request {request_id}: {attachment_result['message']}")
                    
            except Exception as attachment_error:
                main_logger.error(f"Failed to download attachments for request {request_id}: {attachment_error}")
                # Continue with process even if attachment download fails
            
            base_url = get_yml_value(cfg, "paths.base_url")
            headless = bool(get_yml_value(cfg, "browser.headless", True))
            vp_w = int(get_yml_value(cfg, "browser.viewport.width", 1440))
            vp_h = int(get_yml_value(cfg, "browser.viewport.height", 900))

            screenshots = []
            tracer = None  # Initialize tracer variable
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=headless)
                context = await browser.new_context(viewport={"width": vp_w, "height": vp_h})
                
                # Initialize and start Playwright tracing
                try:
                    tracing_enabled = bool(get_yml_value(cfg, "tracing.enabled", True))
                    if tracing_enabled:
                        trace_screenshots = bool(get_yml_value(cfg, "tracing.screenshots", True))
                        trace_snapshots = bool(get_yml_value(cfg, "tracing.snapshots", True))
                        trace_sources = bool(get_yml_value(cfg, "tracing.sources", True))
                        
                        tracer = PlaywrightTracer(run_id, main_logger)
                        await tracer.start_tracing(
                            context=context,
                            screenshots=trace_screenshots,
                            snapshots=trace_snapshots,
                            sources=trace_sources,
                            title=f"CRM_Automation_Request_{request_id}"
                        )
                        main_logger.info(f"Playwright tracing enabled for request {request_id}")
                    else:
                        main_logger.info("Playwright tracing disabled via configuration")
                        tracer = None
                except Exception as trace_err:
                    main_logger.warning(f"Failed to enable Playwright tracing: {trace_err}")
                    tracer = None
                
                page = await context.new_page()

                main_logger.info(f"Navigating to {base_url}")
                await page.goto(str(base_url), wait_until="domcontentloaded")

                # Login
                await login(
                    page,
                    df_credentials,
                    login_selectors,
                    logger=loggers["client"],
                    run_id=run_id,
                    request_id=request_id,
                )
                shot_login = Path(f"data/logs/{run_id}/after-login.png")
                await page.screenshot(path=str(shot_login), full_page=True)
                screenshots.append(shot_login)
                main_logger.info(f"Captured post-login screenshot: {shot_login}")
                
                # Capture trace screenshot after login if tracing is active
                if tracer:
                    try:
                        await tracer.capture_trace_screenshot(page, "after_login")
                    except Exception as trace_err:
                        main_logger.warning(f"Failed to capture trace screenshot after login: {trace_err}")

                # Run automation flows - pass request_id for database updates
                flow_screenshots, _ = await _run_automation_flows(page, df_data, dashboard_selectors, loggers, run_id, request_id)
                screenshots.extend(flow_screenshots)
                
                # Stop tracing and save trace file before closing context
                if tracer:
                    try:
                        trace_file = await tracer.stop_tracing()
                        if trace_file:
                            main_logger.info(f"Trace saved successfully: {trace_file}")
                            main_logger.info(f"To view trace: {get_trace_viewer_command(trace_file)}")
                    except Exception as trace_err:
                        main_logger.error(f"Failed to stop tracing: {trace_err}")

                await context.close()
                await browser.close()

            main_logger.info("Run completed successfully")

        except DatabaseConnectionError as db_conn_err:
            # Handle database connection errors specially - these should trigger retry, not failure
            err_text = f"Database connection error: {db_conn_err}"
            if 'main_logger' in locals():
                main_logger.error(err_text)
                main_logger.info("Database connection error detected - will retry after releasing request back to PENDING")
            else:
                print(err_text)
                print("Database connection error detected - will retry after releasing request back to PENDING")

            # Release the request back to PENDING so it can be retried (by this bot or others)
            try:
                if 'request_id' in locals() and request_id:
                    if 'run_id' in locals() and 'main_logger' in locals():
                        retry_db_service = DataService(run_id=run_id, main_logger=main_logger)
                    else:
                        retry_db_service = DataService()
                    
                    retry_db_service.release_request_on_failure(
                        request_id, 
                        bot_id=bot_id, 
                        error_message=f"Database connection error - released for retry: {str(db_conn_err)[:400]}"
                    )
                    
                    if 'main_logger' in locals():
                        main_logger.info(f"Released request {request_id} back to PENDING due to database connection error - will be retried")
                    else:
                        print(f"Released request {request_id} back to PENDING due to database connection error - will be retried")
            except Exception as release_err:
                if 'main_logger' in locals():
                    main_logger.error(f"Failed to release request after database connection error: {release_err}")
                else:
                    print(f"Failed to release request after database connection error: {release_err}")

            # Wait longer before retrying for database connection errors
            print("Waiting 30 seconds before retrying due to database connection error...")
            await asyncio.sleep(30)
            continue

        except ValidationError as validation_err:
            err_text = f"Run stopped due to validation error: {validation_err}"
            if 'main_logger' in locals():
                main_logger.error(err_text)
            else:
                print(err_text)

            # Validation failures must be marked FAILED and should not be released back to PENDING.
            try:
                if 'request_id' in locals() and request_id:
                    if 'run_id' in locals() and 'main_logger' in locals():
                        validation_db_service = DataService(run_id=run_id, main_logger=main_logger)
                    else:
                        validation_db_service = DataService()

                    update_result = validation_db_service.update_crm_status(request_id, "FAILED")
                    if 'main_logger' in locals():
                        if update_result:
                            main_logger.info(f"Updated CRMStatus to FAILED for validation error, request_id: {request_id}")
                        else:
                            main_logger.error(f"Failed to update CRMStatus to FAILED (returned False), request_id: {request_id}")
                    else:
                        print(f"CRMStatus set to FAILED for validation error, request_id: {request_id}")
            except Exception as db_err:
                if 'main_logger' in locals():
                    main_logger.error(f"Failed to set CRMStatus to FAILED after validation error: {db_err}")
                else:
                    print(f"Failed to set CRMStatus to FAILED after validation error: {db_err}")

            await asyncio.sleep(5)
            continue

        except Exception as e:
            err_text = f"Run failed: {e}"
            if 'main_logger' in locals():
                main_logger.error(err_text)
            else:
                print(err_text)

            # Update CRM status to FAILED for general run failures and release request for other bots
            try:
                if 'request_id' in locals() and 'run_id' in locals() and 'main_logger' in locals():
                    db_service = DataService(run_id=run_id, main_logger=main_logger)
                    # Release the request back to PENDING so other bots can pick it up
                    db_service.release_request_on_failure(request_id, bot_id=bot_id, error_message=str(e)[:500])
                    main_logger.info(f"Released request {request_id} back to PENDING due to bot failure - other bots can now process it")
                elif 'request_id' in locals():
                    db_service = DataService()
                    db_service.release_request_on_failure(request_id, bot_id=bot_id, error_message=str(e)[:500])
                    print(f"Released request {request_id} back to PENDING due to bot failure")
            except Exception as db_err:
                if 'main_logger' in locals():
                    main_logger.error(f"Failed to release request {request_id}: {db_err}")
                else:
                    print(f"Failed to release request {request_id}: {db_err}")

            # Best-effort error screenshot and email
            try:
                if 'page' in locals():
                    err_shot = Path(f"data/logs/{run_id}/error.png")
                    await page.screenshot(path=str(err_shot), full_page=True)
                    screenshots.append(err_shot)
                    
                if 'email_cfg' in locals() and 'screenshots' in locals():
                    # Extract request_id from run_id if available
                    req_id = None
                    if 'request_id' in locals():
                        req_id = request_id
                    elif 'run_id' in locals():
                        from src.utils.send_email import extract_request_id_from_run_id
                        req_id = extract_request_id_from_run_id(run_id)
                    
                    # Pass main_logger if available
                    log = main_logger if 'main_logger' in locals() else None
                    
                    await send_error_email_with_screenshots(
                        email_cfg,
                        subject_prefix=f"[{run_id}]",
                        error_message=err_text,
                        screenshots=screenshots,
                        request_id=req_id,
                        logger=log,
                    )
            except Exception as notify_err:
                print(f"Failed to capture error details: {notify_err}")

            # Wait a bit before retrying
            await asyncio.sleep(1)
            continue

if __name__ == "__main__":
    asyncio.run(run())
