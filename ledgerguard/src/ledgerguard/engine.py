"""Core LedgerGuard deterministic procurement & invoice reconciliation engine."""

from __future__ import annotations

from decimal import Decimal
import re
import time
from typing import Any
import uuid

from .baseline import run_legacy_baseline
from .fixtures import get_master_data
from .matcher import CatalogMatcher
from .models import Discrepancy, LineVerdict, ReconciliationReport
from .money import compute_line_total_minor, format_minor, reconcile_vat_and_totals
from .parsers import parse_inbound_payload
from .storage import LedgerStorage
from .units import expand_pack_conversion
from .validators import validate_bank_account, validate_tax_id

_TEXTS = {
    "ru": {
        "dup": "Повторный документ (совпадает SHA-256 / номер счёта) заблокирован ключом идемпотентности.",
        "empty": "Не удалось распознать ни одной товарной строки — требуется проверка формата.",
        "tax_bad": "Контрольное число налогового ID ({id}) не сходится ({reason}).",
        "bank_bad": "Контрольный ключ/формат счёта ({acc}) некорректен ({reason}).",
        "bank_swap": "Подмена расчётного счёта! В документе указан {actual}, по реестру/договору утверждён {expected}.",
        "line_math": "Строка {ln}: сумма в документе ({actual}) ≠ «кол-во × цена» ({expected}).",
        "low_sku": "Строка {ln}: неоднозначное совпадение со справочником ({desc}, уверенность {conf:.0%}).",
        "cap": "Строка {ln} ({sku}): приведённая цена {actual} превышает потолок договора {expected}.",
        "tot_bad": "Итого счёта ({actual}) расходится с расчётной суммой строк ({expected}).",
        "vat_bad": "Сумма НДС ({actual}) не сходится с расчётной ({expected}).",
    },
    "uk": {
        "dup": "Повторний документ (збігається SHA-256 / номер рахунку) заблоковано ключем ідемпотентності.",
        "empty": "Не вдалося розпізнати жодного товарного рядка — потрібна ручна перевірка.",
        "tax_bad": "Контрольна сума податкового ID ({id}) не збігається ({reason}).",
        "bank_bad": "Контрольний ключ/формат рахунку ({acc}) некоректний ({reason}).",
        "bank_swap": "Підміна банківського рахунку! У документі {actual}, за реєстром/договором затверджено {expected}.",
        "line_math": "Рядок {ln}: сума в документі ({actual}) ≠ «к-сть × ціна» ({expected}).",
        "low_sku": "Рядок {ln}: неоднозначний збіг із довідником ({desc}, впевненість {conf:.0%}).",
        "cap": "Рядок {ln} ({sku}): приведена ціна {actual} перевищує ліміт договору {expected}.",
        "tot_bad": "Разом по рахунку ({actual}) розходиться з розрахунковою сумою ({expected}).",
        "vat_bad": "Сума ПДВ ({actual}) не збігається з розрахунковою ({expected}).",
    },
    "en": {
        "dup": "Re-submitted payload (matching SHA-256 / invoice number) blocked by SQLite idempotency key.",
        "empty": "Zero valid line items extracted — routed to human review.",
        "tax_bad": "Tax ID ({id}) failed statutory checksum ({reason}).",
        "bank_bad": "Bank account / IBAN ({acc}) failed checksum validation ({reason}).",
        "bank_swap": "Bank account hijack risk! Invoice lists {actual}, master contract requires {expected}.",
        "line_math": "Line {ln}: stated line total ({actual}) != exact qty × price ({expected}).",
        "low_sku": "Line {ln}: ambiguous or low-confidence SKU match ({desc}, {conf:.0%}).",
        "cap": "Line {ln} ({sku}): normalized unit price {actual} exceeds contract cap {expected}.",
        "tot_bad": "Invoice header total ({actual}) mismatches computed lines total ({expected}).",
        "vat_bad": "Stated VAT ({actual}) disagrees with computed VAT ({expected}).",
    },
    "fr": {
        "dup": "Doublon bloqué par la clé d'idempotence SQLite (SHA-256 / N° facture identique).",
        "empty": "Aucune ligne valide extraite — mise en file de contrôle.",
        "tax_bad": "Le numéro légal ({id}) a échoué au contrôle de clé ({reason}).",
        "bank_bad": "L'IBAN ({acc}) est invalide ({reason}).",
        "bank_swap": "Substitution de RIB détectée ! Facture : {actual}, contrat validé : {expected}.",
        "line_math": "Ligne {ln} : total affiché ({actual}) != quantité × prix ({expected}).",
        "low_sku": "Ligne {ln} : correspondance catalogue incertaine ({desc}, {conf:.0%}).",
        "cap": "Ligne {ln} ({sku}) : prix unitaire {actual} supérieur au plafond contrat {expected}.",
        "tot_bad": "Le total TTC ({actual}) diverge de la somme des lignes ({expected}).",
        "vat_bad": "La TVA déclarée ({actual}) diffère du calcul ({expected}).",
    },
}


