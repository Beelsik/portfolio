"""Legacy workflow simulator ('Было'): reproduces failures of manual / 1-prompt intake."""

from __future__ import annotations

from decimal import Decimal
import re
from typing import Any

from .matcher import CatalogMatcher
from .models import CatalogItem, ContractTerms, InboundDocument, LegacySimResult, VendorRecord
from .money import compute_line_total_minor, format_minor
from .units import expand_pack_conversion

_MSG = {
    "ru": {
        "bank": "Платёж проведён на подменённые реквизиты ({actual}) вместо эталона договора ({expected}) — уход денег",
        "math_line": "Строка {ln}: принята завышенная сумма документа без пересчёта (переплата {delta})",
        "math_tot": "Итог счёта принят на веру без проверки суммы строк и НДС (расхождение {delta})",
        "cap": "Строка {ln} ({sku}): цена {actual} проведена выше потолка договора {expected} (переплата {delta})",
        "pack": "Строка {ln}: единица упаковки записана в штуках/бухтах без пересчёта в базовые метры ({note})",
        "wrong_sku": "Строка {ln}: похожий артикул перепутан без защиты технических параметров ({raw} → {picked})",
        "dup": "Повторный документ проведён в учёт второй раз (нет idempotency-ключа)",
        "sum_bad": "В старом процессе (1 промпт / ручная приёмка) счёт прошёл бы молча в учёт с {n} скрытыми ошибками.",
        "sum_ok": "Формально прошёл бы, но без нормализации упаковок и гарантии от дублей.",
    },
    "uk": {
        "bank": "Оплату проведено на підмінені реквізити ({actual}) замість еталона договору ({expected}) — ризик втрати коштів",
        "math_line": "Рядок {ln}: прийнято завищену суму документа без перерахунку (переплата {delta})",
        "math_tot": "Підсумок рахунку прийнято на віру без перевірки суми рядків і ПДВ (розбіжність {delta})",
        "cap": "Рядок {ln} ({sku}): ціну {actual} проведено вище межі договору {expected} (переплата {delta})",
        "pack": "Рядок {ln}: пакування проведено без перерахунку в базові одиниці ({note})",
        "wrong_sku": "Рядок {ln}: схожий артикул переплутано без перевірки технічних параметрів ({raw} → {picked})",
        "dup": "Повторний документ проведено в облік вдруге (немає ключа ідемпотентності)",
        "sum_bad": "У старому процесі (1 промпт / ручне занесення) рахунок пішов би мовчки в облік із {n} прихованими помилками.",
        "sum_ok": "Формально пройшов би, але без перерахунку паковань та захисту від дублів.",
    },
    "en": {
        "bank": "Payment routed to swapped bank account ({actual}) instead of master vendor IBAN ({expected}) — wire fraud missed",
        "math_line": "Line {ln}: invoice subtotal accepted without integer recomputation (overcharge {delta})",
        "math_tot": "Header total accepted blindly without line/VAT reconciliation (variance {delta})",
        "cap": "Line {ln} ({sku}): billed unit price {actual} exceeded contract cap {expected} (overcharge {delta})",
        "pack": "Line {ln}: coil/pack quantity booked literally without base-unit conversion ({note})",
        "wrong_sku": "Line {ln}: look-alike SKU silently swapped without spec guard ({raw} → {picked})",
        "dup": "Re-submitted invoice posted as a duplicate ERP bill (no idempotency lock)",
        "sum_bad": "Legacy intake (manual / single-prompt LLM) would blindly post this document into ERP with {n} silent error(s).",
        "sum_ok": "Legacy intake would accept it without pack normalization or replay protection.",
    },
    "fr": {
        "bank": "Paiement orienté vers un IBAN substitué ({actual}) au lieu du RIB contrat ({expected}) — fraude manquée",
        "math_line": "Ligne {ln} : sous-total facture accepté sans recalcul exact (surfacturation {delta})",
        "math_tot": "Total TTC accepté sans contrôle des lignes ni de la TVA (écart {delta})",
        "cap": "Ligne {ln} ({sku}) : prix {actual} validé au-dessus du plafond contrat {expected} (surcoût {delta})",
        "pack": "Ligne {ln} : conditionnement enregistré brut sans conversion en unités de base ({note})",
        "wrong_sku": "Ligne {ln} : référence proche confondue faute de garde-fou technique ({raw} → {picked})",
        "dup": "Doublon créé en comptabilité lors d'une seconde réception (aucune clé d'idempotence)",
        "sum_bad": "L'ancien flux (saisie / prompt unique) aurait validé ce dossier dans l'ERP avec {n} anomalie(s) silencieuse(s).",
        "sum_ok": "Accepté sans conversion des conditionnements ni verrou anti-doublon.",
    },
}


