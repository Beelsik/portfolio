"""Multi-format B2B document ingestion (.xlsx, .docx, .eml, .csv, delimited/free text)."""

from __future__ import annotations

import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile

from .models import DocumentHeader, InboundDocument, RawInvoiceLine
from .money import parse_money_to_minor

_XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_WML_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_inbound_payload(
    raw_text: str | None = None,
    file_bytes: bytes | None = None,
    file_name: str = "inline.txt",
    default_regime: str = "RU",
) -> InboundDocument:
    """Ingest raw text or binary file bytes (.xlsx, .docx, .eml, .csv) into InboundDocument."""
    fname = (file_name or "inline.txt").strip()
    lower = fname.lower()
    source_format = "text"
    normalized_text = ""

    if file_bytes:
        payload_hash = hashlib.sha256(file_bytes).hexdigest()
        if lower.endswith(".xlsx") or (
            file_bytes[:2] == b"PK" and _zip_has_member(file_bytes, "xl/workbook.xml")
        ):
            source_format = "xlsx"
            normalized_text = extract_text_from_xlsx(file_bytes)
        elif lower.endswith(".docx") or (
            file_bytes[:2] == b"PK" and _zip_has_member(file_bytes, "word/document.xml")
        ):
            source_format = "docx"
            normalized_text = extract_text_from_docx(file_bytes)
        elif lower.endswith(".eml") or b"Content-Type:" in file_bytes[:1024] or b"Subject:" in file_bytes[:1024]:
            source_format = "eml"
            normalized_text = extract_text_from_eml(file_bytes)
        else:
            source_format = "csv" if lower.endswith(".csv") else "text"
            normalized_text = _decode_bytes(file_bytes)
    else:
        normalized_text = str(raw_text or "").replace("\r\n", "\n")
        if "\t" in normalized_text and "|" not in normalized_text:
            source_format = "tsv"
        elif ";" in normalized_text and "|" not in normalized_text:
            source_format = "csv"
        canonical_bytes = normalized_text.strip().encode("utf-8")
        payload_hash = hashlib.sha256(canonical_bytes).hexdigest()

    return parse_text_document(
        normalized_text,
        sha256_hash=payload_hash,
        source_format=source_format,
        file_name=fname,
        default_regime=default_regime,
    )


def _decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(enc).replace("\r\n", "\n")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _zip_has_member(data: bytes, member: str) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return member in zf.namelist()
    except zipfile.BadZipFile:
        return False


def extract_text_from_xlsx(data: bytes) -> str:
    """Read an OOXML .xlsx workbook natively via zipfile + ElementTree (zero dependencies)."""
    rows_out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", _XLSX_NS):
                text_parts = [t.text or "" for t in si.findall(".//main:t", _XLSX_NS)]
                shared_strings.append("".join(text_parts))

        sheet_names = sorted(
            n for n in zf.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
        )
        if not sheet_names:
            return ""
        sheet_root = ET.fromstring(zf.read(sheet_names[0]))
        for row_el in sheet_root.findall(".//main:row", _XLSX_NS):
            cells_by_col: dict[int, str] = {}
            max_col = 0
            for c_el in row_el.findall("main:c", _XLSX_NS):
                ref = c_el.attrib.get("r", "")
                col_idx = _xlsx_col_to_index(ref) if ref else (max_col + 1)
                max_col = max(max_col, col_idx)
                cell_type = c_el.attrib.get("t", "")
                val = ""
                if cell_type == "s":
                    v_el = c_el.find("main:v", _XLSX_NS)
                    if v_el is not None and v_el.text is not None:
                        idx = int(v_el.text)
                        val = shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
                elif cell_type == "inlineStr":
                    val = "".join(t.text or "" for t in c_el.findall(".//main:t", _XLSX_NS))
                else:
                    v_el = c_el.find("main:v", _XLSX_NS)
                    if v_el is not None and v_el.text is not None:
                        val = v_el.text
                cells_by_col[col_idx] = val.strip()
            ordered = [cells_by_col.get(i, "") for i in range(1, max_col + 1)]
            if any(ordered):
                rows_out.append(" | ".join(ordered) if len([c for c in ordered if c]) >= 3 else " ".join(c for c in ordered if c))
    return "\n".join(rows_out)


def _xlsx_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(1, idx)