class LedgerGuardEngine:
    """Deterministic verification & reconciliation pipeline guarding ERP writes."""

    def __init__(self, lang: str = "ru", db_path: str = ":memory:") -> None:
        self.lang = (lang or "ru").lower()
        self.storage = LedgerStorage(db_path)
        vendors, catalog, contracts, default_regime = get_master_data(self.lang)
        self.default_regime = default_regime
        self.storage.seed_master_data(vendors, catalog, contracts)
        self.catalog = self.storage.get_catalog()
        self.matcher = CatalogMatcher(self.catalog)

    def process(
        self,
        *,
        raw_text: str | None = None,
        file_bytes: bytes | None = None,
        file_name: str = "inline.txt",
        lang: str | None = None,
    ) -> ReconciliationReport:
        """Ingest, verify, compare Before vs After, persist atomically, and return full report."""
        t0 = time.perf_counter()
        ui_lang = (lang or self.lang).lower()
        txt = _TEXTS.get(ui_lang, _TEXTS["en"])

        doc = parse_inbound_payload(
            raw_text=raw_text,
            file_bytes=file_bytes,
            file_name=file_name,
            default_regime=self.default_regime,
        )

        batch_id = f"B-{uuid.uuid4().hex[:10].upper()}"
        idempotency_key = f"{doc.header.invoice_number}:{doc.sha256[:20]}"
        prior_batch = self.storage.find_batch_by_idempotency(idempotency_key)
        is_replay = prior_batch is not None

        vendor = self.storage.find_vendor(doc.header.tax_id)
        contract = self.storage.find_contract(
            doc.header.contract_number, vendor.vendor_id if vendor else None
        )

        discrepancies: list[Discrepancy] = []
        line_verdicts: list[LineVerdict] = []
        audit_events: list[tuple[str, dict[str, Any]]] = [
            (
                "DOC_INGESTED",
                {
                    "format": doc.source_format,
                    "invoice_number": doc.header.invoice_number,
                    "sha256": doc.sha256[:16],
                    "line_count": len(doc.lines),
                },
            )
        ]

        # 1. Line-by-line deterministic math, pack normalization, SKU match & contract caps
        computed_lines_sum_minor = 0
        direct_overcharge_minor = 0
        line_math_extra_minor = 0

        for line in doc.lines:
            exact_line_total = compute_line_total_minor(line.qty, line.unit_price_minor)
            computed_lines_sum_minor += exact_line_total

            pack = expand_pack_conversion(
                line.description, line.qty, line.unit, line.unit_price_minor
            )
            match = self.matcher.match(line.raw_code, line.description, naive_mode=False)

            cap_minor: int | None = None
            if contract and match["sku"] and match["sku"] in contract.price_caps_minor:
                cap_minor = contract.price_caps_minor[match["sku"]]

            line_issues: list[str] = []

            if line.stated_line_total_minor is not None and abs(
                line.stated_line_total_minor - exact_line_total
            ) > 2:
                delta = line.stated_line_total_minor - exact_line_total
                if delta > 0:
                    line_math_extra_minor += delta
                    direct_overcharge_minor += delta
                line_issues.append("LINE_MATH_MISMATCH")
                discrepancies.append(
                    Discrepancy(
                        code="LINE_MATH_MISMATCH",
                        severity="CRITICAL",
                        line_no=line.line_no,
                        field="line_total",
                        expected=format_minor(exact_line_total, doc.header.currency, ui_lang),
                        actual=format_minor(line.stated_line_total_minor, doc.header.currency, ui_lang),
                        financial_impact_minor=abs(delta),
                        message=txt["line_math"].format(
                            ln=line.line_no,
                            actual=format_minor(line.stated_line_total_minor, doc.header.currency, ui_lang),
                            expected=format_minor(exact_line_total, doc.header.currency, ui_lang),
                        ),
                    )
                )

            if not match["matched"] or match["ambiguous"]:
                line_issues.append("LOW_SKU_CONFIDENCE")
                discrepancies.append(
                    Discrepancy(
                        code="LOW_SKU_CONFIDENCE",
                        severity="HIGH",
                        line_no=line.line_no,
                        field="sku",
                        expected=match["sku"] or "—",
                        actual=line.description,
                        financial_impact_minor=0,
                        message=txt["low_sku"].format(
                            ln=line.line_no, desc=line.description, conf=match["confidence"]
                        ),
                    )
                )

            eff_unit_minor = int(pack["normalized_unit_minor"])
            if cap_minor is not None and eff_unit_minor > cap_minor:
                over_per_unit = eff_unit_minor - cap_minor
                norm_qty_dec = Decimal(str(pack["normalized_qty"]))
                over_total = int((Decimal(over_per_unit) * norm_qty_dec).to_integral_value())
                direct_overcharge_minor += over_total
                line_issues.append("PRICE_ABOVE_CONTRACT_CAP")
                discrepancies.append(
                    Discrepancy(
                        code="PRICE_ABOVE_CONTRACT_CAP",
                        severity="HIGH",
                        line_no=line.line_no,
                        field="unit_price",
                        expected=format_minor(cap_minor, doc.header.currency, ui_lang),
                        actual=format_minor(eff_unit_minor, doc.header.currency, ui_lang),
                        financial_impact_minor=over_total,
                        message=txt["cap"].format(
                            ln=line.line_no,
                            sku=match["sku"],
                            actual=format_minor(eff_unit_minor, doc.header.currency, ui_lang),
                            expected=format_minor(cap_minor, doc.header.currency, ui_lang),
                        ),
                    )
                )

            line_verdicts.append(
                LineVerdict(
                    line_no=line.line_no,
                    raw_description=line.description,
                    matched_sku=match["sku"],
                    matched_name=match["name"],
                    match_method=match["method"],
                    confidence=match["confidence"],
                    ambiguous=match["ambiguous"],
                    raw_qty=line.qty,
                    raw_unit=line.unit,
                    normalized_qty=str(pack["normalized_qty"]),
                    normalized_unit=str(pack["normalized_unit"]),
                    pack_note=str(pack["note"]) if pack["note"] else None,
                    unit_price_minor=line.unit_price_minor,
                    normalized_unit_minor=eff_unit_minor,
                    computed_line_total_minor=exact_line_total,
                    stated_line_total_minor=line.stated_line_total_minor,
                    contract_cap_minor=cap_minor,
                    issues=line_issues,
                )
            )

        if not doc.lines:
            discrepancies.append(
                Discrepancy(
                    code="NO_LINES_EXTRACTED",
                    severity="HIGH",
                    line_no=None,
                    field="lines",
                    expected=">= 1 line",
                    actual="0",
                    financial_impact_minor=0,
                    message=txt["empty"],
                )
            )

        # 2. Header total & VAT reconciliation
        totals = reconcile_vat_and_totals(
            computed_lines_sum_minor=computed_lines_sum_minor,
            stated_total_minor=doc.header.stated_total_minor,
            stated_vat_minor=doc.header.stated_vat_minor,
            vat_rate_pct=doc.header.vat_rate_pct,
            vat_mode=doc.header.vat_mode,
        )
        expected_gross_minor = int(totals["expected_gross_minor"] or 0)
        expected_vat_minor = int(totals["expected_vat_minor"] or 0)

        if not totals["total_ok"]:
            td = int(totals["total_delta_minor"] or 0)
            if td > 0 and line_math_extra_minor == 0:
                direct_overcharge_minor += td
            discrepancies.append(
                Discrepancy(
                    code="TOTAL_MISMATCH",
                    severity="CRITICAL",
                    line_no=None,
                    field="header_total",
                    expected=format_minor(expected_gross_minor, doc.header.currency, ui_lang),
                    actual=format_minor(doc.header.stated_total_minor, doc.header.currency, ui_lang),
                    financial_impact_minor=abs(td),
                    message=txt["tot_bad"].format(
                        actual=format_minor(doc.header.stated_total_minor, doc.header.currency, ui_lang),
                        expected=format_minor(expected_gross_minor, doc.header.currency, ui_lang),
                    ),
                )
            )

        if not totals["vat_ok"]:
            vd = int(totals["vat_delta_minor"] or 0)
            discrepancies.append(
                Discrepancy(
                    code="VAT_MISMATCH",
                    severity="MEDIUM",
                    line_no=None,
                    field="vat",
                    expected=format_minor(expected_vat_minor, doc.header.currency, ui_lang),
                    actual=format_minor(doc.header.stated_vat_minor, doc.header.currency, ui_lang),
                    financial_impact_minor=abs(vd),
                    message=txt["vat_bad"].format(
                        actual=format_minor(doc.header.stated_vat_minor, doc.header.currency, ui_lang),
                        expected=format_minor(expected_vat_minor, doc.header.currency, ui_lang),
                    ),
                )
            )

        # 3. Statutory tax-ID & bank checksums + master vendor registry account lock
        tax_res = (
            validate_tax_id(doc.header.tax_id, doc.header.regime)
            if doc.header.tax_id
            else {"valid": False, "normalized": "", "reason": "MISSING_TAX_ID"}
        )
        if not tax_res["valid"] and doc.header.tax_id:
            discrepancies.append(
                Discrepancy(
                    code="INVALID_TAX_CHECKSUM",
                    severity="CRITICAL",
                    line_no=None,
                    field="tax_id",
                    expected="valid checksum",
                    actual=doc.header.tax_id,
                    financial_impact_minor=0,
                    message=txt["tax_bad"].format(id=doc.header.tax_id, reason=tax_res["reason"]),
                )
            )

        bank_res = (
            validate_bank_account(doc.header.bank_account, doc.header.regime, doc.header.bik)
            if doc.header.bank_account
            else {"valid": True, "normalized": "", "reason": "NOT_PROVIDED"}
        )
        bank_matches_vendor = True
        if doc.header.bank_account and not bank_res["valid"]:
            discrepancies.append(
                Discrepancy(
                    code="INVALID_BANK_CHECKSUM",
                    severity="CRITICAL",
                    line_no=None,
                    field="bank_account",
                    expected="valid checksum",
                    actual=doc.header.bank_account,
                    financial_impact_minor=0,
                    message=txt["bank_bad"].format(acc=doc.header.bank_account, reason=bank_res["reason"]),
                )
            )
        elif vendor and doc.header.bank_account:
            norm_in = re.sub(r"\s+", "", doc.header.bank_account).upper()
            norm_reg = re.sub(r"\s+", "", vendor.approved_bank_account).upper()
            if norm_in != norm_reg:
                bank_matches_vendor = False
                discrepancies.append(
                    Discrepancy(
                        code="BANK_ACCOUNT_CHANGED",
                        severity="CRITICAL",
                        line_no=None,
                        field="bank_account",
                        expected=vendor.approved_bank_account,
                        actual=doc.header.bank_account,
                        financial_impact_minor=expected_gross_minor,
                        message=txt["bank_swap"].format(
                            actual=doc.header.bank_account, expected=vendor.approved_bank_account
                        ),
                    )
                )

        # 4. Run legacy 'Было' simulator before branching on duplicate or quarantine
        before_sim = run_legacy_baseline(
            doc=doc,
            catalog=self.catalog,
            vendor=vendor,
            contract=contract,
            is_replay=is_replay,
            computed_lines_sum_minor=computed_lines_sum_minor,
            expected_gross_minor=expected_gross_minor,
            lang=ui_lang,
        )

        # 5. Final verdict & idempotency enforcement
        prevented_loss_minor = direct_overcharge_minor
        if not bank_matches_vendor:
            prevented_loss_minor = max(prevented_loss_minor, expected_gross_minor)
        if is_replay:
            prevented_loss_minor += expected_gross_minor

        erp_payload: dict[str, Any] | None = None
        quarantine_ticket: dict[str, Any] | None = None

        if is_replay:
            status = "DUPLICATE_BLOCKED"
            dup_batch_id = prior_batch["batch_id"] if prior_batch else None
            discrepancies.insert(
                0,
                Discrepancy(
                    code="DUPLICATE_BLOCKED",
                    severity="HIGH",
                    line_no=None,
                    field="idempotency_key",
                    expected=f"unique key (existing: {dup_batch_id})",
                    actual=idempotency_key,
                    financial_impact_minor=expected_gross_minor,
                    message=txt["dup"],
                ),
            )
            audit_events.append(
                (
                    "DUPLICATE_BLOCKED",
                    {
                        "idempotency_key": idempotency_key,
                        "existing_batch_id": dup_batch_id,
                    },
                )
            )
        elif discrepancies:
            status = "QUARANTINED_FOR_REVIEW"
            dup_batch_id = None
            quarantine_ticket = {
                "ticket_id": f"QT-{batch_id[2:]}",
                "batch_id": batch_id,
                "invoice_number": doc.header.invoice_number,
                "vendor_name": doc.header.vendor_name or (vendor.name if vendor else ""),
                "status": status,
                "discrepancy_codes": [d.code for d in discrepancies],
                "prevented_loss_minor": prevented_loss_minor,
                "prevented_loss_formatted": format_minor(prevented_loss_minor, doc.header.currency, ui_lang),
                "action_required": "Human sign-off required before ERP posting",
            }
            audit_events.append(
                (
                    "QUARANTINED",
                    {
                        "ticket_id": quarantine_ticket["ticket_id"],
                        "codes": [d.code for d in discrepancies],
                        "prevented_loss_minor": prevented_loss_minor,
                    },
                )
            )
        else:
            status = "READY_FOR_ERP"
            dup_batch_id = None
            erp_payload = {
                "outbox_id": f"OUT-{batch_id[2:]}",
                "idempotency_key": idempotency_key,
                "target_erp": "1C / Odoo / Axelor REST",
                "vendor_id": vendor.vendor_id if vendor else None,
                "contract_number": contract.contract_number if contract else doc.header.contract_number,
                "currency": doc.header.currency,
                "gross_minor": expected_gross_minor,
                "vat_minor": expected_vat_minor,
                "lines": [
                    {
                        "sku": lv.matched_sku,
                        "qty": lv.normalized_qty,
                        "unit": lv.normalized_unit,
                        "unit_price_minor": lv.normalized_unit_minor,
                        "line_total_minor": lv.computed_line_total_minor,
                    }
                    for lv in line_verdicts
                ],
            }
            audit_events.append(
                (
                    "ERP_OUTBOX_QUEUED",
                    {
                        "outbox_id": erp_payload["outbox_id"],
                        "gross_minor": expected_gross_minor,
                        "lines": len(line_verdicts),
                    },
                )
            )

        self.storage.record_batch_and_decision(
            batch_id=batch_id,
            idempotency_key=idempotency_key,
            payload_sha256=doc.sha256,
            source_format=doc.source_format,
            invoice_number=doc.header.invoice_number,
            status=status,
            expected_gross_minor=expected_gross_minor,
            lines=[
                {
                    "line_no": lv.line_no,
                    "raw_description": lv.raw_description,
                    "matched_sku": lv.matched_sku,
                    "normalized_qty": lv.normalized_qty,
                    "normalized_unit": lv.normalized_unit,
                    "normalized_unit_minor": lv.normalized_unit_minor,
                    "computed_line_total_minor": lv.computed_line_total_minor,
                    "confidence": lv.confidence,
                }
                for lv in line_verdicts
            ],
            discrepancies=[
                {
                    "code": d.code,
                    "severity": d.severity,
                    "line_no": d.line_no,
                    "message": d.message,
                }
                for d in discrepancies
            ],
            prevented_loss_minor=prevented_loss_minor,
            erp_payload=erp_payload,
            quarantine_ticket=quarantine_ticket,
            audit_events=audit_events,
        )

        chain_check = self.storage.verify_audit_chain()
        recent_audit = self.storage.get_recent_audit_entries(limit=8)
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        return ReconciliationReport(
            batch_id=batch_id,
            status=status,
            idempotency_key=idempotency_key,
            duplicate_of_batch_id=dup_batch_id,
            currency=doc.header.currency,
            regime=doc.header.regime,
            source_format=doc.source_format,
            elapsed_ms=elapsed_ms,
            computed_lines_sum_minor=computed_lines_sum_minor,
            expected_gross_minor=expected_gross_minor,
            expected_vat_minor=expected_vat_minor,
            stated_total_minor=doc.header.stated_total_minor,
            prevented_loss_minor=prevented_loss_minor,
            tax_check={
                "tax_id": doc.header.tax_id,
                "checksum_valid": bool(tax_res["valid"]),
                "reason": tax_res["reason"],
                "vendor_matched": vendor.name if vendor else None,
            },
            bank_check={
                "bank_account": doc.header.bank_account,
                "checksum_valid": bool(bank_res["valid"]),
                "matches_approved_registry": bank_matches_vendor,
                "approved_account": vendor.approved_bank_account if vendor else None,
            },
            contract_check={
                "contract_number": doc.header.contract_number,
                "matched": contract.contract_number if contract else None,
            },
            lines=line_verdicts,
            discrepancies=discrepancies,
            before=before_sim,
            erp_payload=erp_payload,
            quarantine_ticket=quarantine_ticket,
            audit_trail=recent_audit,
            chain_verification=chain_check,
        )
