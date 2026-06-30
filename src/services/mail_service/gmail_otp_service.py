from __future__ import annotations

from base64 import urlsafe_b64decode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import logging
import time

from src.services.mail_service.outlook_mail_service import extract_otp_from_message_text


GMAIL_READONLY_SCOPE = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_SYSTEM_LABEL_ALIASES = {
    "inbox": "INBOX",
    "spam": "SPAM",
    "junk": "SPAM",
    "trash": "TRASH",
    "bin": "TRASH",
    "sent": "SENT",
    "draft": "DRAFT",
    "drafts": "DRAFT",
    "important": "IMPORTANT",
    "starred": "STARRED",
}


def _normalize_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    if since.tzinfo is None:
        return since.replace(tzinfo=timezone.utc)
    return since.astimezone(timezone.utc)


def _gmail_service(credentials_path: Path, token_path: Path) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), GMAIL_READONLY_SCOPE)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(f"Gmail credentials file not found: {credentials_path}")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_READONLY_SCOPE)
            credentials = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=credentials)


def _message_datetime(message: dict[str, Any]) -> datetime | None:
    internal_date = str(message.get("internalDate") or "").strip()
    if not internal_date:
        return None
    try:
        timestamp = int(internal_date) / 1000
    except ValueError:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _decode_body_data(value: str | None) -> str:
    if not value:
        return ""
    padded = value + "=" * (-len(value) % 4)
    try:
        return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _payload_text(payload: dict[str, Any]) -> str:
    body_text = _decode_body_data((payload.get("body") or {}).get("data"))
    parts_text = " ".join(_payload_text(part) for part in payload.get("parts") or [])
    return " ".join(part for part in (body_text, parts_text) if part)


def _headers_text(payload: dict[str, Any]) -> str:
    headers = payload.get("headers") or []
    interesting = {"subject", "from", "to"}
    return " ".join(
        str(header.get("value") or "")
        for header in headers
        if str(header.get("name") or "").strip().lower() in interesting
    )


def _normalize_gmail_label_name(label_name: str | None) -> str:
    label = str(label_name or "INBOX").strip() or "INBOX"
    normalized = label.lower().replace("[gmail]/", "").replace("[googlemail]/", "")
    return GMAIL_SYSTEM_LABEL_ALIASES.get(normalized, label)


def _list_unread_messages(service: Any, label_name: str) -> list[dict[str, Any]]:
    label = _normalize_gmail_label_name(label_name)
    response = (
        service.users()
        .messages()
        .list(userId="me", labelIds=[label], q="is:unread", maxResults=10)
        .execute()
    )
    return list(response.get("messages") or [])


def _get_message(service: Any, message_id: str) -> dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def find_latest_gmail_nas_otp(
    *,
    credentials_path: Path,
    token_path: Path,
    folder_name: str = "INBOX",
    received_after: datetime | None = None,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 5,
    logger: Optional[logging.Logger] = None,
) -> str:
    service = _gmail_service(credentials_path, token_path)
    target_folder = _normalize_gmail_label_name(folder_name)
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    interval_value = max(1, int(poll_interval_seconds))
    received_after_utc = _normalize_since(received_after)
    last_seen_received_at = None

    while time.monotonic() < deadline:
        for summary in _list_unread_messages(service, target_folder):
            message_id = str(summary.get("id") or "")
            if not message_id:
                continue

            message = _get_message(service, message_id)
            received_at = _message_datetime(message)
            if received_at:
                last_seen_received_at = received_at.isoformat()
            if received_after_utc and (not received_at or received_at < received_after_utc):
                continue

            payload = message.get("payload") or {}
            otp = extract_otp_from_message_text(
                _headers_text(payload),
                str(message.get("snippet") or ""),
                _payload_text(payload),
            )
            if otp:
                if logger:
                    logger.info("NAS OTP found in Gmail label '%s'", target_folder)
                return otp

        time.sleep(interval_value)

    detail = f" Last seen internalDate={last_seen_received_at}." if last_seen_received_at else ""
    raise RuntimeError(
        f"No fresh NAS OTP email found in Gmail label '{target_folder}' "
        f"within {int(timeout_seconds)} seconds.{detail}"
    )
