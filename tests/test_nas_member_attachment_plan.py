from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.portals.nas.add_process.bulk_member.bulk_add_member import (
    _build_member_attachment_plan,
)


class NasMemberAttachmentPlanTests(unittest.TestCase):
    def test_builds_field_wise_upload_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            passport = root / "PASSPORT.pdf"
            national_id = root / "EMIRATES_ID.png"
            passport.write_bytes(b"pdf")
            national_id.write_bytes(b"png")

            plan = _build_member_attachment_plan(
                [
                    {"nas_field": "passport_copy", "path": str(passport)},
                    {"nas_field": "national_id_copy", "path": str(national_id)},
                ]
            )

            self.assertEqual(
                [
                    ("passport_copy", passport.resolve()),
                    ("national_id_copy", national_id.resolve()),
                ],
                plan,
            )

    def test_duplicate_field_uses_other_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            front = root / "EID_FRONT.png"
            back = root / "EID_BACK.png"
            front.write_bytes(b"front")
            back.write_bytes(b"back")

            plan = _build_member_attachment_plan(
                [
                    {"nas_field": "national_id_copy", "path": str(front)},
                    {"nas_field": "national_id_copy", "path": str(back)},
                ]
            )

            self.assertEqual("national_id_copy", plan[0][0])
            self.assertEqual("other_attachment", plan[1][0])

    def test_rejects_files_over_portal_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            oversized = Path(temp_dir) / "large.pdf"
            oversized.write_bytes(b"x" * (3 * 1024 * 1024 + 1))

            with self.assertRaisesRegex(ValueError, "3 MB limit"):
                _build_member_attachment_plan(
                    [{"nas_field": "passport_copy", "path": str(oversized)}]
                )


if __name__ == "__main__":
    unittest.main()
