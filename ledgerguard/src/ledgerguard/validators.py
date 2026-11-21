"""Statutory tax-ID and bank-account checksum validators (RU, UA, FR, EU/GB, IBAN)."""

from __future__ import annotations

import re
from typing import Any


def validate_ru_inn(raw: str) -> dict[str, Any]:
    """Validate 10-digit (legal entity) or 12-digit (IE) Russian INN checksum."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) not in (10, 12):
        return {"valid": False, "normalized": digits, "reason": "INN_LENGTH"}
    if set(digits) == {"0"}:
        return {"valid": False, "normalized": digits, "reason": "INN_ZERO"}

    n = [int(ch) for ch in digits]
    calc = lambda weights: (sum(w * n[i] for i, w in enumerate(weights)) % 11) % 10

    if len(digits) == 10:
        c10 = calc([2, 4, 10, 3, 5, 9, 4, 6, 8])
        ok = c10 == n[9]
        return {
            "valid": ok,
            "normalized": digits,
            "reason": "OK" if ok else f"INN_CHECKSUM_MISMATCH(expected:{c10},got:{n[9]})",
        }

    c11 = calc([7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    c12 = calc([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8])
    ok = c11 == n[10] and c12 == n[11]
    return {
        "valid": ok,
        "normalized": digits,
        "reason": "OK" if ok else f"INN12_CHECKSUM_MISMATCH(expected:{c11}{c12},got:{n[10]}{n[11]})",
    }


def validate_ua_edrpou(raw: str) -> dict[str, Any]:
    """Validate 8-digit Ukrainian EDRPOU checksum per official statutory algorithm."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) != 8:
        return {"valid": False, "normalized": digits, "reason": "EDRPOU_LENGTH"}
    num = int(digits)
    if num == 0:
        return {"valid": False, "normalized": digits, "reason": "EDRPOU_ZERO"}

    n = [int(ch) for ch in digits]
    high_range = 30000000 < num < 60000000
    w1 = [7, 1, 2, 3, 4, 5, 6] if high_range else [1, 2, 3, 4, 5, 6, 7]
    w2 = [9, 3, 4, 5, 6, 7, 8] if high_range else [3, 4, 5, 6, 7, 8, 9]

    rem = sum(w1[i] * n[i] for i in range(7)) % 11
    if rem >= 10:
        rem = sum(w2[i] * n[i] for i in range(7)) % 11
        if rem >= 10:
            rem = 0

    ok = rem == n[7]
    return {
        "valid": ok,
        "normalized": digits,
        "reason": "OK" if ok else f"EDRPOU_CHECKSUM_MISMATCH(expected:{rem},got:{n[7]})",
    }


def validate_fr_siret(raw: str) -> dict[str, Any]:
    """Validate 14-digit French SIRET using the standard Luhn checksum."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) != 14:
        return {"valid": False, "normalized": digits, "reason": "SIRET_LENGTH"}
    total = 0
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    ok = total % 10 == 0
    return {"valid": ok, "normalized": digits, "reason": "OK" if ok else "SIRET_LUHN_FAILED"}


def validate_eu_vat(raw: str) -> dict[str, Any]:
    """Validate EU/UK VAT ID format (country code + 7..12 alphanumeric characters)."""
    cleaned = re.sub(r"[\s.-]+", "", str(raw or "")).upper()
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{7,12}", cleaned):
        return {"valid": True, "normalized": cleaned, "reason": "OK"}
    return {"valid": False, "normalized": cleaned, "reason": "VAT_FORMAT_INVALID"}


def validate_iban(raw: str) -> dict[str, Any]:
    """Validate ISO 13616 IBAN via modulo-97 check."""
    iban = re.sub(r"\s+", "", str(raw or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return {"valid": False, "normalized": iban, "reason": "IBAN_FORMAT"}
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    rem = int(numeric) % 97
    ok = rem == 1
    return {
        "valid": ok,
        "normalized": iban,
        "reason": "OK" if ok else f"IBAN_MOD97_FAILED(rem:{rem})",
    }


def validate_ru_bank_account(account_raw: str, bik_raw: str = "") -> dict[str, Any]:
    """Validate 20-digit Russian bank settlement account with CBR BIK control key."""
    acc = re.sub(r"\D", "", str(account_raw or ""))
    if len(acc) != 20:
        return {"valid": False, "normalized": acc, "reason": "RU_ACC_LENGTH"}
    bik = re.sub(r"\D", "", str(bik_raw or ""))
    if len(bik) != 9:
        return {"valid": True, "normalized": acc, "reason": "OK_NO_BIK"}

    check_str = bik[6:9] + acc
    weights = [7, 1, 3] * 7 + [7, 1]
    total = sum((int(check_str[i]) * weights[i]) % 10 for i in range(23))
    ok = total % 10 == 0
    return {"valid": ok, "normalized": acc, "reason": "OK" if ok else "RU_ACC_BIK_KEY_MISMATCH"}


def validate_tax_id(tax_id: str, regime: str = "RU") -> dict[str, Any]:
    """Dispatch statutory tax-ID validation according to legal jurisdiction."""
    r = str(regime or "RU").upper()
    if r == "RU":
        return validate_ru_inn(tax_id)
    if r in ("UA", "UK", "UKR"):
        return validate_ua_edrpou(tax_id)
    if r == "FR":
        return validate_fr_siret(tax_id)
    return validate_eu_vat(tax_id)


def validate_bank_account(account: str, regime: str = "RU", bik: str = "") -> dict[str, Any]:
    """Validate IBAN (UA/FR/EU/GB) or 20-digit CBR account + BIK (RU)."""
    clean = re.sub(r"\s+", "", str(account or "")).upper()
    if clean[:2].isalpha():
        return validate_iban(clean)
    if str(regime or "RU").upper() == "RU":
        return validate_ru_bank_account(clean, bik)
    return validate_iban(clean)
