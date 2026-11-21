"""Integration tests generating real binary .xlsx, .docx, and .eml payloads and ingesting them."""

from email.message import EmailMessage
import io
import unittest
import zipfile

from ledgerguard.engine import LedgerGuardEngine
from ledgerguard.parsers import parse_inbound_payload


def _build_minimal_xlsx(rows: list[list[str]]) -> bytes:
    shared: list[str] = []
    shared_map: dict[str, int] = {}

    def intern(val: str) -> int:
        if val not in shared_map:
            shared_map[val] = len(shared)
            shared.append(val)
        return shared_map[val]

    row_xml_parts: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cells_xml: list[str] = []
        for c_idx, cell in enumerate(row):
            col_letter = chr(ord("A") + c_idx)
            s_id = intern(cell)
            cells_xml.append(f'<c r="{col_letter}{r_idx}" t="s"><v>{s_id}</v></c>')
        row_xml_parts.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')

    si_xml = "".join(f"<si><t>{_xml_esc(s)}</t></si>" for s in shared)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
        zf.writestr(
            "xl/sharedStrings.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{si_xml}</sst>',
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(row_xml_parts)}</sheetData></worksheet>",
        )
    return buf.getvalue()


def _build_minimal_docx(paragraphs: list[str], table_rows: list[list[str]]) -> bytes:
    p_xml = "".join(f"<w:p><w:r><w:t>{_xml_esc(p)}</w:t></w:r></w:p>" for p in paragraphs)
    tr_xml_list: list[str] = []
    for row in table_rows:
        tcs = "".join(f"<w:tc><w:p><w:r><w:t>{_xml_esc(c)}</w:t></w:r></w:p></w:tc>" for c in row)
        tr_xml_list.append(f"<w:tr>{tcs}</w:tr>")
    tbl_xml = f"<w:tbl>{''.join(tr_xml_list)}</w:tbl>"
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{p_xml}{tbl_xml}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def _xml_esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class TestBinaryParsers(unittest.TestCase):
    def test_xlsx_binary_ingestion_and_reconciliation(self) -> None:
        xlsx_bytes = _build_minimal_xlsx(
            [
                ["Поставщик: ООО «СеверЭнергоСнаб»"],
                ["Счёт № 901 от 2026-11-20 | Договор ДП-2026/11"],
                ["ИНН: 7707083893 | БИК: 044525225 | Р/С: 40702810438000124500"],
                ["№", "Наименование", "Кол-во", "Ед.", "Цена", "Сумма"],
                ["1", "ввгнг лс 3*2.5м (бухта 100м)", "2", "бухта", "11500.00", "23000.00"],
                ["2", "автомат abb s201 c16", "10", "шт", "450.00", "4500.00"],
                ["Итого к оплате: 27500.00 ₽"],
            ]
        )
        eng = LedgerGuardEngine(lang="ru")
        rep = eng.process(file_bytes=xlsx_bytes, file_name="invoice_901.xlsx")
        self.assertEqual(rep.source_format, "xlsx")
        self.assertEqual(rep.status, "READY_FOR_ERP")
        self.assertEqual(rep.expected_gross_minor, 2750000)
        self.assertEqual(rep.lines[0].normalized_qty, "200")
        self.assertEqual(rep.lines[0].normalized_unit, "m")

    def test_docx_binary_ingestion(self) -> None:
        docx_bytes = _build_minimal_docx(
            [
                "Постачальник: ТОВ «ЕлектроПром Постач»",
                "Рахунок № 902 від 2026-11-20 | Договір ДП-2026/44",
                "ЄДРПОУ: 38492011 | IBAN: UA213223130000026007233566001",
                "Разом до сплати: 15900.00 ₴",
            ],
            [
                ["№", "Найменування", "К-сть", "Од.", "Ціна", "Сума"],
                ["1", "Кабель ВВГнг-П 3х2,5", "300", "м", "53.00", "15900.00"],
            ],
        )
        eng = LedgerGuardEngine(lang="uk")
        rep = eng.process(file_bytes=docx_bytes, file_name="invoice_902.docx")
        self.assertEqual(rep.source_format, "docx")
        self.assertEqual(rep.status, "READY_FOR_ERP")
        self.assertTrue(rep.tax_check["checksum_valid"])
        self.assertTrue(rep.bank_check["matches_approved_registry"])

    def test_eml_with_csv_attachment_ingestion(self) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Invoice INV-777"
        msg["From"] = "billing@northgrid.example"
        msg.set_content(
            "Supplier: NorthGrid Electrical Supply Ltd\n"
            "Invoice #INV-777 Date 2026-11-20 | Contract MSA-2026-09\n"
            "VAT ID: GB849201472 | IBAN: GB29NWBK60161331926819\n"
            "Total Due: £178.00\n"
        )
        csv_body = "1;Schneider Acti9 iC60N C16 MCB 1P;20;pcs;8.90;178.00\n"
        msg.add_attachment(csv_body.encode("utf-8"), maintype="text", subtype="csv", filename="lines.csv")

        doc = parse_inbound_payload(file_bytes=msg.as_bytes(), file_name="order.eml", default_regime="EU")
        self.assertEqual(doc.source_format, "eml")
        self.assertEqual(len(doc.lines), 1)
        eng = LedgerGuardEngine(lang="en")
        rep = eng.process(file_bytes=msg.as_bytes(), file_name="order.eml")
        self.assertEqual(rep.status, "READY_FOR_ERP")


if __name__ == "__main__":
    unittest.main()
