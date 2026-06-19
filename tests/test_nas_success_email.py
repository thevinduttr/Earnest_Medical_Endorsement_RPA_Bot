from __future__ import annotations

import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.portals.nas.nas_main import _send_nas_success_email


class NasSuccessEmailTests(unittest.TestCase):
    def test_success_email_attaches_screenshot_and_reports_member_count(self) -> None:
        logger = logging.getLogger("test_nas_success_email")
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "nas_bulk_add_success.png"
            second_screenshot = Path(temp_dir) / "nas_bulk_add_member_2.png"
            screenshot.write_bytes(b"png")
            second_screenshot.write_bytes(b"png")
            process_data: dict[str, object] = {
                "RequestId": "REQ-1",
                "PolicyNumber": "POL-1",
                "ActionType": "BULK",
                "PortalName": "NAS",
                "Status": "Addion Completed",
                "ReferenceNumber": "",
                "ProcessedMembers": 3,
            }

            with (
                patch("src.portals.nas.nas_main.MailConfig.load", return_value=object()),
                patch("src.portals.nas.nas_main.send_outlook_email") as send_email,
            ):
                _send_nas_success_email(
                    process_data=process_data,
                    screenshot_paths=[screenshot, second_screenshot],
                    logger=logger,
                )

            kwargs = send_email.call_args.kwargs
            self.assertEqual(
                [screenshot, second_screenshot],
                kwargs["attachments"],
            )
            self.assertIn("Status : Addion Completed", kwargs["subject"])
            self.assertIn("Processed Members", kwargs["body"])
            self.assertIn(">3<", kwargs["body"])
            self.assertIn("nas_bulk_add_success.png", kwargs["body"])
            self.assertIn("nas_bulk_add_member_2.png", kwargs["body"])
            self.assertNotIn("submission reference number was captured", kwargs["body"])

    def test_test_mode_email_is_sent_with_honest_status(self) -> None:
        logger = logging.getLogger("test_nas_success_email_test_mode")
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = Path(temp_dir) / "nas_bulk_add_success.png"
            screenshot.write_bytes(b"png")
            process_data: dict[str, object] = {
                "RequestId": "REQ-TEST",
                "PolicyNumber": "POL-TEST",
                "ActionType": "BULK",
                "PortalName": "NAS",
                "Status": "Test Review Completed",
                "ReferenceNumber": "",
                "ProcessedMembers": 2,
                "SubmissionSkipped": True,
            }

            with (
                patch("src.portals.nas.nas_main.MailConfig.load", return_value=object()),
                patch("src.portals.nas.nas_main.send_outlook_email") as send_email,
            ):
                _send_nas_success_email(
                    process_data=process_data,
                    screenshot_paths=[screenshot],
                    logger=logger,
                )

            kwargs = send_email.call_args.kwargs
            self.assertIn("Status : Test Review Completed", kwargs["subject"])
            self.assertIn("NAS Test Review Completed", kwargs["body"])
            self.assertIn("Submit clicks were skipped", kwargs["body"])
            self.assertEqual([screenshot], kwargs["attachments"])


if __name__ == "__main__":
    unittest.main()
