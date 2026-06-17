from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Optional, Sequence
import base64
import logging
import re
import time

import requests

from src.utils.mail_config import MailConfig


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
OTP_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class OutlookTokenManager:
    def __init__(self, client_id: str, tenant_id: str, cache_path: Path):
        import msal

        self.config = {
            "client_id": client_id,
            "tenant_id": tenant_id,
            "scope": [
                "https://graph.microsoft.com/Mail.Send",
                "https://graph.microsoft.com/Mail.Read",
            ],
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


def _graph_headers(mail_config: MailConfig, *, force_refresh: bool = False) -> dict[str, str]:
    token = get_valid_access_token(mail_config, force_refresh=force_refresh)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _graph_request(
    method: str,
    url: str,
    mail_config: MailConfig,
    *,
    logger: Optional[logging.Logger] = None,
    **kwargs,
) -> requests.Response:
    response = requests.request(
        method,
        url,
        headers=_graph_headers(mail_config),
        timeout=60,
        **kwargs,
    )
    if response.status_code == 401 and "InvalidAuthenticationToken" in response.text:
        response = requests.request(
            method,
            url,
            headers=_graph_headers(mail_config, force_refresh=True),
            timeout=60,
            **kwargs,
        )

    if response.status_code >= 400:
        error = f"Microsoft Graph request failed. HTTP {response.status_code}: {response.text}"
        if logger:
            logger.error(error)
        raise RuntimeError(error)
    return response


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(unescape(without_tags).split())


def extract_otp_from_message_text(*parts: str) -> str | None:
    text = " ".join(_strip_html(part) for part in parts if part)
    if not text:
        return None

    candidates = OTP_PATTERN.findall(text)
    if not candidates:
        return None

    preferred_keywords = ("code", "verify", "identity", "broker connect", "sign in")
    normalized = text.lower()
    for candidate in candidates:
        position = normalized.find(candidate)
        start = max(0, position - 80)
        end = min(len(normalized), position + len(candidate) + 80)
        nearby = normalized[start:end]
        if any(keyword in nearby for keyword in preferred_keywords):
            return candidate

    return candidates[0]


def _parse_graph_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    if since.tzinfo is None:
        return since.replace(tzinfo=timezone.utc)
    return since.astimezone(timezone.utc)


def _list_folder_page(
    mail_config: MailConfig,
    url: str,
    *,
    logger: Optional[logging.Logger] = None,
) -> dict:
    response = _graph_request("GET", url, mail_config, logger=logger)
    return response.json()


def _find_mail_folder_id(
    mail_config: MailConfig,
    folder_name: str,
    *,
    logger: Optional[logging.Logger] = None,
) -> str:
    target_name = str(folder_name or "").strip().lower()
    if not target_name:
        raise ValueError("OTP folder name is empty")

    queue = [f"{GRAPH_BASE_URL}/me/mailFolders?$top=100&$select=id,displayName"]
    while queue:
        page_url = queue.pop(0)
        data = _list_folder_page(mail_config, page_url, logger=logger)
        for folder in data.get("value", []):
            folder_id = str(folder.get("id") or "")
            display_name = str(folder.get("displayName") or "")
            if display_name.strip().lower() == target_name and folder_id:
                return folder_id
            if folder_id:
                queue.append(
                    f"{GRAPH_BASE_URL}/me/mailFolders/{folder_id}/childFolders"
                    "?$top=100&$select=id,displayName"
                )

        next_link = data.get("@odata.nextLink")
        if next_link:
            queue.append(str(next_link))

    raise RuntimeError(f"Outlook folder '{folder_name}' was not found")


def _get_latest_folder_messages(
    mail_config: MailConfig,
    folder_id: str,
    *,
    logger: Optional[logging.Logger] = None,
) -> list[dict]:
    url = _build_latest_unread_messages_url(folder_id)
    response = _graph_request("GET", url, mail_config, logger=logger)
    data = response.json()
    return list(data.get("value", []))


def _build_latest_unread_messages_url(folder_id: str) -> str:
    return (
        f"{GRAPH_BASE_URL}/me/mailFolders/{folder_id}/messages"
        "?$top=10"
        "&$filter=isRead%20eq%20false"
        "&$orderby=receivedDateTime%20desc"
        "&$select=subject,bodyPreview,body,receivedDateTime,isRead"
    )


def find_latest_nas_otp(
    mail_config: MailConfig,
    *,
    folder_name: str | None = None,
    received_after: datetime | None = None,
    timeout_seconds: int | None = None,
    poll_interval_seconds: int | None = None,
    logger: Optional[logging.Logger] = None,
) -> str:
    target_folder = folder_name or mail_config.otp_folder
    timeout_value = int(timeout_seconds or mail_config.otp_poll_timeout_seconds)
    interval_value = int(poll_interval_seconds or mail_config.otp_poll_interval_seconds)
    received_after_utc = _normalize_since(received_after)

    folder_id = _find_mail_folder_id(mail_config, target_folder, logger=logger)
    deadline = time.monotonic() + max(1, timeout_value)
    last_seen_received_at = None

    while time.monotonic() < deadline:
        messages = _get_latest_folder_messages(mail_config, folder_id, logger=logger)
        for message in messages:
            if bool(message.get("isRead")):
                continue

            received_at = _parse_graph_datetime(str(message.get("receivedDateTime") or ""))
            if received_at:
                last_seen_received_at = received_at.isoformat()
            if received_after_utc:
                if not received_at or received_at < received_after_utc:
                    continue

            body = message.get("body") or {}
            otp = extract_otp_from_message_text(
                str(message.get("subject") or ""),
                str(message.get("bodyPreview") or ""),
                str(body.get("content") or ""),
            )
            if otp:
                if logger:
                    logger.info("NAS OTP found in Outlook folder '%s'", target_folder)
                return otp

        time.sleep(max(1, interval_value))

    detail = f" Last seen receivedDateTime={last_seen_received_at}." if last_seen_received_at else ""
    raise RuntimeError(
        f"No fresh NAS OTP email found in Outlook folder '{target_folder}' "
        f"within {timeout_value} seconds.{detail}"
    )


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

    headers = _graph_headers(mail_config)
    response = requests.post(f"{GRAPH_BASE_URL}/me/sendMail", headers=headers, json=message, timeout=60)

    if response.status_code in (200, 202):
        if logger:
            logger.info("Email sent successfully")
        return

    if response.status_code == 401 and "InvalidAuthenticationToken" in response.text:
        headers = _graph_headers(mail_config, force_refresh=True)
        response = requests.post(f"{GRAPH_BASE_URL}/me/sendMail", headers=headers, json=message, timeout=60)
        if response.status_code in (200, 202):
            if logger:
                logger.info("Email sent successfully after token refresh")
            return

    error = f"Failed to send mail. HTTP {response.status_code}: {response.text}"
    if logger:
        logger.error(error)
    raise RuntimeError(error)
