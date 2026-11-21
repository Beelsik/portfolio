"""SQLite persistence layer (WAL mode) with idempotency, quarantine queue, and SHA-256 hash-chained audit ledger."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3
from typing import Any

from .models import AuditEntry, CatalogItem, ContractTerms, VendorRecord

GENESIS_HASH = "0" * 64


class LedgerStorage:
    """Thread-safe SQLite repository backing master registries, outbox, quarantine, and audit log."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        if db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vendors (
                vendor_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                regime TEXT NOT NULL,
                tax_id TEXT NOT NULL,
                bik TEXT NOT NULL DEFAULT '',
                approved_bank_account TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS catalog_skus (
                sku TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                unit TEXT NOT NULL,
                list_price_minor INTEGER NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                brand TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS contracts (
                contract_number TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(vendor_id),
                currency TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_until TEXT NOT NULL,
                max_variance_pct REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS contract_prices (
                contract_number TEXT NOT NULL REFERENCES contracts(contract_number),
                sku TEXT NOT NULL REFERENCES catalog_skus(sku),
                cap_price_minor INTEGER NOT NULL,
                PRIMARY KEY (contract_number, sku)
            );

            CREATE TABLE IF NOT EXISTS inbound_batches (
                batch_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                payload_sha256 TEXT NOT NULL,
                source_format TEXT NOT NULL,
                invoice_number TEXT NOT NULL,
                status TEXT NOT NULL,
                expected_gross_minor INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reconciled_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL REFERENCES inbound_batches(batch_id),
                line_no INTEGER NOT NULL,
                raw_description TEXT NOT NULL,
                matched_sku TEXT,
                normalized_qty TEXT NOT NULL,
                normalized_unit TEXT NOT NULL,
                normalized_unit_minor INTEGER NOT NULL,
                computed_line_total_minor INTEGER NOT NULL,
                confidence REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quarantine_queue (
                ticket_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES inbound_batches(batch_id),
                discrepancy_count INTEGER NOT NULL,
                prevented_loss_minor INTEGER NOT NULL,
                discrepancies_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS erp_outbox (
                outbox_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES inbound_batches(batch_id),
                idempotency_key TEXT UNIQUE NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                event TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def seed_master_data(
        self,
        vendors: list[VendorRecord],
        catalog: list[CatalogItem],
        contracts: list[ContractTerms],
    ) -> None:
        """Populate master catalog, approved vendors, and contract price caps idempotently."""
        with self.conn:
            for v in vendors:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO vendors(vendor_id, name, regime, tax_id, bik, approved_bank_account)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (v.vendor_id, v.name, v.regime, v.tax_id, v.bik, v.approved_bank_account),
                )
            for item in catalog:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO catalog_skus(sku, name, unit, list_price_minor, aliases_json, brand)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.sku,
                        item.name,
                        item.unit,
                        item.list_price_minor,
                        json.dumps(item.aliases, ensure_ascii=False),
                        item.brand,
                    ),
                )
            for c in contracts:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO contracts(contract_number, vendor_id, currency, valid_from, valid_until, max_variance_pct)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (c.contract_number, c.vendor_id, c.currency, c.valid_from, c.valid_until, c.max_variance_pct),
                )
                for sku, cap in c.price_caps_minor.items():
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO contract_prices(contract_number, sku, cap_price_minor)
                        VALUES (?, ?, ?)
                        """,
                        (c.contract_number, sku, cap),
                    )

    def get_catalog(self) -> list[CatalogItem]:
        rows = self.conn.execute("SELECT sku, name, unit, list_price_minor, aliases_json, brand FROM catalog_skus").fetchall()
        return [
            CatalogItem(
                sku=r["sku"],
                name=r["name"],
                unit=r["unit"],
                list_price_minor=r["list_price_minor"],
                aliases=json.loads(r["aliases_json"]),
                brand=r["brand"],
            )
            for r in rows
        ]

    def find_vendor(self, tax_id: str) -> VendorRecord | None:
        if not tax_id:
            return None
        r = self.conn.execute(
            "SELECT vendor_id, name, regime, tax_id, bik, approved_bank_account FROM vendors WHERE tax_id = ?",
            (tax_id,),
        ).fetchone()
        if r is None:
            return None
        return VendorRecord(**dict(r))

    def find_contract(self, contract_number: str, vendor_id: str | None = None) -> ContractTerms | None:
        row = None
        if contract_number:
            row = self.conn.execute(
                "SELECT * FROM contracts WHERE UPPER(contract_number) = UPPER(?)",
                (contract_number,),
            ).fetchone()
        if row is None and vendor_id:
            row = self.conn.execute(
                "SELECT * FROM contracts WHERE vendor_id = ? LIMIT 1",
                (vendor_id,),
            ).fetchone()
        if row is None:
            return None
        caps_rows = self.conn.execute(
            "SELECT sku, cap_price_minor FROM contract_prices WHERE contract_number = ?",
            (row["contract_number"],),
        ).fetchall()
        return ContractTerms(
            contract_number=row["contract_number"],
            vendor_id=row["vendor_id"],
            currency=row["currency"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            max_variance_pct=row["max_variance_pct"],
            price_caps_minor={cr["sku"]: cr["cap_price_minor"] for cr in caps_rows},
        )

    def find_batch_by_idempotency(self, idempotency_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM inbound_batches WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()

    def record_batch_and_decision(
        self,
        *,
        batch_id: str,
        idempotency_key: str,
        payload_sha256: str,
        source_format: str,
        invoice_number: str,
        status: str,
        expected_gross_minor: int,
        lines: list[dict[str, Any]],
        discrepancies: list[dict[str, Any]],
        prevented_loss_minor: int,
        erp_payload: dict[str, Any] | None,
        quarantine_ticket: dict[str, Any] | None,
        audit_events: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Persist batch, line verdicts, ERP outbox OR quarantine ticket, and chained audit events atomically."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conn:
            if status != "DUPLICATE_BLOCKED":
                self.conn.execute(
                    """
                    INSERT INTO inbound_batches(
                        batch_id, idempotency_key, payload_sha256, source_format,
                        invoice_number, status, expected_gross_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        idempotency_key,
                        payload_sha256,
                        source_format,
                        invoice_number,
                        status,
                        expected_gross_minor,
                        now,
                    ),
                )
                for ln in lines:
                    self.conn.execute(
                        """
                        INSERT INTO reconciled_lines(
                            batch_id, line_no, raw_description, matched_sku,
                            normalized_qty, normalized_unit, normalized_unit_minor,
                            computed_line_total_minor, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch_id,
                            ln["line_no"],
                            ln["raw_description"],
                            ln["matched_sku"],
                            ln["normalized_qty"],
                            ln["normalized_unit"],
                            ln["normalized_unit_minor"],
                            ln["computed_line_total_minor"],
                            ln["confidence"],
                        ),
                    )
                if erp_payload is not None:
                    self.conn.execute(
                        """
                        INSERT INTO erp_outbox(outbox_id, batch_id, idempotency_key, payload_json, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            erp_payload["outbox_id"],
                            batch_id,
                            idempotency_key,
                            json.dumps(erp_payload, ensure_ascii=False),
                            now,
                        ),
                    )
                if quarantine_ticket is not None:
                    self.conn.execute(
                        """
                        INSERT INTO quarantine_queue(
                            ticket_id, batch_id, discrepancy_count,
                            prevented_loss_minor, discrepancies_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            quarantine_ticket["ticket_id"],
                            batch_id,
                            len(discrepancies),
                            prevented_loss_minor,
                            json.dumps(discrepancies, ensure_ascii=False),
                            now,
                        ),
                    )

            for event_name, payload in audit_events:
                self._append_audit_locked(batch_id, event_name, payload, now)

    def _append_audit_locked(
        self, batch_id: str, event: str, payload: dict[str, Any], ts: str
    ) -> AuditEntry:
        last = self.conn.execute(
            "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = last["entry_hash"] if last else GENESIS_HASH
        next_seq = (last["seq"] + 1) if last else 1
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest_input = f"{prev_hash}|{next_seq}|{batch_id}|{event}|{payload_json}".encode("utf-8")
        entry_hash = hashlib.sha256(digest_input).hexdigest()
        self.conn.execute(
            """
            INSERT INTO audit_log(seq, ts, batch_id, event, payload_json, prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (next_seq, ts, batch_id, event, payload_json, prev_hash, entry_hash),
        )
        return AuditEntry(
            seq=next_seq,
            ts=ts,
            batch_id=batch_id,
            event=event,
            payload_json=payload_json,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

    def get_recent_audit_entries(self, limit: int = 12) -> list[AuditEntry]:
        rows = self.conn.execute(
            "SELECT seq, ts, batch_id, event, payload_json, prev_hash, entry_hash FROM audit_log ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [AuditEntry(**dict(r)) for r in reversed(rows)]

    def verify_audit_chain(self) -> dict[str, Any]:
        """Recompute every SHA-256 hash link in audit_log from genesis to prove zero tampering."""
        rows = self.conn.execute(
            "SELECT seq, batch_id, event, payload_json, prev_hash, entry_hash FROM audit_log ORDER BY seq ASC"
        ).fetchall()
        expected_prev = GENESIS_HASH
        for r in rows:
            if r["prev_hash"] != expected_prev:
                return {
                    "valid": False,
                    "entries": len(rows),
                    "broken_at_seq": r["seq"],
                    "reason": "PREV_HASH_MISMATCH",
                }
            digest_input = f"{expected_prev}|{r['seq']}|{r['batch_id']}|{r['event']}|{r['payload_json']}".encode(
                "utf-8"
            )
            recomputed = hashlib.sha256(digest_input).hexdigest()
            if recomputed != r["entry_hash"]:
                return {
                    "valid": False,
                    "entries": len(rows),
                    "broken_at_seq": r["seq"],
                    "reason": "ENTRY_HASH_TAMPERED",
                }
            expected_prev = recomputed
        return {
            "valid": True,
            "entries": len(rows),
            "broken_at_seq": None,
            "head_hash": expected_prev,
        }
