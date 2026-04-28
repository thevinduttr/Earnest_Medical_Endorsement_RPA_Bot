from __future__ import annotations
import json
import os
import time
import base64
from pathlib import Path
from typing import Dict, Optional, Sequence
import requests
import logging
from .env_config import resolve_env_vars

class OutlookTokenManager:
    def __init__(self, client_id: str, tenant_id: str, cache_path: str):
        import msal
        self.config = {
            "client_id": client_id,
            "tenant_id": tenant_id,
            "scope": ["https://graph.microsoft.com/Mail.Send"],
            "authority": f"https://login.microsoftonline.com/{tenant_id}"
        }
        self.cache_path = cache_path
        self.app = msal.PublicClientApplication(
            self.config["client_id"],
            authority=self.config["authority"],
            token_cache=msal.SerializableTokenCache()
        )
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load token cache from file"""
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                cache_data = f.read()
                if cache_data:
                    self.app.token_cache.deserialize(cache_data)
        except FileNotFoundError:
            pass  # No cache exists yet
        except Exception as e:
            raise ValueError(f"Failed to load token cache from {self.cache_path}: {e}")
    
    def _save_cache(self) -> None:
        """Save token cache to file"""
        try:
            cache_data = self.app.token_cache.serialize()
            with open(self.cache_path, "w", encoding="utf-8") as f:
                f.write(cache_data)
        except Exception as e:
            raise ValueError(f"Failed to save token cache to {self.cache_path}: {e}")
    
    def get_token(self, force_refresh: bool = False) -> str:
        """Get a valid access token, refreshing if necessary"""
        if not force_refresh:
            # Try silent token acquisition first
            accounts = self.app.get_accounts()
            if accounts:
                result = self.app.acquire_token_silent(
                    self.config["scope"],
                    account=accounts[0]
                )
                if result and "access_token" in result:
                    self._save_cache()
                    return result["access_token"]

        # If we get here, we need to do interactive auth
        result = self.app.acquire_token_interactive(scopes=self.config["scope"])
        if "access_token" in result:
            self._save_cache()
            return result["access_token"]
        else:
            error = result.get("error", "Unknown error")
            error_desc = result.get("error_description", "No description")
            raise ValueError(f"Authentication failed: {error} - {error_desc}")

# Global token manager instance
_token_manager = None

def get_token_manager() -> OutlookTokenManager:
    """Get or create the token manager instance"""
    global _token_manager
    if _token_manager is None:
        client_id = os.getenv("OUTLOOK_CLIENT_ID", "1ac522e4-707b-4dc8-b7c7-ba88bc4d0e6f")
        tenant_id = os.getenv("OUTLOOK_TENANT_ID", "a3dfb5e4-789f-427f-ada4-9481ec87a98e")
        cache_path = os.getenv("OUTLOOK_TOKEN_CACHE", "config/outlook_token_cache.json")
        _token_manager = OutlookTokenManager(client_id, tenant_id, cache_path)
    return _token_manager

def get_valid_access_token(force_refresh: bool = False) -> str:
    """Get a valid access token using the token manager with automatic refresh support.
    
    Args:
        force_refresh: If True, skip cache and force token refresh
        
    Returns:
        A valid access token string
        
    Raises:
        ValueError: If token acquisition fails
    """
    return get_token_manager().get_token(force_refresh=force_refresh)

async def send_email_async(
    email_cfg: Dict,
    *,
    subject: str,
    body: str,
    to: Optional[Sequence[str]] = None,
    cc: Optional[Sequence[str]] = None,
    bcc: Optional[Sequence[str]] = None,
    attachments: Optional[Sequence[Path]] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Send email using Microsoft Graph API with automatic token refresh.

    This function will:
    1. Get a valid access token, refreshing if needed
    2. Send the email using Graph API
    3. If the token is expired, refresh it and retry automatically
    4. Handle up to 2 retries for token expiration

    Required environment variables:
    - OUTLOOK_CLIENT_ID: Azure AD app client ID
    - OUTLOOK_TENANT_ID: Azure AD tenant ID
    - OUTLOOK_TOKEN_CACHE: Path to token cache file (default: config/outlook_token_cache.json)

    Args:
        email_cfg: Email configuration dictionary
        subject: Email subject line
        body: Email body text
        to: List of recipient email addresses
        cc: List of CC recipient email addresses
        bcc: List of BCC recipient email addresses
        attachments: List of file paths to attach
        logger: Optional logger for status/debug messages

    Raises:
        ValueError: If token acquisition fails
        RuntimeError: If email sending fails after retries
    """
    
    # Get token with auto-refresh
    try:
        token = get_valid_access_token()
    except ValueError as e:
        # Token acquisition failed
        if logger:
            logger.error(f"Failed to get access token: {e}")
        raise
        
    url = "https://graph.microsoft.com/v1.0/me/sendMail"
    
    # Get recipients from config if not overridden
    if not to:
        to = email_cfg.get("recipients", {}).get("to", [])
    if not cc:
        cc = email_cfg.get("recipients", {}).get("cc", [])
    if not bcc:
        bcc = email_cfg.get("recipients", {}).get("bcc", [])
        
    # Build recipients lists
    to_list = [{"emailAddress": {"address": addr}} for addr in (to or [])]
    cc_list = [{"emailAddress": {"address": addr}} for addr in (cc or [])]
    bcc_list = [{"emailAddress": {"address": addr}} for addr in (bcc or [])]
    
    # Prepare attachments if any
    attachment_list = []
    if attachments:
        for att in attachments:
            p = Path(att).resolve()
            if not p.exists():
                continue
            try:
                data = p.read_bytes()
                b64_data = base64.b64encode(data).decode()
                attachment_list.append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": p.name,
                    "contentBytes": b64_data
                })
            except Exception as e:
                if logger:
                    logger.warning(f"Failed to attach file {p}: {e}")

    content_type = "Text"
    if "<html>" in body or "<table" in body or "<h3>" in body or "<div>" in body:
        content_type = "HTML"
    
    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": content_type, 
                "content": body
            },
            "toRecipients": to_list,
            "ccRecipients": cc_list,
            "bccRecipients": bcc_list,
            "attachments": attachment_list
        },
        "saveToSentItems": True
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json" 
    }
    
    if logger:
        to_str = ", ".join(to or [])
        cc_str = ", ".join(cc or [])
        bcc_str = ", ".join(bcc or [])
        logger.info(f"Sending email: Subject='{subject}' To='{to_str}' CC='{cc_str}' BCC='{bcc_str}'")
        if attachments:
            logger.info(f"With attachments: {[p.name for p in attachments if p.exists()]}")
    
    # Try sending with auto-retry on token expiration
    max_retries = 2
    for attempt in range(max_retries):
        resp = requests.post(url, headers=headers, json=message)
        
        if resp.status_code in (200, 202):
            if logger:
                logger.info(f"Email sent successfully to {to_str}")
            return
            
        # Check if token expired
        if resp.status_code == 401 and "InvalidAuthenticationToken" in resp.text:
            if attempt < max_retries - 1:  # Don't refresh on last attempt
                if logger:
                    logger.warning("Token expired, refreshing and retrying...")
                try:
                    # Force token refresh and update headers
                    token = get_valid_access_token(force_refresh=True)
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                except Exception as e:
                    if logger:
                        logger.error(f"Token refresh failed: {e}")
                    break

        # Non-token error or max retries reached
        error = f"Failed to send mail. HTTP {resp.status_code}: {resp.text}"
        if logger:
            logger.error(error)
        raise RuntimeError(error)

