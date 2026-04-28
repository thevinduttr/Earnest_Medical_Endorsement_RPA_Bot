"""Helper wrapper around existing mailer to provide a simple send_error_email
and an async decorator to capture screenshots, logs and send notifications.

This module reads `config.ini` (project root) for provider credentials and
respects send_emails toggle. It uses the existing `src.utils.mailer` where
possible to avoid duplicating SMTP logic.
"""
from __future__ import annotations
import asyncio
import configparser
import logging
import time
from pathlib import Path
from typing import Optional, Sequence, Dict, Any

from . import mailer
from .error_handler import ValidationError

DEFAULT_CONFIG = Path("config.ini")
LOG_TAIL_DEFAULT = 200


def _read_ini(path: Optional[Path] = None) -> dict:
    p = Path(path or DEFAULT_CONFIG)
    cfg = {"send_emails": False}
    if not p.exists():
        return cfg
    parser = configparser.ConfigParser()
    parser.read(p)
    if "EMAIL" in parser:
        em = parser["EMAIL"]
        cfg.update({
            "provider": em.get("provider", "").strip(),
            "smtp_server": em.get("smtp_server", "").strip(),
            "smtp_port": em.get("smtp_port", "").strip(),
            "sender_email": em.get("sender_email", "").strip(),
            "sender_password": em.get("sender_password", "").strip(),
            "recipient_emails": [e.strip() for e in em.get("recipient_emails", "").split(",") if e.strip()],
            "cc_emails": [e.strip() for e in em.get("cc_emails", "").split(",") if e.strip()],
            "bcc_emails": [e.strip() for e in em.get("bcc_emails", "").split(",") if e.strip()],
            "send_emails": em.get("send_emails", "true").strip().lower() in ("1", "true", "yes"),
        })
    if "OPTIONS" in parser:
        opt = parser["OPTIONS"]
        cfg["log_tail_lines"] = int(opt.get("log_tail_lines", LOG_TAIL_DEFAULT))
    else:
        cfg["log_tail_lines"] = LOG_TAIL_DEFAULT
    return cfg


async def send_error_email(
    subject: str,
    body: str,
    *,
    screenshot_path: Optional[Path] = None,
    log_files: Optional[Sequence[Path]] = None,
    config_path: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
    request_id: Optional[str] = None,
    attachments_dir: Optional[str] = None,
) -> None:
    """Send an error email using config.ini. Uses existing mailer.send_email_async.

    - Builds a minimal email_cfg expected by `src.utils.mailer`.
    - If send_emails is false in config.ini this is a no-op (but logs when logger provided).
    - If request_id is provided, automatically includes all downloaded documents from attachments folder.
    """
    cfg = _read_ini(config_path)
    if not cfg.get("send_emails"):
        if logger:
            logger.info("Email notifications are disabled in config.ini; skipping error email.")
        return

    # Build mailer-friendly dict
    email_cfg = {
        # keep keys similar to existing mailer structure
        "provider": cfg.get("provider"),
        "smtp_host": cfg.get("smtp_server"),
        "smtp_port": cfg.get("smtp_port"),
        "use_tls": True,
        "sender": {"email": cfg.get("sender_email"), "name": "RPA Notifier"},
        "auth": {"username": cfg.get("sender_email"), "password": cfg.get("sender_password")},
        "recipients": {
            "to": list(cfg.get("recipient_emails") or []),
            "cc": list(cfg.get("cc_emails") or []),
            "bcc": list(cfg.get("bcc_emails") or [])
        },
        # allow mailer to use defaults for retry/timeouts
    }

    # Create temp directory for email attachments if needed
    temp_attachments_dir = Path("data/outputs/email_attachments")
    temp_attachments_dir.mkdir(parents=True, exist_ok=True)
    
    attachments = []
    try:
        # Copy screenshot if exists
        if screenshot_path and Path(screenshot_path).exists():
            screenshot_copy = temp_attachments_dir / f"screenshot_{int(time.time())}_{Path(screenshot_path).name}"
            screenshot_copy.write_bytes(Path(screenshot_path).read_bytes())
            attachments.append(screenshot_copy)

        # NOTE: Log files are NOT attached to error emails (removed as per CR update)
        # Only screenshots and submitted documents are attached

        # NEW: Copy downloaded documents if request_id provided
        if request_id:
            # Determine base path for attachments
            base_path = attachments_dir if attachments_dir else "data/attachments"
            
            if logger:
                logger.info(f"Including submitted documents for request {request_id} in email")
            
            # Get all downloaded attachments for this request (inline to avoid import issues)
            request_dir = Path(base_path) / f"request_{request_id}"
            document_files = []
            if request_dir.exists():
                document_files = [str(file_path) for file_path in request_dir.glob('*') if file_path.is_file()]
            
            if document_files:
                if logger:
                    logger.info(f"Found {len(document_files)} submitted document(s) to attach")
                
                # Copy each document to temp folder for email
                for doc_path_str in document_files:
                    doc_path = Path(doc_path_str)
                    if doc_path.exists():
                        doc_copy = temp_attachments_dir / f"doc_{int(time.time())}_{doc_path.name}"
                        doc_copy.write_bytes(doc_path.read_bytes())
                        attachments.append(doc_copy)
                        if logger:
                            logger.info(f"Attached submitted document: {doc_path.name}")
                        # Small delay to ensure unique timestamps
                        time.sleep(0.01)
            else:
                if logger:
                    logger.info(f"No submitted documents found for request {request_id}")

    except Exception as copy_err:
        if logger:
            logger.error(f"Failed to copy attachments: {copy_err}")

    # Use the existing mailer which expects async send
    try:
        await mailer.send_email_async(
            email_cfg,
            subject=subject,
            body=body,
            to=email_cfg["recipients"]["to"],
            cc=email_cfg["recipients"]["cc"],
            bcc=email_cfg["recipients"]["bcc"],
            attachments=attachments or None,
            logger=logger,
        )
    except Exception as e:
        if logger:
            logger.error(f"Failed to send error email: {e}")
    finally:
        # Clean up temporary copies after sending (or if sending fails)
        for temp_file in attachments:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception as cleanup_err:
                if logger:
                    logger.debug(f"Failed to clean up temporary attachment {temp_file}: {cleanup_err}")


