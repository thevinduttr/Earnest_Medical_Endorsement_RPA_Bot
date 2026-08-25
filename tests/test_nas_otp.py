from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.services.mail_service.outlook_mail_service import (
    _build_latest_unread_messages_url,
    extract_otp_from_message_text,
)
from src.utils.mail_config import MailConfig


class NasOtpExtractionTests(unittest.TestCase):
    def test_extracts_otp_from_email_body(self) -> None:
        body = """
        <html>
          <body>
            <h2>Hi there!</h2>
            <p>Use the code below to verify your identity and sign in to your Broker Connect account</p>
            <h1>766209</h1>
          </body>
        </html>
        """

        self.assertEqual("766209", extract_otp_from_message_text(body))

    def test_ignores_non_six_digit_numbers(self) -> None:
        body = "Use the code below to verify your identity. Reference 12345 and ticket 1234567."

        self.assertIsNone(extract_otp_from_message_text(body))

    def test_returns_none_when_no_otp_exists(self) -> None:
        body = "Please verify your identity, but this message has no numeric code."

        self.assertIsNone(extract_otp_from_message_text(body))

    def test_latest_message_query_filters_unread_first(self) -> None:
        url = _build_latest_unread_messages_url("folder-id")

        self.assertIn("$filter=isRead%20eq%20false", url)
        self.assertIn("$orderby=receivedDateTime%20desc", url)
        self.assertIn("isRead", url)


class MailConfigOtpTests(unittest.TestCase):
    def test_otp_defaults_are_loaded_when_section_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mail.ini"
            config_path.write_text(
                """
[EMAIL]
client_id = client-id
tenant_id = tenant-id
token_cache_path = config/outlook_token_cache.json
recipient_emails = test@example.com
send_emails = true
""".strip(),
                encoding="utf-8",
            )

            config = MailConfig.load(config_path)

        self.assertEqual("NAS OTP", config.otp_folder)
        self.assertEqual(120, config.otp_poll_timeout_seconds)
        self.assertEqual(5, config.otp_poll_interval_seconds)

    def test_otp_section_overrides_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "mail.ini"
            config_path.write_text(
                """
[EMAIL]
client_id = client-id
tenant_id = tenant-id
token_cache_path = config/outlook_token_cache.json
recipient_emails = test@example.com
send_emails = true

[OTP]
folder_name = NAS OTP Custom
poll_timeout_seconds = 120
poll_interval_seconds = 3
""".strip(),
                encoding="utf-8",
            )

            config = MailConfig.load(config_path)

        self.assertEqual("NAS OTP Custom", config.otp_folder)
        self.assertEqual(120, config.otp_poll_timeout_seconds)
        self.assertEqual(3, config.otp_poll_interval_seconds)


if __name__ == "__main__":
    unittest.main()
