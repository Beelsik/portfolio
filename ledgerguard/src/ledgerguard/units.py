"""Packaging normalization and engineering parameter extraction (gauge, amperage, IP)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

UNIT_MAP: dict[str, str] = {
    "м": "m",
    "метр": "m",
    "метра": "m",
    "метров": "m",
    "метрів": "m",
    "п.м": "m",
    "м.п": "m",
    "m": "m",
    "ml": "m",
    "meter": "m",
    "meters": "m",
    "mètre": "m",
    "mètres": "m",
    "шт": "pcs",
    "штук": "pcs",
    "штуки": "pcs",
    "од": "pcs",
    "pcs": "pcs",
    "pc": "pcs",
    "ea": "pcs",
    "unit": "pcs",
    "units": "pcs",
    "u": "pcs",
    "pce": "pcs",
    "pièce": "pcs",
    "pièces": "pcs",
    "компл": "set",
    "комплект": "set",
    "set": "set",
    "kit": "set",
    "lot": "set",
    "кг": "kg",
    "kg": "kg",
}

BOUND_L = r"(?:^|[^a-zа-яіїєґ0-9])"
BOUND_R = r"(?=$|[^a-zа-яіїєґ0-9.,])"

_PACK_M_RE = re.compile(
    rf"{BOUND_L}(?:бухт[аыі]?|барабан|coils?|drums?|spools?|couronnes?|tourets?|rouleaux?)\s*(?:по|x|×|of|de)?\s*(\d{{2,4}})\s*(м|m){BOUND_R}",
    re.IGNORECASE,
)
_PACK_PCS_RE = re.compile(
    rf"{BOUND_L}(?:упак(?:овк[аи])?|уп\.?|кор(?:обк[аи])?|пачк[аи]|packs?|box(?:es)?|boîtes?|sachets?)\s*(?:по|x|×|of|de)?\s*(\d{{2,4}})\s*(шт\.?|од\.?|pcs|pce|u)?{BOUND_R}",
    re.IGNORECASE,
)


UNIT_LABELS: dict[str, dict[str, str]] = {
    "ru": {"m": "м", "pcs": "шт", "set": "компл", "kg": "кг"},
    "uk": {"m": "м", "pcs": "шт", "set": "компл", "kg": "кг"},
    "fr": {"m": "m", "pcs": "u", "set": "lot", "kg": "kg"},
    "en": {"m": "m", "pcs": "pcs", "set": "set", "kg": "kg"},
}


def format_unit(unit_code: str, lang: str = "en") -> str:
    """Format canonical unit code into localized display label."""
    table = UNIT_LABELS.get((lang or "en").lower(), UNIT_LABELS["en"])
    return table.get(unit_code, unit_code)


def normalize_unit_code(raw_unit: str) -> str:
    """Normalize multilingual unit strings into canonical base units ('m', 'pcs', 'set', 'kg')."""
    cleaned = str(raw_unit or "").strip().lower().rstrip(".")
    return UNIT_MAP.get(cleaned, cleaned or "pcs")


def expand_pack_conversion(
    description: str,
    raw_qty: str,
    raw_unit: str,
    unit_price_minor: int,
    lang: str = "en",
) -> dict[str, object]:
    """Expand coil/box/pack quantities into canonical base units and divide unit price."""
    text = f"{description or ''} {raw_unit or ''}"
    canon_unit = normalize_unit_code(raw_unit)
    raw_unit_lower = str(raw_unit or "").strip().lower()
    input_is_pack = not raw_unit_lower or bool(
        re.search(
            r"бухт|уп|кор|пач|барабан|coil|drum|spool|pack|box|couronne|rouleau|boîte|шт|од|pcs|pce|u",
            raw_unit_lower,
        )
    )

    try:
        q_dec = Decimal(str(raw_qty).replace(",", "."))
    except InvalidOperation:
        q_dec = Decimal(1)

    for rx, default_target in ((_PACK_M_RE, "m"), (_PACK_PCS_RE, "pcs")):
        m = rx.search(text)
        if not m:
            continue
        factor = int(m.group(1))
        target_unit = default_target
        # Avoid double multiplication if the buyer already entered linear meters
        if target_unit == "m" and canon_unit == "m" and not re.search(
            r"бухт|coil|couronne|rouleau", raw_unit_lower
        ):
            break
        if factor > 1 and input_is_pack:
            norm_qty = q_dec * Decimal(factor)
            norm_unit_minor = int(
                (Decimal(unit_price_minor) / Decimal(factor)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            qty_fmt = str(norm_qty.normalize()) if "." in str(norm_qty) else str(norm_qty)
            if qty_fmt.endswith(".0"):
                qty_fmt = qty_fmt[:-2]
            disp_u = format_unit(target_unit, lang)
            return {
                "converted": True,
                "pack_factor": factor,
                "normalized_qty": qty_fmt,
                "normalized_unit": target_unit,
                "normalized_unit_minor": norm_unit_minor,
                "note": f"{raw_qty} × {factor} {disp_u} = {qty_fmt} {disp_u}",
            }

    return {
        "converted": False,
        "pack_factor": 1,
        "normalized_qty": str(raw_qty).replace(",", "."),
        "normalized_unit": canon_unit,
        "normalized_unit_minor": int(unit_price_minor),
        "note": None,
    }


def extract_tech_signature(raw_text: str) -> dict[str, str | None]:
    """Extract canonical electrical/industrial specs so similar SKUs are never swapped."""
    lower = str(raw_text or "").lower().replace("ё", "е")

    # Cable cores x cross-section: 3*2,5 / 3х2.5 / 3*2.5м / 3G2.5 -> "3x2.5"
    sec_m = re.search(
        rf"{BOUND_L}(\d{{1,2}})\s*[*xхg×]\s*(\d{{1,3}}(?:[.,]\d{{1,2}})?)\s*(?:мм2|мм²|mm2|mm²|м|m)?{BOUND_R}",
        lower,
    )
    section = None
    if sec_m:
        num = sec_m.group(2).replace(",", ".")
        if num.endswith(".0"):
            num = num[:-2]
        section = f"{sec_m.group(1)}x{num}"

    # Breaker curve (B/C) or explicit amperage (16A, 25A) - avoids colliding with conduit d20
    amp_m = re.search(rf"{BOUND_L}(?:[bcсв](\d{{1,3}})|(\d{{1,3}})\s*[aа]){BOUND_R}", lower)
    amps = f"{amp_m.group(1) or amp_m.group(2)}a" if amp_m else None

    # Ingress protection: IP65 / IP54 -> "ip65"
    ip_m = re.search(rf"{BOUND_L}ip\s*(\d{{2}}){BOUND_R}", lower)
    ip = f"ip{ip_m.group(1)}" if ip_m else None

    # Conduit diameter when no cable section is present: d20 / ф20 / 20мм -> "d20"
    dia_m = (
        None
        if section
        else re.search(rf"{BOUND_L}(?:[dдфø]\s*(\d{{2,3}})|(\d{{2}})\s*(?:мм|mm)){BOUND_R}", lower)
    )
    diameter = f"d{dia_m.group(1) or dia_m.group(2)}" if dia_m else None

    # Power rating: 36Вт / 36W -> "36w"
    watt_m = re.search(rf"{BOUND_L}(\d{{1,4}})\s*(?:вт|w){BOUND_R}", lower)
    watts = f"{watt_m.group(1)}w" if watt_m else None

    return {"section": section, "amps": amps, "ip": ip, "diameter": diameter, "watts": watts}
