"""Data models for LedgerGuard reconciliation pipelines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class RawInvoiceLine:
    """Normalized representation of a single parsed invoice/order row."""

    line_no: int
    raw_code: str
    description: str
    qty: str
    unit: str
    unit_price_minor: int
    stated_line_total_minor: int | None = None


@dataclass(slots=True)
class DocumentHeader:
    """Extracted document-level metadata and monetary header fields."""

    regime: str
    currency: str
    invoice_number: str
    invoice_date: str
    vendor_name: str
    tax_id: str
    bik: str
    bank_account: str
    contract_number: str
    vat_rate_pct: int
    vat_mode: str
    stated_total_minor: int | None = None
    stated_vat_minor: int | None = None


@dataclass(slots=True)
class InboundDocument:
    """Complete parsed procurement document ready for reconciliation."""

    sha256: str
    source_format: str
    file_name: str
    raw_preview: str
    header: DocumentHeader
    lines: list[RawInvoiceLine] = field(default_factory=list)


@dataclass(slots=True)
class CatalogItem:
    """Master catalog SKU definition with aliases and list price in minor units."""

    sku: str
    name: str
    unit: str
    list_price_minor: int
    aliases: list[str] = field(default_factory=list)
    brand: str = ""


@dataclass(slots=True)
class VendorRecord:
    """Approved vendor master record stored in SQLite."""

    vendor_id: str
    name: str
    regime: str
    tax_id: str
    bik: str
    approved_bank_account: str


@dataclass(slots=True)
class ContractTerms:
    """Active supplier contract and per-SKU unit-price ceilings."""

    contract_number: str
    vendor_id: str
    currency: str
    valid_from: str
    valid_until: str
    max_variance_pct: float
    price_caps_minor: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class Discrepancy:
    """Structured mismatch or policy violation detected during verification."""

    code: str
    severity: str
    line_no: int | None
    field: str
    expected: str
    actual: str
    financial_impact_minor: int
    message: str


@dataclass(slots=True)
class LineVerdict:
    """Per-line matching, packaging normalization, arithmetic, and cap audit."""

    line_no: int
    raw_description: str
    matched_sku: str | None
    matched_name: str | None
    match_method: str
    confidence: float
    ambiguous: bool
    raw_qty: str
    raw_unit: str
    normalized_qty: str
    normalized_unit: str
    pack_note: str | None
    unit_price_minor: int
    normalized_unit_minor: int
    computed_line_total_minor: int
    stated_line_total_minor: int | None
    contract_cap_minor: int | None
    issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LegacySimResult:
    """Measured outcome of the legacy single-prompt / manual import workflow."""

    status: str
    silent_errors: list[dict[str, Any]]
    overpayment_minor: int
    wrong_skus: int
    bank_hijack_missed: bool
    duplicate_created: bool
    summary: str


@dataclass(slots=True)
class AuditEntry:
    """Hash-chained ledger event entry."""

    seq: int
    ts: str
    batch_id: str
    event: str
    payload_json: str
    prev_hash: str
    entry_hash: str


@dataclass(slots=True)
class ReconciliationReport:
    """Full before-vs-after reconciliation result returned by LedgerGuardEngine."""

    batch_id: str
    status: str
    idempotency_key: str
    duplicate_of_batch_id: str | None
    currency: str
    regime: str
    source_format: str
    elapsed_ms: float
    computed_lines_sum_minor: int
    expected_gross_minor: int
    expected_vat_minor: int
    stated_total_minor: int | None
    prevented_loss_minor: int
    tax_check: dict[str, Any]
    bank_check: dict[str, Any]
    contract_check: dict[str, Any]
    lines: list[LineVerdict]
    discrepancies: list[Discrepancy]
    before: LegacySimResult
    erp_payload: dict[str, Any] | None
    quarantine_ticket: dict[str, Any] | None
    audit_trail: list[AuditEntry]
    chain_verification: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize report cleanly into plain JSON-compatible dictionaries."""
        return asdict(self)
