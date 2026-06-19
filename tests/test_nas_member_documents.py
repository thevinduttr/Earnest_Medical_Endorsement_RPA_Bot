from __future__ import annotations

import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.services.document_service.nas_member_documents import (
    map_document_type_to_nas_field,
    prepare_nas_member_documents,
)


class NasMemberDocumentTests(unittest.TestCase):
    def test_document_type_mapping(self) -> None:
        self.assertEqual(
            "emirates_id",
            map_document_type_to_nas_field("Emirates ID Front"),
        )
        self.assertEqual("passport", map_document_type_to_nas_field("Passport"))
        self.assertEqual("visa", map_document_type_to_nas_field("Residence Visa"))
        self.assertEqual(
            "supporting_document",
            map_document_type_to_nas_field("Other Attachment"),
        )

    def test_documents_are_manifested_in_census_member_order(self) -> None:
        members = pd.DataFrame(
            [
                {
                    "UserId": "U2",
                    "FirstName": "Second",
                    "LastName": "Member",
                    "EmiratesId": "784-2",
                    "PassportNo": "P2",
                    "StaffId": "S2",
                },
                {
                    "UserId": "U1",
                    "FirstName": "First",
                    "LastName": "Member",
                    "EmiratesId": "784-1",
                    "PassportNo": "P1",
                    "StaffId": "S1",
                },
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            u2_document = root / "user_U2" / "PASSPORT.pdf"
            u1_document = root / "user_U1" / "EMIRATES_ID_FRONT.png"
            u2_document.parent.mkdir(parents=True)
            u1_document.parent.mkdir(parents=True)
            u2_document.write_bytes(b"pdf")
            u1_document.write_bytes(b"png")

            with (
                patch(
                    "src.services.document_service.nas_member_documents."
                    "load_request_members_dataframe",
                    return_value=members,
                ),
                patch(
                    "src.services.document_service.nas_member_documents."
                    "download_request_documents_for_users",
                    return_value=(
                        {
                            "U2": [u2_document],
                            "U1": [u1_document],
                        },
                        {},
                        [u2_document, u1_document],
                    ),
                ),
            ):
                result = prepare_nas_member_documents(
                    request_id="REQ-1",
                    user_ids=["U1", "U2"],
                    destination_root=root,
                    logger=logging.getLogger("test_nas_member_documents"),
                )

            self.assertEqual(["U2", "U1"], result.ordered_user_ids)
            self.assertEqual(
                ["Second Member", "First Member"],
                result.ordered_member_names,
            )
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("U2", manifest["members"][0]["user_id"])
            self.assertEqual("Second Member", manifest["members"][0]["member_name"])
            self.assertEqual(
                "passport",
                manifest["members"][0]["documents"][0]["nas_field"],
            )
            self.assertEqual(
                "emirates_id",
                manifest["members"][1]["documents"][0]["nas_field"],
            )

    def test_missing_member_documents_fail_clearly(self) -> None:
        members = pd.DataFrame([{"UserId": "U1", "FirstName": "First"}])
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "src.services.document_service.nas_member_documents."
                    "load_request_members_dataframe",
                    return_value=members,
                ),
                patch(
                    "src.services.document_service.nas_member_documents."
                    "download_request_documents_for_users",
                    return_value=({}, {}, []),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "documents are missing for UserIds: U1",
                ):
                    prepare_nas_member_documents(
                        request_id="REQ-1",
                        user_ids=["U1"],
                        destination_root=Path(temp_dir),
                        logger=logging.getLogger("test_nas_member_documents"),
                    )


if __name__ == "__main__":
    unittest.main()