def _find_log_tail(logfile: Path, tail_lines: int = LOG_TAIL_DEFAULT) -> str:
    try:
        if not logfile.exists():
            return ""
        with logfile.open("rb") as fh:
            # read last ~10KB then splitlines
            fh.seek(0, 2)
            size = fh.tell()
            to_read = min(size, 100 * 1024)
            fh.seek(max(0, size - to_read))
            data = fh.read().decode(errors="replace").splitlines()
        return "\n".join(data[-tail_lines:])
    except Exception:
        return ""


def _extract_log_file_from_logger(logger: logging.Logger) -> Optional[Path]:
    # Look for a FileHandler and return its baseFilename
    if not logger:
        return None
    for h in getattr(logger, "handlers", []):
        try:
            base = getattr(h, "baseFilename", None)
            if base:
                return Path(base)
        except Exception:
            continue
    return None


def extract_request_id_from_run_id(run_id: str) -> Optional[str]:
    """Extract request_id from run_id format: 'run_YYYY-MM-DD/bot_X-req_XXXXXX'
    
    Args:
        run_id: Run ID string in format like 'run_2026-02-23/bot_1-req_815948000'
        
    Returns:
        Request ID string (e.g., '815948000') or None if not found
    """
    try:
        if not run_id:
            return None
        # Extract the part after 'req_'
        if 'req_' in run_id:
            # Split by 'req_' and get the part after it
            parts = run_id.split('req_')
            if len(parts) > 1:
                # Get the numeric part (may have additional text after)
                req_part = parts[1].split('/')[0].split('-')[0].split('_')[0]
                return req_part
    except Exception:
        return None
    return None