def run_legacy_baseline(
    doc: InboundDocument,
    catalog: list[CatalogItem],
    vendor: VendorRecord | None,
    contract: ContractTerms | None,
    is_replay: bool,
    computed_lines_sum_minor: int,
    expected_gross_minor: int,
    lang: str = "ru",
) -> LegacySimResult:
    """Measure every financial/operational failure a single-prompt / manual intake misses."""
    msg = _MSG.get(lang, _MSG["en"])
    matcher = CatalogMatcher(catalog)
    silent_errors: list[dict[str, Any]] = []
    overpayment_minor = 0
    wrong_skus = 0
    bank_hijack_missed = False

    def clean_acc(s: str) -> str:
        return re.sub(r"\s+", "", s or "").upper()

    if vendor and doc.header.bank_account:
        if clean_acc(doc.header.bank_account) != clean_acc(vendor.approved_bank_account):
            bank_hijack_missed = True
            silent_errors.append(
                {
                    "type": "BANK_HIJACK_MISSED",
                    "impact_minor": expected_gross_minor,
                    "detail": msg["bank"].format(
                        actual=doc.header.bank_account, expected=vendor.approved_bank_account
                    ),
                }
            )

    for line in doc.lines:
        strict_match = matcher.match(line.raw_code, line.description, naive_mode=False)
        naive_match = matcher.match(line.raw_code, line.description, naive_mode=True)
        pack = expand_pack_conversion(line.description, line.qty, line.unit, line.unit_price_minor)

        if pack["converted"]:
            silent_errors.append(
                {
                    "type": "PACK_UNIT_DISTORTION",
                    "impact_minor": 0,
                    "detail": msg["pack"].format(ln=line.line_no, note=pack["note"]),
                }
            )

        if strict_match["matched"] and naive_match["sku"] != strict_match["sku"]:
            wrong_skus += 1
            silent_errors.append(
                {
                    "type": "SPEC_SKU_MISMATCH",
                    "impact_minor": 0,
                    "detail": msg["wrong_sku"].format(
                        ln=line.line_no, raw=line.description, picked=naive_match["sku"]
                    ),
                }
            )

        exact_line_total = compute_line_total_minor(line.qty, line.unit_price_minor)
        if line.stated_line_total_minor is not None and line.stated_line_total_minor > exact_line_total + 2:
            delta = line.stated_line_total_minor - exact_line_total
            overpayment_minor += delta
            silent_errors.append(
                {
                    "type": "LINE_OVERCHARGE_MISSED",
                    "impact_minor": delta,
                    "detail": msg["math_line"].format(
                        ln=line.line_no,
                        delta=format_minor(delta, doc.header.currency, lang),
                    ),
                }
            )

        if strict_match["matched"] and contract and strict_match["sku"] in contract.price_caps_minor:
            cap = contract.price_caps_minor[strict_match["sku"]]
            eff_price = int(pack["normalized_unit_minor"])
            if eff_price > cap:
                qty_num = Decimal(str(pack["normalized_qty"]))
                delta = int(((Decimal(eff_price - cap)) * qty_num).to_integral_value())
                overpayment_minor += delta
                silent_errors.append(
                    {
                        "type": "CONTRACT_OVERBILLING_MISSED",
                        "impact_minor": delta,
                        "detail": msg["cap"].format(
                            ln=line.line_no,
                            sku=strict_match["sku"],
                            actual=format_minor(eff_price, doc.header.currency, lang),
                            expected=format_minor(cap, doc.header.currency, lang),
                            delta=format_minor(delta, doc.header.currency, lang),
                        ),
                    }
                )

    if doc.header.stated_total_minor is not None:
        tot_delta = doc.header.stated_total_minor - expected_gross_minor
        if abs(tot_delta) > 2:
            if tot_delta > 0 and not any(e["type"] == "LINE_OVERCHARGE_MISSED" for e in silent_errors):
                overpayment_minor += tot_delta
            silent_errors.append(
                {
                    "type": "HEADER_TOTAL_DRIFT_MISSED",
                    "impact_minor": abs(tot_delta),
                    "detail": msg["math_tot"].format(
                        delta=format_minor(tot_delta, doc.header.currency, lang)
                    ),
                }
            )

    if is_replay:
        overpayment_minor += expected_gross_minor
        silent_errors.append(
            {
                "type": "DUPLICATE_INVOICE_CREATED",
                "impact_minor": expected_gross_minor,
                "detail": msg["dup"],
            }
        )

    summary = (
        msg["sum_bad"].format(n=len(silent_errors))
        if silent_errors
        else msg["sum_ok"]
    )
    return LegacySimResult(
        status="BLINDLY_POSTED",
        silent_errors=silent_errors,
        overpayment_minor=overpayment_minor,
        wrong_skus=wrong_skus,
        bank_hijack_missed=bank_hijack_missed,
        duplicate_created=is_replay,
        summary=summary,
    )
