"""Unit tests for statutory tax/IBAN checksums and exact Decimal money math."""

import unittest

from ledgerguard.money import compute_line_total_minor, parse_money_to_minor, reconcile_vat_and_totals
from ledgerguard.units import expand_pack_conversion, extract_tech_signature
from ledgerguard.validators import (
    validate_fr_siret,
    validate_iban,
    validate_ru_bank_account,
    validate_ru_inn,
    validate_ua_edrpou,
)


class TestValidatorsAndMoney(unittest.TestCase):
    def test_ru_inn_and_bank_account_checksums(self) -> None:
        self.assertTrue(validate_ru_inn("7707083893")["valid"])
        self.assertFalse(validate_ru_inn("7707083894")["valid"])
        self.assertTrue(validate_ru_bank_account("40702810438000124500", "044525225")["valid"])
        self.assertTrue(validate_ru_bank_account("40702810638000998811", "044525225")["valid"])
        self.assertFalse(validate_ru_bank_account("40702810938000124500", "044525225")["valid"])

    def test_ua_edrpou_fr_siret_and_iban_checksums(self) -> None:
        self.assertTrue(validate_ua_edrpou("38492011")["valid"])
        self.assertFalse(validate_ua_edrpou("38492012")["valid"])
        self.assertTrue(validate_fr_siret("73282932000074")["valid"])
        self.assertFalse(validate_fr_siret("73282932000075")["valid"])
        self.assertTrue(validate_iban("UA213223130000026007233566001")["valid"])
        self.assertTrue(validate_iban("FR1420041010050500013M02606")["valid"])
        self.assertTrue(validate_iban("GB29NWBK60161331926819")["valid"])
        self.assertFalse(validate_iban("GB29NWBK60161331926810")["valid"])

    def test_exact_decimal_money_parsing_and_vat(self) -> None:
        self.assertEqual(parse_money_to_minor("14 520,50 ₽"), 1452050)
        self.assertEqual(parse_money_to_minor("$1,240.05"), 124005)
        self.assertEqual(compute_line_total_minor("12.5", 14500), 181250)
        vat = reconcile_vat_and_totals(
            computed_lines_sum_minor=4645000,
            stated_total_minor=4645000,
            stated_vat_minor=774167,
            vat_rate_pct=20,
            vat_mode="included",
        )
        self.assertTrue(vat["total_ok"])
        self.assertTrue(vat["vat_ok"])
        self.assertEqual(vat["expected_vat_minor"], 774167)

    def test_pack_expansion_and_engineering_signature(self) -> None:
        conv = expand_pack_conversion("ввгнг лс 3*2.5м (бухта 100м)", "3", "бухта", 1150000)
        self.assertTrue(conv["converted"])
        self.assertEqual(conv["normalized_qty"], "300")
        self.assertEqual(conv["normalized_unit"], "m")
        self.assertEqual(conv["normalized_unit_minor"], 11500)

        sig_25 = extract_tech_signature("Кабель ВВГнг(А)-LS 3х2,5 ГОСТ")
        sig_15 = extract_tech_signature("Кабель ВВГнг(А)-LS 3х1,5")
        self.assertEqual(sig_25["section"], "3x2.5")
        self.assertEqual(sig_15["section"], "3x1.5")


if __name__ == "__main__":
    unittest.main()
