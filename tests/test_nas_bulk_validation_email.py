from __future__ import annotations

from pathlib import Path
import logging
import tempfile
import unittest
from unittest.mock import patch

from src.portals.nas.add_process.bulk_member.bulk_add_member import (
    NasBulkValidationDownloadError,
)
from src.portals.nas.nas_main import _send_nas_validation_error_email


class NasBulkValidationEmailTests(unittest.TestCase):
    def test_validation_exception_keeps_downloaded_file(self) -> None:
        path = Path("validation.xlsx")
        error = NasBulkValidationDownloadError("invalid upload", path)

        self.assertEqual(path, error.downloaded_file)
        self.assertEqual("invalid upload", str(error))

    def test_validation_email_attaches_workbook_and_screenshot(self) -> None:
        logger = logging.getLogger("test_nas_bulk_validation_email")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook = root / "nas_validation_errors.xlsx"
            screenshot = root / "validation.png"
            workbook.write_bytes(b"xlsx")
            screenshot.write_bytes(b"png")

            with (
                patch("src.portals.nas.nas_main.MailConfig.load", return_value=object()),
                patch("src.portals.nas.nas_main.send_outlook_email") as send_email,
            ):
                _send_nas_validation_error_email(
                    process_data={
                        "RequestId": "REQ-1",
                        "PolicyNumber": "POL-1",
                        "ActionType": "BULK",
                        "PortalName": "NAS",
                        "Status": "Validation Error",
                    },
                    error_message="NAS returned a validation workbook",
                    downloaded_file=workbook,
                    screenshot_path=screenshot,
                    logger=logger,
                )

            kwargs = send_email.call_args.kwargs
            self.assertEqual([workbook, screenshot], kwargs["attachments"])
            self.assertIn("Status : Validation Error", kwargs["subject"])
            self.assertIn("nas_validation_errors.xlsx", kwargs["body"])
            self.assertIn("NAS returned a validation workbook", kwargs["body"])


if __name__ == "__main__":
    unittest.main()
