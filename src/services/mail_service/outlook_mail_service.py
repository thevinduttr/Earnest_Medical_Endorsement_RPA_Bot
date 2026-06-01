from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence
import base64
import logging

import requests

from src.utils.mail_config import MailConfig


class OutlookTokenManager:
    def __init__(self, client_id: str, tenant_id: str, cache_path: Path):
        import msal

        self.config = {
            "client_id": client_id,
            "tenant_id": tenant_id,
            "scope": ["https://graph.microsoft.com/Mail.Send"],
            "authority": f"https://login.microsoftonline.com/{tenant_id}",
        }
        self.cache_path = cache_path
        self.app = msal.PublicClientApplication(
            self.config["client_id"],
            authority=self.config["authority"],
            token_cache=msal.SerializableTokenCache(),
        )
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            with self.cache_path.open("r", encoding="utf-8") as file_handle:
                cache_data = file_handle.read()
                if cache_data:
                    self.app.token_cache.deserialize(cache_data)
        except FileNotFoundError:
            return
        except Exception as error:
            raise ValueError(f"Failed to load token cache from {self.cache_path}: {error}")

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = self.app.token_cache.serialize()
            with self.cache_path.open("w", encoding="utf-8") as file_handle:
                file_handle.write(cache_data)
        except Exception as error:
            raise ValueError(f"Failed to save token cache to {self.cache_path}: {error}")

    def get_token(self, force_refresh: bool = False) -> str:
        if not force_refresh:
            accounts = self.app.get_accounts()
            if accounts:
                result = self.app.acquire_token_silent(self.config["scope"], account=accounts[0])
                if result and "access_token" in result:
                    self._save_cache()
                    return result["access_token"]

        result = self.app.acquire_token_interactive(scopes=self.config["scope"])
        if "access_token" in result:
            self._save_cache()
            return result["access_token"]

        error = result.get("error", "Unknown error")
        error_desc = result.get("error_description", "No description")
        raise ValueError(f"Authentication failed: {error} - {error_desc}")


_token_manager: OutlookTokenManager | None = None


def get_token_manager(mail_config: MailConfig) -> OutlookTokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = OutlookTokenManager(
            mail_config.client_id,
            mail_config.tenant_id,
            mail_config.token_cache_path,
        )
    return _token_manager


def get_valid_access_token(mail_config: MailConfig, force_refresh: bool = False) -> str:
    return get_token_manager(mail_config).get_token(force_refresh=force_refresh)


def _attachment_payload(attachments: Sequence[Path] | None) -> list[dict]:
    payload: list[dict] = []
    for attachment in attachments or []:
        file_path = Path(attachment).resolve()
        if not file_path.exists():
            continue
        payload.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": file_path.name,
                "contentBytes": base64.b64encode(file_path.read_bytes()).decode(),
            }
        )
    return payload


def send_outlook_email(
    mail_config: MailConfig,
    *,
    subject: str,
    body: str,
    to: Optional[Sequence[str]] = None,
    cc: Optional[Sequence[str]] = None,
    bcc: Optional[Sequence[str]] = None,
    attachments: Optional[Sequence[Path]] = None,
    content_type: str = "HTML",
    logger: Optional[logging.Logger] = None,
) -> None:
    if not mail_config.send_emails:
        if logger:
            logger.info("Mail sending is disabled in config/mail.ini")
        return

    recipient_to = list(to or mail_config.recipients)
    recipient_cc = list(cc or mail_config.cc)
    recipient_bcc = list(bcc or mail_config.bcc)

    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": body,
            },
            "toRecipients": [{"emailAddress": {"address": address}} for address in recipient_to],
            "ccRecipients": [{"emailAddress": {"address": address}} for address in recipient_cc],
            "bccRecipients": [{"emailAddress": {"address": address}} for address in recipient_bcc],
            "attachments": _attachment_payload(attachments),
        },
        "saveToSentItems": True,
    }

    token = get_valid_access_token(mail_config)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers=headers, json=message, timeout=60)

    if response.status_code in (200, 202):
        if logger:
            logger.info("Email sent successfully")
        return

    if response.status_code == 401 and "InvalidAuthenticationToken" in response.text:
        token = get_valid_access_token(mail_config, force_refresh=True)
        headers["Authorization"] = f"Bearer {token}"
        response = requests.post("https://graph.microsoft.com/v1.0/me/sendMail", headers=headers, json=message, timeout=60)
        if response.status_code in (200, 202):
            if logger:
                logger.info("Email sent successfully after token refresh")
            return

    error = f"Failed to send mail. HTTP {response.status_code}: {response.text}"
    if logger:
        logger.error(error)
    raise RuntimeError(error)
