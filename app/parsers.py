"""Turns any input (CSV, Excel, PDF, pasted text, API rows) into a list of tables:
   {"sheet": str, "headers": [str], "rows": [[cell, ...]]}.  Everything downstream is source-agnostic."""
import csv
import io
import re
from datetime import datetime, date

import pandas as pd


def clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _table(sheet, grid, header_row=0):
    grid = [[clean(c) for c in r] for r in grid]
    if len(grid) <= header_row:
        return None
    seen, headers = {}, []
    for i, h in enumerate(grid[header_row]):
        h = str(h) if h is not None else f"Column {i + 1}"
        seen[h] = seen.get(h, 0) + 1
        headers.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
    rows = [r for r in grid[header_row + 1:] if any(c is not None for c in r)]
    return {"sheet": sheet, "headers": headers, "rows": rows}


def from_text(text, sheet="Pasted data", header_row=0):
    text = text.strip("\n")
    if "\t" in text:
        grid = list(csv.reader(io.StringIO(text), delimiter="\t"))
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;|")
        except csv.Error:
            dialect = csv.excel
        grid = list(csv.reader(io.StringIO(text), dialect))
    t = _table(sheet, grid, header_row)
    return [t] if t else []


def from_csv(content, header_row=0):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return from_text(text, "CSV", header_row)


def excel_sheets(content):
    return pd.ExcelFile(io.BytesIO(content)).sheet_names


def from_excel(content, header_row=0):
    book = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object)
    out = []
    for name, df in book.items():
        t = _table(str(name), df.values.tolist(), header_row)
        if t and t["headers"]:
            out.append(t)
    return out


def _ocr(content):
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as e:
        raise ValueError("OCR libraries are not installed") from e
    try:
        return "\n".join(pytesseract.image_to_string(img) for img in convert_from_bytes(content, dpi=200))
    except Exception as e:
        raise ValueError(f"OCR unavailable (tesseract/poppler missing?): {e}") from e


def from_pdf(content):
    import pdfplumber
    tables, texts = [], []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages):
            texts.append(page.extract_text() or "")
            for j, tb in enumerate(page.extract_tables()):
                t = _table(f"page {i + 1} table {j + 1}", tb)
                if t and t["rows"]:
                    tables.append(t)
    text = "\n".join(texts)
    if not text.strip() and not tables:          # scanned document -> OCR
        text = _ocr(content)
    if not tables and text.strip():              # fall back to whitespace-separated lines
        grid = [re.split(r"\t|\s{2,}|\|", ln.strip()) for ln in text.splitlines() if ln.strip()]
        grid = [r for r in grid if len(r) > 1]
        t = _table("extracted text", grid)
        if t:
            tables.append(t)
    return tables, text


def read_input(filename, content, text, header_row=0):
    """Returns (tables, source, extracted_text)."""
    if content is None:
        return from_text(text, header_row=header_row), "Paste", None
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xlsm", "xls"):
        return from_excel(content, header_row), "Excel", None
    if ext in ("csv", "txt", "tsv"):
        return from_csv(content, header_row), "CSV", None
    if ext == "pdf":
        tables, txt = from_pdf(content)
        return tables, "PDF", txt
    raise ValueError("Unsupported file type. Use .xlsx, .xls, .csv or .pdf")