def handle_process_errors(process_name: Optional[str] = None):
    """Decorator for async process functions to capture exceptions, screenshot and send email.

    The wrapped function is expected to accept a named parameter `logger` and `page` in args/kwargs.
    On exception it will:
      - try to save a screenshot to data/outputs/error_screenshots
      - include last log lines from the process logger
      - call send_error_email
      - re-raise the exception so callers can decide to stop or continue
    """
    def deco(func):
        if asyncio.iscoroutinefunction(func):
            async def wrapper(*args, **kwargs):
                ln = process_name or getattr(func, "__name__", "process")
                # try to retrieve page and logger from args/kwargs
                page = kwargs.get("page", None)
                logger = kwargs.get("logger", None)
                # also inspect positional args if not found
                if page is None or logger is None:
                    # try positional: common signature (page, df, ... , logger)
                    if len(args) >= 1 and page is None:
                        possible_page = args[0]
                        # crude check
                        if hasattr(possible_page, "screenshot"):
                            page = possible_page
                    if len(args) >= 4 and logger is None:
                        possible_logger = args[3]
                        if hasattr(possible_logger, "error"):
                            logger = possible_logger

                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Build error context
                    func_name = f"{func.__module__}.{func.__name__}"
                    err_msg = f"Unhandled exception in {ln} ({func_name}): {e}"
                    if logger:
                        logger.error(err_msg)
                    # screenshot (best-effort)
                    shot_path = None
                    try:
                        if page is not None:
                            dest = Path("data/outputs/error_screenshots")
                            dest.mkdir(parents=True, exist_ok=True)
                            shot_path = dest / f"{ln}_{func.__name__}_error.png"
                            # playwright page.screenshot is async
                            await page.screenshot(path=str(shot_path), full_page=True)
                            if logger:
                                logger.error(f"Saved error screenshot: {shot_path}")
                    except Exception as se:
                        if logger:
                            logger.error(f"Failed to capture screenshot for {ln}: {se}")

                    # extract log file tail
                    log_tail = ""
                    log_file = _extract_log_file_from_logger(logger) if logger else None
                    if log_file:
                        log_tail = _find_log_tail(log_file)

                    # prepare email
                    subj = f"Validation/Error in {ln} - {func.__name__}"
                    body = f"An unhandled exception occurred in process '{ln}'.\n\nException:\n{e}\n\nFunction: {func_name}\n\n"
                    if log_tail:
                        body += f"Recent log lines:\n{log_tail}\n\n"

                    # call async send (best-effort). If this is a ValidationError, it's
                    # likely already handled by the validation checker (which sends an email),
                    # so avoid duplicate notifications here.
                    try:
                        if not isinstance(e, ValidationError):
                            # Try to extract request_id from kwargs if available
                            request_id = kwargs.get('request_id') if kwargs else None
                            await send_error_email(subj, body, screenshot_path=shot_path, log_files=None, logger=logger, request_id=request_id)
                            if logger:
                                logger.error("Dispatched process-level error email.")
                        else:
                            if logger:
                                logger.debug("ValidationError raised; skipping duplicate process-level email (already sent by validator).")
                    except Exception as me:
                        if logger:
                            logger.error(f"Failed to dispatch process-level error email: {me}")

                    # re-raise so caller may stop only this process
                    raise

            return wrapper
        else:
            # sync functions: provide basic wrapper
            def wrapper(*args, **kwargs):
                ln = process_name or getattr(func, "__name__", "process")
                logger = kwargs.get("logger")
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if logger:
                        logger.error(f"Unhandled exception in {ln} -> see logs/screenshot")
                    raise
            return wrapper
    return deco


