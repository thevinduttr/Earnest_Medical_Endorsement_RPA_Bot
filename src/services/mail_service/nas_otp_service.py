from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import logging
import os

import yaml

from src.services.mail_service.gmail_otp_service import find_latest_gmail_nas_otp
from src.services.mail_service.outlook_mail_service import find_latest_nas_otp as find_latest_outlook_nas_otp
from src.utils.mail_config import MailConfig


DEFAULT_BASE_CONFIG_PATH = Path("config/base.yml")


@dataclass(frozen=True)
class NasOtpProviderConfig:
    use_gmail: bool = False
    gmail_credentials_path: Path = Path("config/gmail_credentials.json")
    gmail_token_path: Path = Path("config/gmail_token.json")
    gmail_folder_name: str = "INBOX"


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_external_path(raw_value: Any, fallback: str) -> Path:
    value = str(raw_value or fallback).strip() or fallback
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def load_nas_otp_provider_config(
    config_path: Path | str = DEFAULT_BASE_CONFIG_PATH,
) -> NasOtpProviderConfig:
    path = Path(config_path)
    if not path.exists():
        base_config = {}
    else:
        with path.open("r", encoding="utf-8") as stream:
            base_config = yaml.safe_load(stream) or {}

    section = base_config.get("nas_otp") or {}
    if not isinstance(section, dict):
        section = {}

    gmail_section = section.get("gmail") or {}
    if not isinstance(gmail_section, dict):
        gmail_section = {}

    return NasOtpProviderConfig(
        use_gmail=_as_bool(section.get("use_gmail"), default=False),
        gmail_credentials_path=_resolve_external_path(
            gmail_section.get("credentials_path"),
            "config/gmail_credentials.json",
        ),
        gmail_token_path=_resolve_external_path(
            gmail_section.get("token_path"),
            "config/gmail_token.json",
        ),
        gmail_folder_name=str(gmail_section.get("folder_name") or "INBOX").strip() or "INBOX",
    )


def find_latest_nas_otp(
    mail_config: MailConfig,
    *,
    folder_name: str | None = None,
    received_after: datetime | None = None,
    timeout_seconds: int | None = None,
    poll_interval_seconds: int | None = None,
    logger: Optional[logging.Logger] = None,
    provider_config: NasOtpProviderConfig | None = None,
) -> str:
    config = provider_config or load_nas_otp_provider_config()
    timeout_value = int(timeout_seconds or mail_config.otp_poll_timeout_seconds)
    interval_value = int(poll_interval_seconds or mail_config.otp_poll_interval_seconds)

    if config.use_gmail:
        if logger:
            logger.info("NAS OTP provider selected: Gmail")
        return find_latest_gmail_nas_otp(
            credentials_path=config.gmail_credentials_path,
            token_path=config.gmail_token_path,
            folder_name=folder_name or config.gmail_folder_name,
            received_after=received_after,
            timeout_seconds=timeout_value,
            poll_interval_seconds=interval_value,
            logger=logger,
        )

    if logger:
        logger.info("NAS OTP provider selected: Outlook")
    return find_latest_outlook_nas_otp(
        mail_config,
        folder_name=folder_name,
        received_after=received_after,
        timeout_seconds=timeout_value,
        poll_interval_seconds=interval_value,
        logger=logger,
    )
