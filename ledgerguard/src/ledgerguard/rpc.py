"""Line-delimited JSON-RPC bridge over stdin/stdout for low-latency Node.js integration."""

from __future__ import annotations

import base64
from collections import OrderedDict
import json
import sys
from typing import Any

from .benchmark import run_benchmark
from .engine import LedgerGuardEngine
from .fixtures import get_master_data, get_presets

MAX_SESSIONS = 32
_SESSIONS: OrderedDict[str, LedgerGuardEngine] = OrderedDict()
_BENCH_CACHE: dict[str, dict[str, Any]] = {}


def _get_engine(session_id: str, lang: str) -> LedgerGuardEngine:
    key = f"{session_id}:{lang}"
    if key in _SESSIONS:
        _SESSIONS.move_to_end(key)
        return _SESSIONS[key]
    eng = LedgerGuardEngine(lang=lang, db_path=":memory:")
    _SESSIONS[key] = eng
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.popitem(last=False)
    return eng


def _handle(method: str, params: dict[str, Any]) -> dict[str, Any]:
    lang = str(params.get("lang") or "ru").lower()
    if lang not in ("ru", "uk", "en", "fr"):
        lang = "ru"

    if method == "presets":
        vendors, catalog, contracts, _ = get_master_data(lang)
        if lang not in _BENCH_CACHE:
            _BENCH_CACHE[lang] = run_benchmark(lang)
        return {
            "presets": get_presets(lang),
            "vendor": vendors[0].__dict__ if hasattr(vendors[0], "__dict__") else {},
            "contract": {
                "contract_number": contracts[0].contract_number,
                "currency": contracts[0].currency,
                "valid_until": contracts[0].valid_until,
                "caps_count": len(contracts[0].price_caps_minor),
            },
            "benchmark": _BENCH_CACHE[lang],
        }

    if method == "reset_session":
        sid = str(params.get("sessionId") or "default")[:64]
        for l in ("ru", "uk", "en", "fr"):
            _SESSIONS.pop(f"{sid}:{l}", None)
        return {"reset": True}

    if method == "benchmark":
        return {"benchmark": run_benchmark(lang)}

    if method == "reconcile":
        sid = str(params.get("sessionId") or "default")[:64]
        engine = _get_engine(sid, lang)
        raw_text = params.get("rawText")
        file_name = str(params.get("fileName") or "inline.txt")[:128]
        b64 = params.get("fileBase64")
        file_bytes = base64.b64decode(b64) if b64 else None
        report = engine.process(
            raw_text=str(raw_text) if raw_text is not None else None,
            file_bytes=file_bytes,
            file_name=file_name,
            lang=lang,
        )
        if lang not in _BENCH_CACHE:
            _BENCH_CACHE[lang] = run_benchmark(lang)
        out = report.to_dict()
        out["benchmark"] = _BENCH_CACHE[lang]
        return out

    raise ValueError(f"Unknown RPC method: {method}")


def main() -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            result = _handle(str(req.get("method") or ""), req.get("params") or {})
            sys.stdout.write(json.dumps({"id": req_id, "ok": True, "result": result}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(
                json.dumps({"id": req_id, "ok": False, "error": str(exc)}, ensure_ascii=False) + "\n"
            )
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
