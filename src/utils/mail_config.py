from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_MAIL_CONFIG_PATH = Path("config/mail.ini")


def _split_addresses(raw_value: str | None) -> tuple[str, ...]:
    return tuple(address.strip() for address in str(raw_value or "").split(",") if address.strip())


@dataclass(frozen=True)
class MailConfig:
    client_id: str
    tenant_id: str
    token_cache_path: Path
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    send_emails: bool = True
    otp_folder: str = "NAS OTP"
    otp_poll_timeout_seconds: int = 120
    otp_poll_interval_seconds: int = 5

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "MailConfig":
        path = Path(config_path or DEFAULT_MAIL_CONFIG_PATH)
        parser = ConfigParser()
        if path.exists():
            parser.read(path, encoding="utf-8")

        section = parser["EMAIL"] if parser.has_section("EMAIL") else {}
        client_id = str(section.get("client_id", "")).strip() if section else ""
        tenant_id = str(section.get("tenant_id", "")).strip() if section else ""
        token_cache = str(section.get("token_cache_path", "config/outlook_token_cache.json")).strip() if section else "config/outlook_token_cache.json"

        otp_section = parser["OTP"] if parser.has_section("OTP") else {}
        otp_folder = str(otp_section.get("folder_name", "NAS OTP")).strip() if otp_section else "NAS OTP"
        otp_poll_timeout = str(otp_section.get("poll_timeout_seconds", "120")).strip() if otp_section else "120"
        otp_poll_interval = str(otp_section.get("poll_interval_seconds", "5")).strip() if otp_section else "5"

        client_id = client_id or os.getenv("OUTLOOK_CLIENT_ID", "").strip()
        tenant_id = tenant_id or os.getenv("OUTLOOK_TENANT_ID", "").strip()
        token_cache = token_cache or os.getenv("OUTLOOK_TOKEN_CACHE", "config/outlook_token_cache.json").strip()
        otp_folder = os.getenv("NAS_OTP_FOLDER", "").strip() or otp_folder or "NAS OTP"

        try:
            otp_poll_timeout_seconds = int(os.getenv("NAS_OTP_POLL_TIMEOUT_SECONDS", "").strip() or otp_poll_timeout)
        except ValueError:
            otp_poll_timeout_seconds = 120

        try:
            otp_poll_interval_seconds = int(os.getenv("NAS_OTP_POLL_INTERVAL_SECONDS", "").strip() or otp_poll_interval)
        except ValueError:
            otp_poll_interval_seconds = 5

        return cls(
            client_id=client_id,
            tenant_id=tenant_id,
            token_cache_path=Path(token_cache),
            recipients=_split_addresses(section.get("recipient_emails") if section else None),
            cc=_split_addresses(section.get("cc_emails") if section else None),
            bcc=_split_addresses(section.get("bcc_emails") if section else None),
            send_emails=str(section.get("send_emails", "true") if section else "true").strip().lower() in {"1", "true", "yes", "on"},
            otp_folder=otp_folder,
            otp_poll_timeout_seconds=max(1, otp_poll_timeout_seconds),
            otp_poll_interval_seconds=max(1, otp_poll_interval_seconds),
        )