def extract_text_from_docx(data: bytes) -> str:
    """Read OOXML .docx paragraphs and structured tables natively via zipfile + ElementTree."""
    out_lines: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        root = ET.fromstring(zf.read("word/document.xml"))
        body = root.find("w:body", _WML_NS)
        if body is None:
            return ""
        for child in body:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                txt = "".join(t.text or "" for t in child.findall(".//w:t", _WML_NS)).strip()
                if txt:
                    out_lines.append(txt)
            elif tag == "tbl":
                for tr in child.findall("w:tr", _WML_NS):
                    cells: list[str] = []
                    for tc in tr.findall("w:tc", _WML_NS):
                        cell_txt = " ".join(
                            "".join(t.text or "" for t in p.findall(".//w:t", _WML_NS)).strip()
                            for p in tc.findall(".//w:p", _WML_NS)
                        ).strip()
                        cells.append(cell_txt)
                    if any(cells):
                        out_lines.append(" | ".join(cells))
    return "\n".join(out_lines)


def extract_text_from_eml(data: bytes) -> str:
    """Parse an RFC-5322 .eml message, extracting body headers + text/XLSX/DOCX/CSV attachments."""
    msg = BytesParser(policy=policy.default).parsebytes(data)
    sections: list[str] = []
    if msg["Subject"]:
        sections.append(f"# Email Subject: {msg['Subject']}")
    if msg["From"]:
        sections.append(f"# From: {msg['From']}")

    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = str(part.get_content_disposition() or "")
        fname = (part.get_filename() or "").lower()
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        if not payload:
            continue
        if fname.endswith(".xlsx"):
            sections.append(extract_text_from_xlsx(payload))
        elif fname.endswith(".docx"):
            sections.append(extract_text_from_docx(payload))
        elif ctype in ("text/plain", "text/csv") or disp == "attachment" and fname.endswith((".csv", ".txt")):
            sections.append(_decode_bytes(payload))
    return "\n".join(s for s in sections if s.strip())


def parse_text_document(
    raw_text: str,
    sha256_hash: str,
    source_format: str = "text",
    file_name: str = "inline.txt",
    default_regime: str = "RU",
) -> InboundDocument:
    """Parse normalized invoice/BOM text into DocumentHeader + RawInvoiceLines."""
    text = str(raw_text or "").replace("\r\n", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip() and not ln.strip().startswith("#")]

    regime = _detect_regime(text, default_regime)
    currency = _detect_currency(text, regime)
    tax_id_raw = _match_first(
        text,
        [
            r"(?:инн|інн|єдрпоу|edrpou|siret|vat(?:\s*id)?|tax\s*id)[ \t]*[:#№—-]?[ \t]*([A-Z]{0,2}[\d \t]{8,17}?)(?=\s*(?:\||;|$|\n))",
        ],
    )
    bank_raw = _match_first(
        text,
        [
            r"(?:iban)[ \t]*[:#—-]?[ \t]*([A-Z]{2}\d{2}[A-Z0-9 \t]{11,32}?)(?=\s*(?:\||;|$|\n))",
            r"\b([A-Z]{2}\d{2}[A-Z0-9]{11,30})\b",
            r"(?:р/с|р\.с\.|расч[её]тный[ \t]+сч[её]т|account)[ \t]*[:#№—-]?[ \t]*(\d{20})",
        ],
    )

    header = DocumentHeader(
        regime=regime,
        currency=currency,
        invoice_number=_match_first(
            text,
            [
                r"(?:сч[её]т(?:-фактура)?|рахунок(?:-фактура)?|invoice|facture|quote|devis)\s*(?:№|#|no\.?|n°)?\s*([A-Za-zА-Яа-яІіЇїЄєҐґ0-9/_-]{2,32})",
            ],
        )
        or "INV-UNSPECIFIED",
        invoice_date=_match_first(
            text,
            [
                r"(?:от|від|date|du)\s*(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})",
                r"\b(\d{4}-\d{2}-\d{2})\b",
            ],
        )
        or "2026-11-20",
        vendor_name=_match_first(
            text,
            [r"(?:поставщик|постачальник|контрагент|vendor|supplier|fournisseur)\s*[:—-]\s*([^\n|;]+)"],
        )
        or "",
        tax_id=re.sub(r"\s+", "", tax_id_raw or ""),
        bik=_match_first(text, [r"(?:бик|bik|мфо)\s*[:#—-]?\s*(\d{6,9})"]) or "",
        bank_account=re.sub(r"\s+", "", bank_raw or ""),
        contract_number=_match_first(
            text,
            [
                r"(?:договор|договір|contract|contrat|accord)\s*(?:№|#|no\.?|n°|:)?\s*([A-Za-zА-Яа-яІіЇїЄєҐґ0-9/_-]{3,32})",
            ],
        )
        or "",
        vat_rate_pct=_detect_vat_rate(text),
        vat_mode=_detect_vat_mode(text),
    )

    for ln in lines:
        tot_m = re.match(
            r"^(?:итого(?:\s+к\s+оплате)?|всего(?:\s+к\s+оплате)?|разом(?:\s+до\s+сплати)?|усього|total(?:\s+ttc|\s+due|\s+gross)?|montant\s+ttc)\s*[:—=-]\s*(.+)$",
            ln,
            flags=re.IGNORECASE,
        )
        if tot_m:
            val = parse_money_to_minor(tot_m.group(1))
            if val is not None:
                header.stated_total_minor = val
            continue
        vat_m = re.match(
            r"^(?:в\s*т\.?\s*ч\.?\s*(?:ндс|пдв)|у\s*т\.?\s*ч\.?\s*пдв|ндс|пдв|vat(?:\s+amount)?|dont\s+tva|tva)\s*(?:\(\d+%\)|\d+%)?\s*[:—=-]\s*(.+)$",
            ln,
            flags=re.IGNORECASE,
        )
        if vat_m:
            val = parse_money_to_minor(vat_m.group(1))
            if val is not None:
                header.stated_vat_minor = val

    parsed_lines: list[RawInvoiceLine] = []
    line_idx = 0
    for ln in lines:
        if _is_header_or_meta_line(ln):
            continue
        item = _parse_row(ln, line_idx + 1)
        if item is not None:
            parsed_lines.append(item)
            line_idx += 1

    return InboundDocument(
        sha256=sha256_hash,
        source_format=source_format,
        file_name=file_name,
        raw_preview=text[:600],
        header=header,
        lines=parsed_lines,
    )


