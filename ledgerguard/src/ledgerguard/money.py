"""Exact Decimal integer minor-unit arithmetic (kopeks, cents, pence) for B2B invoices."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

CURRENCY_META: dict[str, dict[str, Any]] = {
    "RUB": {"symbol": "₽", "minor": 100, "pos": "after"},
    "UAH": {"symbol": "₴", "minor": 100, "pos": "after"},
    "EUR": {"symbol": "€", "minor": 100, "pos": "after"},
    "USD": {"symbol": "$", "minor": 100, "pos": "before"},
    "GBP": {"symbol": "£", "minor": 100, "pos": "before"},
}


def parse_money_to_minor(raw: str | int | float | Decimal | None) -> int | None:
    """Parse formatted monetary amounts ("14 520,50 ₽", "$1,240.00") to integer minor units."""
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return int((raw * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            d = Decimal(str(raw))
        except InvalidOperation:
            return None
        if not d.is_finite():
            return None
        return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    s = re.sub(r"[\u00A0\u202F\s]+", "", str(raw))
    s = re.sub(r"[₽₴€$£]|руб\.?|грн\.?|eur|usd|gbp", "", s, flags=re.IGNORECASE).strip()
    if not s:
        return None

    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:]

    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    if last_comma > -1 and last_dot > -1:
        if last_comma > last_dot:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif last_comma > -1:
        decimals = len(s) - last_comma - 1
        s = s.replace(",", "") if (decimals == 3 and not s.startswith("0,")) else s.replace(",", ".")
    elif last_dot > -1:
        parts = s.split(".")
        if len(parts) > 2:
            dec = parts.pop()
            s = "".join(parts) + "." + dec

    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return None

    try:
        dec_val = Decimal(s)
    except InvalidOperation:
        return None
    minor = int((dec_val * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return -minor if neg else minor


def compute_line_total_minor(qty: str | int | float | Decimal, unit_price_minor: int) -> int:
    """Compute exact line total in minor units using Decimal multiplication and half-up rounding."""
    try:
        q = qty if isinstance(qty, Decimal) else Decimal(str(qty).replace(",", "."))
        price = Decimal(unit_price_minor)
    except InvalidOperation:
        return 0
    if not q.is_finite():
        return 0
    return int((q * price).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def reconcile_vat_and_totals(
    computed_lines_sum_minor: int,
    stated_total_minor: int | None = None,
    stated_vat_minor: int | None = None,
    vat_rate_pct: int = 20,
    vat_mode: str = "included",
    rounding_tolerance_minor: int = 2,
) -> dict[str, int | bool | None]:
    """Verify invoice gross total and VAT breakdown with zero floating-point drift."""
    rate = Decimal(max(0, int(vat_rate_pct or 0)))
    lines_sum = Decimal(computed_lines_sum_minor)

    expected_gross = lines_sum
    expected_vat = Decimal(0)
    expected_net = lines_sum

    if rate > 0 and vat_mode == "included":
        expected_gross = lines_sum
        expected_vat = ((expected_gross * rate) / (Decimal(100) + rate)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        expected_net = expected_gross - expected_vat
    elif rate > 0 and vat_mode == "added":
        expected_net = lines_sum
        expected_vat = ((expected_net * rate) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        expected_gross = expected_net + expected_vat

    exp_gross_i = int(expected_gross)
    exp_vat_i = int(expected_vat)
    exp_net_i = int(expected_net)

    total_delta = 0 if stated_total_minor is None else stated_total_minor - exp_gross_i
    vat_delta = 0 if stated_vat_minor is None else stated_vat_minor - exp_vat_i

    total_ok = stated_total_minor is None or abs(total_delta) <= rounding_tolerance_minor
    vat_ok = stated_vat_minor is None or abs(vat_delta) <= max(rounding_tolerance_minor, 5)

    return {
        "expected_net_minor": exp_net_i,
        "expected_vat_minor": exp_vat_i,
        "expected_gross_minor": exp_gross_i,
        "stated_total_minor": stated_total_minor,
        "stated_vat_minor": stated_vat_minor,
        "total_delta_minor": total_delta,
        "vat_delta_minor": vat_delta,
        "total_ok": total_ok,
        "vat_ok": vat_ok,
    }


def format_minor(minor: int | None, currency: str = "RUB", lang: str = "ru") -> str:
    """Format integer minor units nicely according to currency and UI language."""
    if minor is None:
        return "—"
    meta = CURRENCY_META.get(currency.upper(), CURRENCY_META["USD"])
    sign = "-" if minor < 0 else ""
    abs_val = abs(int(minor))
    whole = abs_val // 100
    frac = abs_val % 100
    if lang == "en":
        whole_str = f"{whole:,}"
        num_str = f"{whole_str}.{frac:02d}"
    else:
        whole_str = f"{whole:,}".replace(",", "\u00A0")
        num_str = f"{whole_str},{frac:02d}"
    sym = meta["symbol"]
    return f"{sign}{sym}{num_str}" if meta["pos"] == "before" else f"{sign}{num_str} {sym}"
