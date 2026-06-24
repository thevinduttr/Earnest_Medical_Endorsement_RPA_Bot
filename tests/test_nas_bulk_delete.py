from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.portals.nas.delete_process.bulk_member.bulk_delete_member import (
    _resolve_delete_excel_path,
)
from src.portals.nas.nas_main import _resolve_process_key
from src.portals.nas.main_process.request_dashboard_page import (
    _resolve_dashboard_action,
)


class NasBulkDeleteRoutingTests(unittest.TestCase):
    def test_delete_batch_input_is_normalized_to_bulk_process(self) -> None:
        self.assertEqual("delete_bulk", _resolve_process_key("DELETE", "BATCH"))

    def test_delete_bulk_uses_cancel_bulk_members_dashboard_action(self) -> None:
        action = _resolve_dashboard_action("delete_bulk")

        self.assertEqual("cancel_bulk_member_button", action["key"])
        self.assertEqual("NAS Cancel Bulk Members", action["label"])
        self.assertEqual("import_choose_file_button", action["next_key"])

    def test_delete_batch_dashboard_process_is_not_supported_separately(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported NAS request dashboard process"):
            _resolve_dashboard_action("delete_batch")

    def test_delete_excel_path_resolves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            excel_path = Path(temp_dir) / "Deletion.xlsx"
            excel_path.write_bytes(b"placeholder")

            resolved = _resolve_delete_excel_path(
                {"batch_delete_member_file": str(excel_path)}
            )

            self.assertEqual(excel_path.resolve(), resolved)

    def test_delete_excel_path_requires_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch_delete_member_file"):
            _resolve_delete_excel_path({})


if __name__ == "__main__":
    unittest.main()
