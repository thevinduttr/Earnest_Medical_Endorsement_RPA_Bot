from __future__ import annotations

import unittest

from src.portals.nas.add_process.bulk_member.bulk_add_member import (
    normalize_bulk_contract_name,
    resolve_payer_name_from_email_filename,
)


class NasBulkMatchingTests(unittest.TestCase):
    def test_removes_forward_prefix_from_contract_name(self) -> None:
        self.assertEqual(
            "JASHANMAL NATIONAL CO LLC",
            normalize_bulk_contract_name("Fw: JASHANMAL NATIONAL CO LLC"),
        )

    def test_removes_repeated_mail_prefixes(self) -> None:
        self.assertEqual(
            "JASHANMAL NATIONAL CO LLC",
            normalize_bulk_contract_name("RE: Fwd: FW: JASHANMAL NATIONAL CO LLC"),
        )

    def test_resolves_qic_payer_from_email_filename(self) -> None:
        filename = (
            "20260617_045805_20260617_045758_"
            "Fw__JASHANMAL_NATIONAL_CO_LLC_-_QIC_-_ADDI_404bcd067e.eml"
        )

        self.assertEqual(
            "Qatar Insurance Company - QIC - NAS",
            resolve_payer_name_from_email_filename(filename),
        )

    def test_resolves_liva_payer_from_email_filename(self) -> None:
        filename = "20260617_Fw__EXAMPLE_COMPANY_-_LIVA_-_ADDITION.eml"

        self.assertEqual(
            "Liva Insurance B.S.C. (C) - LIVA - Nas",
            resolve_payer_name_from_email_filename(filename),
        )

    def test_returns_none_when_filename_has_no_known_payer(self) -> None:
        self.assertIsNone(resolve_payer_name_from_email_filename("request_addition.eml"))


if __name__ == "__main__":
    unittest.main()
