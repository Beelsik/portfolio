"""Hybrid deterministic SKU matcher with technical specification collision guards."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from .models import CatalogItem
from .units import extract_tech_signature


class CatalogMatcher:
    """Match noisy supplier/contractor text to canonical ERP SKUs safely."""

    def __init__(self, catalog: list[CatalogItem]) -> None:
        self._indexed: list[dict[str, Any]] = []
        for item in catalog:
            variants = [v for v in [item.name, *item.aliases] if v]
            # Extract technical specs only from human descriptions/aliases, never ASCII SKU IDs like 3X25
            tech_corpus = " ".join(variants)
            self._indexed.append(
                {
                    "item": item,
                    "norm_sku": _normalize_code(item.sku),
                    "norm_aliases": [_normalize_code(a) for a in item.aliases],
                    "variant_vectors": [(_build_trigrams(v), _build_tokens(v)) for v in variants],
                    "tech": extract_tech_signature(tech_corpus),
                }
            )

    def match(self, raw_code: str = "", description: str = "", naive_mode: bool = False) -> dict[str, Any]:
        """Match an inbound line. If naive_mode=True, skips spec guards (simulating Było)."""
        code_norm = _normalize_code(raw_code)
        if code_norm:
            for entry in self._indexed:
                if entry["norm_sku"] == code_norm or code_norm in entry["norm_aliases"]:
                    it: CatalogItem = entry["item"]
                    return {
                        "matched": True,
                        "sku": it.sku,
                        "name": it.name,
                        "unit": it.unit,
                        "list_price_minor": it.list_price_minor,
                        "confidence": 1.0,
                        "ambiguous": False,
                        "method": "EXACT_SKU",
                        "candidates": [{"sku": it.sku, "name": it.name, "score": 1.0}],
                    }

        cleaned_desc = _strip_pack_parenthetical(f"{raw_code} {description}".strip())
        q_tri = _build_trigrams(cleaned_desc)
        q_tok = _build_tokens(cleaned_desc)
        q_tech = extract_tech_signature(description or raw_code)

        scored: list[tuple[CatalogItem, float]] = []
        for entry in self._indexed:
            best_lex = 0.0
            for v_tri, v_tok in entry["variant_vectors"]:
                tri_sim = _cosine(q_tri, v_tri)
                tok_sim = _jaccard(q_tok, v_tok)
                lex = tri_sim * 0.65 + tok_sim * 0.35
                if lex > best_lex:
                    best_lex = lex

            score = best_lex
            if not naive_mode:
                it_tech = entry["tech"]
                for key in ("section", "amps", "ip", "diameter", "watts"):
                    qv = q_tech.get(key)
                    iv = it_tech.get(key)
                    if qv and iv:
                        score += 0.25 if qv == iv else -0.48

            clamped = round(max(0.0, min(0.99, score)), 3)
            scored.append((entry["item"], clamped))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        best_item, best_score = scored[0] if scored else (None, 0.0)
        runner_score = scored[1][1] if len(scored) > 1 else 0.0

        if best_item is None or (not naive_mode and best_score < 0.30):
            return {
                "matched": False,
                "sku": None,
                "name": None,
                "unit": None,
                "list_price_minor": None,
                "confidence": best_score,
                "ambiguous": True,
                "method": "UNMATCHED",
                "candidates": [{"sku": it.sku, "name": it.name, "score": sc} for it, sc in scored[:3]],
            }

        close_margin = (best_score - runner_score) < 0.08 if len(scored) > 1 else False
        low_conf = best_score < 0.58

        return {
            "matched": naive_mode or not low_conf,
            "sku": best_item.sku,
            "name": best_item.name,
            "unit": best_item.unit,
            "list_price_minor": best_item.list_price_minor,
            "confidence": best_score,
            "ambiguous": False if naive_mode else (low_conf or close_margin),
            "method": "NAIVE_OVERLAP" if naive_mode else "HYBRID_SPEC_GUARDED",
            "candidates": [{"sku": it.sku, "name": it.name, "score": sc} for it, sc in scored[:3]],
        }


def _normalize_code(s: str) -> str:
    return re.sub(r"[\s./_-]+", "", str(s or "").strip().upper())


def _strip_pack_parenthetical(s: str) -> str:
    return re.sub(
        r"\((?:бухта|уп|упак|coil|drum|pack|box|couronne|rouleau)[^)]*\)",
        " ",
        str(s or ""),
        flags=re.IGNORECASE,
    ).strip()


def _normalize_search_text(s: str) -> str:
    t = str(s or "").lower().replace("ё", "е")
    t = re.sub(r"(\d)\s*[*х×]\s*(\d)", r"\1x\2", t)
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    t = re.sub(r"[^a-zа-яіїєґ0-9.x]+", " ", t)
    return t.strip()


def _build_trigrams(text: str) -> Counter[str]:
    padded = f"  {_normalize_search_text(text)}  "
    if len(padded) < 3:
        return Counter({padded: 1})
    return Counter(padded[i : i + 3] for i in range(len(padded) - 2))


def _build_tokens(text: str) -> set[str]:
    return {w for w in _normalize_search_text(text).split() if len(w) >= 2}


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(va * b[k] for k, va in a.items() if k in b)
    if not dot:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)