def _parse_row(line: str, line_no: int) -> RawInvoiceLine | None:
    cells: list[str] | None = None
    if "|" in line:
        cells = [c.strip() for c in line.split("|")]
        while cells and cells[0] == "":
            cells.pop(0)
        while cells and cells[-1] == "":
            cells.pop()
    elif "\t" in line:
        cells = [c.strip() for c in line.split("\t")]
    elif line.count(";") >= 3:
        cells = next(csv.reader([line], delimiter=";"))
        cells = [c.strip() for c in cells]
    elif line.count(",") >= 4 and "«" not in line:
        cells = next(csv.reader([line], delimiter=","))
        cells = [c.strip() for c in cells]

    if cells and len(cells) >= 4:
        first_l = cells[0].lower()
        if re.fullmatch(
            r"(?:№|#|pos|line|код|артикул|sku|наименование|найменування|description|désignation)",
            first_l,
        ) and any(re.search(r"цена|ціна|price|prix|кол-во|кількість|qty|qté", c.lower()) for c in cells):
            return None

        cursor = 0
        raw_code = ""
        if re.fullmatch(r"\d{1,3}\.?", cells[0]) and len(cells) >= 5:
            cursor = 1
        if (
            len(cells) - cursor >= 5
            and re.fullmatch(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9._-]{3,20}", cells[cursor])
            and " " not in cells[cursor]
            and "-" in cells[cursor]
        ):
            raw_code = cells[cursor]
            cursor += 1

        desc = cells[cursor] if cursor < len(cells) else ""
        qty_cell = cells[cursor + 1] if cursor + 1 < len(cells) else ""
        qty_clean = re.sub(r"[^\d.,]", "", qty_cell).replace(",", ".")
        if not desc or not re.fullmatch(r"\d+(?:\.\d+)?", qty_clean) or float(qty_clean) <= 0:
            return None

        unit = "pcs"
        if len(cells) - cursor >= 5 and re.search(r"[a-zа-яіїєґ]", cells[cursor + 2], re.I) and not re.search(
            r"\d{2,}", cells[cursor + 2]
        ):
            unit = cells[cursor + 2]
            price_cell = cells[cursor + 3]
            total_cell = cells[cursor + 4] if cursor + 4 < len(cells) else None
        else:
            um = re.search(r"[a-zа-яіїєґ.]+$", qty_cell, re.I)
            if um:
                unit = um.group(0)
            price_cell = cells[cursor + 2]
            total_cell = cells[cursor + 3] if cursor + 3 < len(cells) else None

        unit_price_minor = parse_money_to_minor(price_cell)
        stated_total_minor = parse_money_to_minor(total_cell) if total_cell else None
        if unit_price_minor is None:
            return None

        return RawInvoiceLine(
            line_no=line_no,
            raw_code=raw_code,
            description=desc,
            qty=qty_clean,
            unit=unit,
            unit_price_minor=unit_price_minor,
            stated_line_total_minor=stated_total_minor,
        )

    free_m = re.match(
        r"^(?:\d+[.)]\s*)?(.+?)\s*[—–-]\s*(\d+(?:[.,]\d+)?)\s*([a-zа-яіїєґ.]{1,12})\s*(?:по|x|×|@)\s*([\d\s.,]+?)(?:\s*[₽₴€$£]?\s*=\s*([\d\s.,]+))?\s*[₽₴€$£]?$",
        line,
        re.IGNORECASE,
    )
    if free_m:
        qty_s = free_m.group(2).replace(",", ".")
        unit_price_minor = parse_money_to_minor(free_m.group(4))
        stated_total_minor = parse_money_to_minor(free_m.group(5)) if free_m.group(5) else None
        if float(qty_s) > 0 and unit_price_minor is not None:
            return RawInvoiceLine(
                line_no=line_no,
                raw_code="",
                description=free_m.group(1).strip(),
                qty=qty_s,
                unit=free_m.group(3).strip(),
                unit_price_minor=unit_price_minor,
                stated_line_total_minor=stated_total_minor,
            )

    return None