def _build_lead_success_email_body(df, lead_ref_no: str, optout_data: Optional[Dict[str, Any]] = None) -> str:
    """Build professional HTML email body for lead creation success."""
    import pandas as pd
    row = df.iloc[0]
    
    # Helper to safely get values
    def get(key, default="N/A"):
        val = row.get(key, default)
        return val if pd.notna(val) and str(val).strip() else default
    
    # Determine header background color based on opt-out status
    header_bg_color = "#dc3545" if optout_data else "#0066cc"  # Red for opt-out, blue for normal
    header_text = "Lead Created Successfully - OPT-OUT REQUEST ⚠️" if optout_data else "Lead Created Successfully ✓"
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: {header_bg_color}; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
            .section {{ margin-bottom: 20px; }}
            .section-title {{ font-weight: bold; color: #0066cc; margin-bottom: 10px; font-size: 16px; border-bottom: 2px solid #0066cc; padding-bottom: 5px; }}
            .info-row {{ margin: 8px 0; }}
            .label {{ font-weight: bold; color: #555; display: inline-block; width: 180px; }}
            .value {{ color: #333; }}
            .ref-number {{ font-size: 20px; color: #28a745; font-weight: bold; text-align: center; padding: 15px; background-color: #e8f5e9; border-radius: 5px; margin: 20px 0; }}
            .optout-section {{ background-color: #f8d7da; border: 2px solid #dc3545; border-radius: 5px; padding: 15px; margin: 20px 0; }}
            .optout-title {{ font-weight: bold; color: #dc3545; margin-bottom: 10px; font-size: 18px; text-align: center; }}
            .footer {{ text-align: center; color: #777; font-size: 12px; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>{header_text}</h2>
            </div>
            <div class="content">
                <div class="ref-number">
                    Lead Reference Number: {lead_ref_no}
                </div>
                
                <div class="section">
                    <div class="section-title">Client Information</div>
                    <div class="info-row"><span class="label">Name:</span> <span class="value">{get('FirstName')} {get('LastName')}</span></div>
                    <div class="info-row"><span class="label">Email:</span> <span class="value">{get('Email_CRM')}</span></div>
                    <div class="info-row"><span class="label">Mobile:</span> <span class="value">{get('Mobile_CRM')}</span></div>
                    <div class="info-row"><span class="label">Emirates ID:</span> <span class="value">{get('EmiratesID')}</span></div>
                    <div class="info-row"><span class="label">Nationality:</span> <span class="value">{get('Nationality')}</span></div>
                </div>
                
                <div class="section">
                    <div class="section-title">Client Status</div>"""
    
    # Add client status information
    client_status = get('_client_status', 'new')
    if client_status == 'new':
        html += """
                    <div class="info-row"><span class="label">Status:</span> <span class="value" style="color: #28a745; font-weight: bold;">New Customer Created</span></div>"""
    else:
        html += """
                    <div class="info-row"><span class="label">Status:</span> <span class="value" style="color: #ffc107; font-weight: bold;">Existing Customer Selected</span></div>"""
        matched_by = get('_client_matched_by', 'N/A')
        matched_value = get('_client_matched_value', 'N/A')
        html += f"""
                    <div class="info-row"><span class="label">Matched By:</span> <span class="value">{matched_by}</span></div>
                    <div class="info-row"><span class="label">Matched Value:</span> <span class="value">{matched_value}</span></div>"""
    
    html += f"""
                </div>
                
                <div class="section">
                    <div class="section-title">Lead Details</div>
                    <div class="info-row"><span class="label">Business Type:</span> <span class="value">{get('BusinessType')}</span></div>
                    <div class="info-row"><span class="label">Class:</span> <span class="value">{get('Class')}</span></div>
                    <div class="info-row"><span class="label">Policy Type:</span> <span class="value">{get('PolicyTypeCRM')}</span></div>
                    <div class="info-row"><span class="label">Insurance Company:</span> <span class="value">{get('InsuranceCompany')}</span></div>
                    <div class="info-row"><span class="label">Classification:</span> <span class="value">{get('Classification')}</span></div>
                    <div class="info-row"><span class="label">Source:</span> <span class="value">{get('Source')}</span></div>
                </div>"""
    
    # Add opt-out section if applicable
    if optout_data:
        # Check if opt-out details are already in the email (from Client Information section)
        existing_email = get('Email_CRM')
        existing_mobile = get('Mobile_CRM')
        optout_email = optout_data.get('CustomerEmail', 'N/A')
        optout_mobile = optout_data.get('CustomerMobile', 'N/A')
        
        html += f"""
                
                <div class="optout-section">
                    <div class="optout-title">⚠️ OPT-OUT REQUEST DETAILS ⚠️</div>
                    <div class="info-row"><span class="label">OptOut ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('OptOutId', 'N/A')}</span></div>
                    <div class="info-row"><span class="label">Submission ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('SubmissionId', 'N/A')}</span></div>
                    <div class="info-row"><span class="label">Request ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('RequestId', 'N/A')}</span></div>"""
        
        # Only add email if it's different from what's already shown or if not shown
        if optout_email and (not existing_email or existing_email == 'N/A' or existing_email != optout_email):
            html += f"""
                    <div class="info-row"><span class="label">Customer Email:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_email}</span></div>"""
        
        # Only add mobile if it's different from what's already shown or if not shown
        if optout_mobile and (not existing_mobile or existing_mobile == 'N/A' or existing_mobile != optout_mobile):
            html += f"""
                    <div class="info-row"><span class="label">Customer Mobile:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_mobile}</span></div>"""
        
        html += """
                    <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #dc3545; font-size: 13px; color: #721c24;">
                        <strong>Important:</strong> This is an opt-out request. The customer has requested to be removed from communications.
                    </div>
                </div>"""
    
    html += """
                
                <div class="footer">
                    <p>This is an automated notification. Your lead has been successfully created in the CRM system.</p>
                    <p>For any questions, please contact your administrator.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def _build_prospect_success_email_body(df, prospect_ref_no: str, optout_data: Optional[Dict[str, Any]] = None) -> str:
    """Build professional HTML email body for prospect creation success."""
    import pandas as pd
    row = df.iloc[0]
    
    # Helper to safely get values
    def get(key, default="N/A"):
        val = row.get(key, default)
        return val if pd.notna(val) and str(val).strip() else default
    
    # Determine header background color based on opt-out status
    header_bg_color = "#dc3545" if optout_data else "#0066cc"  # Red for opt-out, blue for normal
    header_text = "Prospect Created Successfully - OPT-OUT REQUEST ⚠️" if optout_data else "Prospect Created Successfully ✓"
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: {header_bg_color}; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
            .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
            .section {{ margin-bottom: 20px; }}
            .section-title {{ font-weight: bold; color: #0066cc; margin-bottom: 10px; font-size: 16px; border-bottom: 2px solid #0066cc; padding-bottom: 5px; }}
            .info-row {{ margin: 8px 0; }}
            .label {{ font-weight: bold; color: #555; display: inline-block; width: 180px; }}
            .value {{ color: #333; }}
            .ref-number {{ font-size: 20px; color: #28a745; font-weight: bold; text-align: center; padding: 15px; background-color: #e8f5e9; border-radius: 5px; margin: 20px 0; }}
            .optout-section {{ background-color: #f8d7da; border: 2px solid #dc3545; border-radius: 5px; padding: 15px; margin: 20px 0; }}
            .optout-title {{ font-weight: bold; color: #dc3545; margin-bottom: 10px; font-size: 18px; text-align: center; }}
            .footer {{ text-align: center; color: #777; font-size: 12px; margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>{header_text}</h2>
            </div>
            <div class="content">
                <div class="ref-number">
                    Prospect Reference Number: {prospect_ref_no}
                </div>
                
                <div class="section">
                    <div class="section-title">Client Information</div>
                    <div class="info-row"><span class="label">Name:</span> <span class="value">{get('FirstName')} {get('LastName')}</span></div>
                    <div class="info-row"><span class="label">Email:</span> <span class="value">{get('Email_CRM')}</span></div>
                    <div class="info-row"><span class="label">Mobile:</span> <span class="value">{get('Mobile_CRM')}</span></div>
                    <div class="info-row"><span class="label">Emirates ID:</span> <span class="value">{get('EmiratesID')}</span></div>
                    <div class="info-row"><span class="label">Nationality:</span> <span class="value">{get('Nationality')}</span></div>
                </div>
                
                <div class="section">
                    <div class="section-title">Client Status</div>"""
    
    # Add client status information
    client_status = get('_client_status', 'new')
    if client_status == 'new':
        html += """
                    <div class="info-row"><span class="label">Status:</span> <span class="value" style="color: #28a745; font-weight: bold;">New Customer Created</span></div>"""
    else:
        html += """
                    <div class="info-row"><span class="label">Status:</span> <span class="value" style="color: #ffc107; font-weight: bold;">Existing Customer Selected</span></div>"""
        matched_by = get('_client_matched_by', 'N/A')
        matched_value = get('_client_matched_value', 'N/A')
        html += f"""
                    <div class="info-row"><span class="label">Matched By:</span> <span class="value">{matched_by}</span></div>
                    <div class="info-row"><span class="label">Matched Value:</span> <span class="value">{matched_value}</span></div>"""
    
    html += f"""
                </div>
                
                <div class="section">
                    <div class="section-title">Prospect Details</div>
                    <div class="info-row"><span class="label">Business Type:</span> <span class="value">{get('BusinessType')}</span></div>
                    <div class="info-row"><span class="label">Class:</span> <span class="value">{get('Class')}</span></div>
                    <div class="info-row"><span class="label">Policy Type:</span> <span class="value">{get('PolicyTypeCRM')}</span></div>
                    <div class="info-row"><span class="label">Classification:</span> <span class="value">{get('Classification')}</span></div>
                    <div class="info-row"><span class="label">Source:</span> <span class="value">{get('Source')}</span></div>
                    <div class="info-row"><span class="label">Location:</span> <span class="value">{get('LocationRegion')}</span></div>
                </div>
                
                <div class="section">
                    <div class="section-title">Vehicle Information</div>
                    <div class="info-row"><span class="label">Make:</span> <span class="value">{get('Make')}</span></div>
                    <div class="info-row"><span class="label">Model:</span> <span class="value">{get('Model')}</span></div>
                    <div class="info-row"><span class="label">Year:</span> <span class="value">{get('YearOfManufacture')}</span></div>
                    <div class="info-row"><span class="label">Chassis Number:</span> <span class="value">{get('ChassisNumber')}</span></div>
                </div>"""

    # Add fuzzy matching section if applicable  
    fuzzy_matches = get('vehicle_fuzzy_matches', '')
    if fuzzy_matches and fuzzy_matches.strip():
        html += f"""
                
                <div class="section" style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 5px; padding: 15px;">
                    <div class="section-title" style="color: #856404;">🔍 Data Matching Information</div>
                    <div class="info-row">
                        <span class="label">Automatic Corrections:</span> 
                        <span class="value" style="font-style: italic; color: #856404;">{fuzzy_matches}</span>
                    </div>
                    <div style="font-size: 12px; color: #6c757d; margin-top: 8px; padding-top: 8px; border-top: 1px solid #dee2e6;">
                        <strong>Note:</strong> Minor typos in vehicle make/model were automatically corrected using intelligent matching. 
                        The percentage shows the similarity confidence of the automatic correction.
                    </div>
                </div>"""
    
    # Add opt-out section if applicable
    if optout_data:
        # Check if opt-out details are already in the email (from Client Information section)
        existing_email = get('Email_CRM')
        existing_mobile = get('Mobile_CRM')
        optout_email = optout_data.get('CustomerEmail', 'N/A')
        optout_mobile = optout_data.get('CustomerMobile', 'N/A')
        
        html += f"""
                
                <div class="optout-section">
                    <div class="optout-title">⚠️ OPT-OUT REQUEST DETAILS ⚠️</div>
                    <div class="info-row"><span class="label">OptOut ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('OptOutId', 'N/A')}</span></div>
                    <div class="info-row"><span class="label">Submission ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('SubmissionId', 'N/A')}</span></div>
                    <div class="info-row"><span class="label">Request ID:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_data.get('RequestId', 'N/A')}</span></div>"""
        
        # Only add email if it's different from what's already shown or if not shown
        if optout_email and (not existing_email or existing_email == 'N/A' or existing_email != optout_email):
            html += f"""
                    <div class="info-row"><span class="label">Customer Email:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_email}</span></div>"""
        
        # Only add mobile if it's different from what's already shown or if not shown
        if optout_mobile and (not existing_mobile or existing_mobile == 'N/A' or existing_mobile != optout_mobile):
            html += f"""
                    <div class="info-row"><span class="label">Customer Mobile:</span> <span class="value" style="color: #dc3545; font-weight: bold;">{optout_mobile}</span></div>"""
        
        html += """
                    <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #dc3545; font-size: 13px; color: #721c24;">
                        <strong>Important:</strong> This is an opt-out request. The customer has requested to be removed from communications.
                    </div>
                </div>"""

    html += """
                <div class="footer">
                    <p>This is an automated notification. Your prospect has been successfully created in the CRM system.</p>
                    <p>For any questions, please contact your administrator.</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return html


async def send_success_email(
    process_type: str,
    df,
    ref_no: str,
    request_id: str,
    *,
    optout_data: Optional[Dict[str, Any]] = None,
    config_path: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Send a success notification email for lead or prospect creation.
    
    Args:
        process_type: Either "lead" or "prospect"
        df: DataFrame containing the record data
        ref_no: The reference number generated (lead_refr_no or crm_ref_no)
        request_id: The request ID for identification
        optout_data: Optional dict with opt-out details if this is an opt-out request
        config_path: Optional path to config.ini
        logger: Optional logger for status messages
    """
    cfg = _read_ini(config_path)
    if not cfg.get("send_emails"):
        if logger:
            logger.info("Email notifications are disabled in config.ini; skipping success email.")
        return
    
    # Build the appropriate email body
    if process_type.lower() == "lead":
        body = _build_lead_success_email_body(df, ref_no, optout_data)
        subject_prefix = "OPT-OUT - " if optout_data else ""
        subject = f"{subject_prefix}Lead Created Successfully - Request ID: {request_id} - Ref: {ref_no}"
    elif process_type.lower() == "prospect":
        body = _build_prospect_success_email_body(df, ref_no, optout_data)
        subject_prefix = "OPT-OUT - " if optout_data else ""
        subject = f"{subject_prefix}Prospect Created Successfully - Request ID: {request_id} - Ref: {ref_no}"
    else:
        if logger:
            logger.error(f"Unknown process_type: {process_type}. Must be 'lead' or 'prospect'")
        return
    
    # Send the email using existing function with request_id to attach documents
    await send_error_email(
        subject=subject,
        body=body,
        config_path=config_path,
        logger=logger,
        request_id=request_id  # Pass request_id to enable document attachments
    )
