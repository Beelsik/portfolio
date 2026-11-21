# LedgerGuard (`ledgerguard`)

> **Deterministic B2B procurement & invoice reconciliation gatekeeper before posting to 1C, Odoo, Axelor, or any ERP.**  
> Built in zero-dependency **Python 3.12+** (`decimal.Decimal`, `sqlite3` WAL, `zipfile` + `ElementTree` OOXML, RFC-5322 `email`, `hashlib` SHA-256 chain).

## Why this project exists (The Problem)

Across mid-market wholesale, construction supply, solar/photovoltaic, and electrical distributors receiving 60–300 PDF/XLSX/email orders per day, teams run into two failure modes:

1. **Manual re-keying («Было №1»):** operators spend 12–15 minutes per multi-line bill typing SKUs into 1C/ERP and still miss look-alike cable gauges (`3x1.5` vs `3x2.5`) or unit pack mismatches (`3 coils` vs `3 m`).
2. **Naive 1-prompt LLM / n8n automation («Было №2»):** piping an invoice straight into GPT/Gemini and pushing JSON to ERP looks great in a demo, then silently loses money in production:
   - Floating-point rounding drift and unverified `qty × price != line_total` arithmetic overcharges;
   - **Vendor bank-account swap fraud**: an attacker replaces an IBAN or settlement account with another *checksum-valid* account — format validators pass it through;
   - **Contract price-cap drift**: unit price quietly bills `+8..15%` above the signed annex;
   - **Duplicate postings**: forwarded email retries create duplicate vendor bills in ERP with no audit trace.

**LedgerGuard** sits in front of your ERP REST API as a strict deterministic verification kernel. LLMs handle noisy OCR/free-text; **LedgerGuard** owns every number, tax checksum, bank lock, SKU parameter guard, idempotency lock, and cryptographic audit log.

---

## Measured Before → After (60-Document Corpus)

Reproducible via `PYTHONPATH=src python -m ledgerguard benchmark`:

| Metric | Before (Manual / 1-prompt n8n) | After (`LedgerGuard` Python 3.12) |
|---|---|---|
| Throughput per multi-line order | 12–15 min manual entry | **~6 ms** auto-pass (`<1 min` quarantine review) |
| Silent errors entering ERP (60-doc corpus) | **40.0%** (24 / 60 docs leaked) | **0.0%** (`0 / 60` leaked; 24 / 24 trapped) |
| Typo/coil-pack orders auto-posted cleanly | Manual intervention required | **100%** of valid noisy docs (`36 / 36`) |
| Duplicate postings on email retries | Duplicate bills created | **0 duplicates** (`SHA-256 + invoice_number` key) |
| Audit trail integrity | No structured lineage | **SHA-256 hash-chained SQLite `audit_log`** |

---

## Architecture & Safeguards

1. **Multi-Format Ingestion (`parsers.py`):** Native binary `.xlsx` (`xl/sharedStrings.xml` + sheet XML), `.docx` (paragraphs + `<w:tbl>`), RFC-5322 `.eml` with attachments, `.csv`/`.tsv`, and free text — zero `openpyxl`/`pandas` wheel bloat.
2. **Statutory Checksums (`validators.py`):**
   - **RU:** 10/12-digit INN + CBR 20-digit bank account / BIK control key;
   - **UA:** 8-digit EDRPOU weighted modulus-11 + ISO 13616 IBAN mod-97;
   - **FR:** 14-digit SIRET Luhn + FR IBAN mod-97;
   - **EU/UK:** VAT prefix/structure + IBAN mod-97.
   - Cross-checks invoice bank details against the approved `vendors.approved_bank_account` master record.
3. **Pack Expansion & Spec-Guarded SKU Matching (`units.py`, `matcher.py`):**
   - Expands `3 бухты по 100м` / `3 coils x 100m` / `3 couronnes 100m` → `300 m` and normalizes per-meter price;
   - Combines character 3-gram cosine similarity + token Jaccard with a **hard engineering penalty (`-0.48`)** on mismatched wire cross-section (`3x1.5` vs `3x2.5`), amperage (`C16` vs `C25`), or IP rating.
4. **Exact `Decimal` Money & VAT Check (`money.py`):** Computes every line and tax breakdown (`included`, `added`, `none`) strictly in integer minor units (kopeks / kopecks / cents / pence).
5. **SQLite WAL + Tamper-Evident Audit Chain (`storage.py`):**
   - Idempotent write to `erp_outbox` OR structured human-review ticket in `quarantine_queue`;
   - Every state transition appends to `audit_log` chained via `SHA-256(prev_hash | seq | batch_id | event | payload_json)` + built-in `verify-audit` command.

---

## Quickstart & Tests

```bash
cd ledgerguard

# Run full unit & binary (.xlsx / .docx / .eml) integration test suite
PYTHONPATH=src python -m unittest discover -s tests -v

# Reconcile built-in traps preset (RU / UK / EN / FR)
PYTHONPATH=src python -m ledgerguard run --preset traps --lang ru

# Reconcile a real local .xlsx / .docx / .eml / .csv file with persistent SQLite ledger
PYTHONPATH=src python -m ledgerguard run --file invoice.xlsx --db ledger.sqlite

# Verify tamper-evident SHA-256 audit log chain
PYTHONPATH=src python -m ledgerguard verify-audit --db ledger.sqlite

# Run 60-document Before-vs-After benchmark
PYTHONPATH=src python -m ledgerguard benchmark --lang en
```