def _is_header_or_meta_line(ln: str) -> bool:
    if re.fullmatch(r"[-=+_]{4,}", ln):
        return True
    return bool(
        re.match(
            r"^(?:поставщик|постачальник|контрагент|vendor|supplier|fournisseur|покупатель|покупець|buyer|client|инн|інн|єдрпоу|edrpou|siret|vat|iban|р/с|бик|bik|мфо|договор|договір|contract|contrat|сч[её]т|рахунок|invoice|facture|итого|всего|разом|усього|total|montant|в\s*т\.?\s*ч\.?|у\s*т\.?\s*ч\.?|ндс|пдв|dont\s+tva|комментарий|примітка|note)\b",
            ln,
            re.IGNORECASE,
        )
    )


def _match_first(text: str, regexes: list[str]) -> str | None:
    for pat in regexes:
        m = re.search(pat, text, re.IGNORECASE)
        if m and m.group(1):
            return m.group(1).strip()
    return None


def _detect_regime(text: str, fallback: str = "RU") -> str:
    if re.search(r"єдрпоу|рахунок|постачальник|пдв|₴|грн|\bUA\d{2}\d{6}", text, re.I):
        return "UA"
    if re.search(r"siret|fournisseur|facture|tva|\bFR\d{2}", text, re.I):
        return "FR"
    if re.search(r"\bинн\b|\bбик\b|р/с|поставщик|\bндс\b|₽", text, re.I):
        return "RU"
    if re.search(r"vat\s*id|invoice|supplier|\bGB\d{2}|\bDE\d{2}|£|\$", text, re.I):
        return "EU"
    return str(fallback or "RU").upper()


def _default_currency(regime: str) -> str:
    r = regime.upper()
    if r == "UA":
        return "UAH"
    if r == "FR":
        return "EUR"
    if r == "EU":
        return "GBP"
    return "RUB"


def _detect_currency(text: str, regime: str) -> str:
    if re.search(r"₴|грн|\buah\b", text, re.I):
        return "UAH"
    if re.search(r"€|\beur\b", text, re.I):
        return "EUR"
    if re.search(r"£|\bgbp\b", text, re.I):
        return "GBP"
    if re.search(r"\$|\busd\b", text, re.I):
        return "USD"
    if re.search(r"₽|руб|\brub\b", text, re.I):
        return "RUB"
    return _default_currency(regime)


def _detect_vat_rate(text: str) -> int:
    if re.search(r"без\s+(?:ндс|пдв)|sans\s+tva|vat\s*0%|0%\s*vat", text, re.I):
        return 0
    m = re.search(r"(?:ндс|пдв|vat|tva)\s*[:—-]?\s*(\d{1,2})\s*%", text, re.I) or re.search(
        r"(\d{1,2})\s*%\s*(?:ндс|пдв|vat|tva)", text, re.I
    )
    return int(m.group(1)) if m else 20


def _detect_vat_mode(text: str) -> str:
    if re.search(r"без\s+(?:ндс|пдв)|sans\s+tva|vat\s*0%", text, re.I):
        return "none"
    if re.search(
        r"начисл(?:ить|яется)\s+сверху|плюс\s+(?:ндс|пдв)|нараховується\s+зверху|\+\s*(?:vat|tva)|ht\s*\+\s*tva|excl\.?\s*vat",
        text,
        re.I,
    ):
        return "added"
    return "included"
