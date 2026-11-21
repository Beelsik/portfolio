"""Command-line interface for LedgerGuard reconciliation and benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .benchmark import run_benchmark
from .engine import LedgerGuardEngine
from .fixtures import get_presets
from .storage import LedgerStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ledgerguard",
        description="Deterministic B2B invoice & BOM reconciliation gatekeeper before ERP/1C posting.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Reconcile a file or built-in preset against master registries.")
    p_run.add_argument("--file", help="Path to .xlsx, .docx, .eml, .csv, or .txt invoice.")
    p_run.add_argument("--preset", choices=["traps", "clean_packs"], default="traps")
    p_run.add_argument("--lang", choices=["ru", "uk", "en", "fr"], default="ru")
    p_run.add_argument("--db", default=":memory:", help="SQLite DB path (default: in-memory).")

    p_bench = sub.add_parser("benchmark", help="Run reproducible 60-doc Before-vs-After benchmark.")
    p_bench.add_argument("--lang", choices=["ru", "uk", "en", "fr"], default="ru")

    p_ver = sub.add_parser("verify-audit", help="Verify SHA-256 hash chain integrity of an audit DB.")
    p_ver.add_argument("--db", required=True, help="Path to SQLite ledger DB.")

    args = parser.parse_args(argv)

    if args.cmd == "benchmark":
        res = run_benchmark(lang=args.lang)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "verify-audit":
        st = LedgerStorage(args.db)
        res = st.verify_audit_chain()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("valid") else 2

    if args.cmd == "run":
        engine = LedgerGuardEngine(lang=args.lang, db_path=args.db)
        if args.file:
            p = Path(args.file)
            rep = engine.process(file_bytes=p.read_bytes(), file_name=p.name, lang=args.lang)
        else:
            preset = get_presets(args.lang)[args.preset]
            rep = engine.process(raw_text=preset["text"], file_name=f"{args.preset}.txt", lang=args.lang)
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
