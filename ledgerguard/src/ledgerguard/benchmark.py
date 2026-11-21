"""Reproducible 60-document Before-vs-After reconciliation benchmark."""

from __future__ import annotations

import statistics
from typing import Any

from .engine import LedgerGuardEngine
from .fixtures import get_presets
from .money import format_minor


def run_benchmark(lang: str = "ru") -> dict[str, Any]:
    """Run a deterministic 60-document corpus (36 messy clean + 24 adversarial) and measure accuracy/latency."""
    l = (lang or "ru").lower()
    presets = get_presets(l)
    clean_base = presets["clean_packs"]["text"]
    traps_base = presets["traps"]["text"]

    engine = LedgerGuardEngine(lang=l, db_path=":memory:")
    latencies: list[float] = []

    before_missed_docs = 0
    before_total_loss_minor = 0
    after_missed_docs = 0
    auto_passed_clean = 0
    quarantined_or_blocked = 0
    prevented_loss_minor = 0
    currency = "RUB"

    # 36 messy valid orders (different invoice numbers so each is unique)
    for i in range(1, 37):
        doc_text = _replace_invoice_num(clean_base, f"CLN-{1000 + i}")
        rep = engine.process(raw_text=doc_text, lang=l)
        currency = rep.currency
        latencies.append(rep.elapsed_ms)
        if rep.status == "READY_FOR_ERP":
            auto_passed_clean += 1

    # 24 adversarial documents across 4 fault classes:
    # - 18 unique traps invoices (swapped bank, over-contract price, line math drift, close gauge)
    # - 6 replay duplicates of previously submitted clean invoices
    for i in range(1, 19):
        doc_text = _replace_invoice_num(traps_base, f"ADV-{2000 + i}")
        rep = engine.process(raw_text=doc_text, lang=l)
        latencies.append(rep.elapsed_ms)
        if rep.before.silent_errors:
            before_missed_docs += 1
            before_total_loss_minor += rep.before.overpayment_minor + (
                rep.expected_gross_minor if rep.before.bank_hijack_missed else 0
            )
        if rep.status in ("QUARANTINED_FOR_REVIEW", "DUPLICATE_BLOCKED"):
            quarantined_or_blocked += 1
            prevented_loss_minor += rep.prevented_loss_minor
        else:
            after_missed_docs += 1

    for i in range(1, 7):
        replay_text = _replace_invoice_num(clean_base, f"CLN-{1000 + i}")
        rep = engine.process(raw_text=replay_text, lang=l)
        latencies.append(rep.elapsed_ms)
        if rep.before.silent_errors:
            before_missed_docs += 1
            before_total_loss_minor += rep.before.overpayment_minor
        if rep.status == "DUPLICATE_BLOCKED":
            quarantined_or_blocked += 1
            prevented_loss_minor += rep.prevented_loss_minor
        else:
            after_missed_docs += 1

    lat_sorted = sorted(latencies)
    p50 = round(statistics.median(lat_sorted), 2)
    p95 = round(lat_sorted[min(len(lat_sorted) - 1, int(len(lat_sorted) * 0.95))], 2)
    chain = engine.storage.verify_audit_chain()

    return {
        "total_docs": 60,
        "clean_docs": 36,
        "adversarial_docs": 24,
        "before_silent_error_docs": before_missed_docs,
        "before_silent_error_rate_pct": round((before_missed_docs / 60) * 100, 1),
        "after_silent_error_docs": after_missed_docs,
        "after_silent_error_rate_pct": round((after_missed_docs / 60) * 100, 1),
        "auto_passed_clean": auto_passed_clean,
        "clean_auto_pass_rate_pct": round((auto_passed_clean / 36) * 100, 1),
        "quarantined_or_blocked": quarantined_or_blocked,
        "prevented_loss_minor": prevented_loss_minor,
        "prevented_loss_formatted": format_minor(prevented_loss_minor, currency, l),
        "p50_ms": p50,
        "p95_ms": p95,
        "audit_chain_entries": chain["entries"],
        "audit_chain_valid": chain["valid"],
    }


def _replace_invoice_num(text: str, new_num: str) -> str:
    return (
        text.replace("№ 184", f"№ {new_num}")
        .replace("№ 185", f"№ {new_num}")
        .replace("#INV-184", f"#{new_num}")
        .replace("#INV-185", f"#{new_num}")
        .replace("N°FAC-184", f"N°{new_num}")
        .replace("N°FAC-185", f"N°{new_num}")
    )
