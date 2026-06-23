from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from src.portals.nas.add_process.family_member.family_member_search import (
    resolve_principal_name,
)

logger = logging.getLogger("test_nas_family_member")


class NasFamilyMemberResolutionTests(unittest.TestCase):
    def test_resolves_name_using_sponsor_id_matching_staff_id(self) -> None:
        row = {"SponsorId": "S-101"}
        all_members = [
            {"FirstName": "John", "MiddleName": "D.", "LastName": "Doe", "Relation": "Employee", "StaffId": "S-101"},
            {"FirstName": "Jane", "MiddleName": "", "LastName": "Smith", "Relation": "Spouse", "StaffId": "S-102"},
        ]
        resolved = resolve_principal_name(row, all_members, "POL-123", logger)
        self.assertEqual("John D. Doe", resolved)

    def test_resolves_name_using_unique_principal_in_request(self) -> None:
        row = {"SponsorId": ""}
        all_members = [
            {"FirstName": "John", "MiddleName": "", "LastName": "Doe", "Relation": "Employee", "StaffId": "S-101"},
            {"FirstName": "Jane", "MiddleName": "", "LastName": "Smith", "Relation": "Spouse", "StaffId": "S-102"},
        ]
        resolved = resolve_principal_name(row, all_members, "POL-123", logger)
        self.assertEqual("John Doe", resolved)

    def test_resolves_name_directly_from_alphabetic_sponsor_id(self) -> None:
        row = {"SponsorId": "Joan Mallillin Landicho"}
        all_members = [
            {"FirstName": "Jane", "MiddleName": "", "LastName": "Smith", "Relation": "Spouse", "StaffId": "S-102"},
        ]
        resolved = resolve_principal_name(row, all_members, "POL-123", logger)
        self.assertEqual("Joan Mallillin Landicho", resolved)

    @patch("src.portals.nas.add_process.family_member.family_member_search.AzureSQLConnection")
    def test_resolves_name_using_database_lookup(self, mock_db_conn_class: MagicMock) -> None:
        # Mock DB setup
        mock_db_instance = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        mock_db_conn_class.return_value.__enter__.return_value = mock_db_instance
        mock_db_instance.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("Joan", "Mallillin", "Landicho")

        row = {"SponsorId": "23432"}
        all_members = [
            {"FirstName": "Jane", "MiddleName": "", "LastName": "Smith", "Relation": "Spouse", "StaffId": "S-102"},
        ]
        resolved = resolve_principal_name(row, all_members, "POL-123", logger)
        
        self.assertEqual("Joan Mallillin Landicho", resolved)
        mock_cursor.execute.assert_called_once()
        query_arg = mock_cursor.execute.call_args[0][0]
        params_arg = mock_cursor.execute.call_args[0][1]
        self.assertIn("SELECT TOP 1 FirstName", query_arg)
        self.assertEqual(["23432", "23432", "23432", "23432", "POL-123"], params_arg)


if __name__ == "__main__":
    unittest.main()