async def send_error_email_with_screenshots(
    email_cfg: Dict,
    *,
    subject_prefix: str,
    error_message: str,
    screenshots: Sequence[Path],
    extra_to: Optional[Sequence[str]] = None,
    extra_cc: Optional[Sequence[str]] = None,
    extra_bcc: Optional[Sequence[str]] = None,
    request_id: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Helper to send error notification emails with screenshots and submitted documents
    
    Args:
        email_cfg: Email configuration
        subject_prefix: Prefix for email subject
        error_message: Error message to include in body
        screenshots: List of screenshot paths to attach
        extra_to: Additional TO recipients
        extra_cc: Additional CC recipients
        extra_bcc: Additional BCC recipients
        request_id: Request ID to include submitted documents
        logger: Optional logger for status messages
    """
    subject = f"{subject_prefix} - Error Notification"
    body = f"""An error occurred during process execution.

Details:
{error_message}

Attached screenshots (if any) show the application state at error time.
"""
    
    # Combine screenshots with submitted documents if request_id provided
    all_attachments = list(screenshots) if screenshots else []
    
    if request_id:
        try:
            from pathlib import Path
            from src.utils.attachment_manager import get_downloaded_attachments
            
            if logger:
                logger.info(f"Including submitted documents for request {request_id} in error email")
            
            # Get all downloaded attachments for this request
            document_files = get_downloaded_attachments(request_id, download_path="data/attachments")
            
            if document_files:
                if logger:
                    logger.info(f"Found {len(document_files)} submitted document(s) to attach")
                
                # Add documents to attachments list
                for doc_path_str in document_files:
                    doc_path = Path(doc_path_str)
                    if doc_path.exists():
                        all_attachments.append(doc_path)
                        if logger:
                            logger.info(f"Attached submitted document: {doc_path.name}")
            else:
                if logger:
                    logger.info(f"No submitted documents found for request {request_id}")
        except Exception as e:
            if logger:
                logger.error(f"Failed to attach submitted documents: {e}")
    
    await send_email_async(
        email_cfg,
        subject=subject,
        body=body,
        to=extra_to,
        cc=extra_cc,
        bcc=extra_bcc,
        attachments=all_attachments,
        logger=logger,
    )
