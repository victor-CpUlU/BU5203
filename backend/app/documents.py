"""PDF processing with PyMuPDF: page text, Page_Tags, page selection, passage location, page images (Req 3, 4, 7, 20)."""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

QUOTES = {"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
          "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"'}
DASHES = {"\u2013": "-", "\u2014": "-"}


class PdfError(Exception):
    pass


# --------------------------------------------------------------------------- pages
def open_pdf(path: Path) -> fitz.Document:
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise PdfError("The file could not be opened as a PDF.") from exc
    if not doc.is_pdf:
        doc.close()
        raise PdfError("The file is not a PDF.")
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise PdfError("The PDF is password-protected.")
    if doc.page_count == 0:
        doc.close()
        raise PdfError("The PDF has no pages.")
    return doc


def extract_pages(path: Path) -> list[dict]:
    """Every physical page with its 1-based page number (Req 4.1)."""
    doc = open_pdf(path)
    try:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            pages.append({"page": i + 1, "text": text, "no_text_layer": not text.strip()})
        return pages
    finally:
        doc.close()


def page_tag(doc_id: str, doc_name: str, page: int) -> str:
    return f"[[DOC {doc_id} | {doc_name} | PAGE {page}]]"


def order_key(p: dict) -> tuple[int, int]:
    return int(p["doc_id"][1:]), p["page"]


def select_pages(pages: list[dict], keywords: list[str]) -> list[dict]:
    """Pages containing at least one keyword, case-insensitive (Req 4.3)."""
    kws = [k.lower() for k in keywords if k]
    out = [p for p in pages if not p.get("no_text_layer") and any(k in p["text"].lower() for k in kws)]
    return sorted(out, key=order_key)


def batch_pages(pages: list[dict], limit: int) -> list[list[dict]]:
    ordered = sorted(pages, key=order_key)
    return [ordered[i:i + limit] for i in range(0, len(ordered), limit)]


def render_batch(batch: list[dict]) -> str:
    return "\n\n".join(f"{page_tag(p['doc_id'], p['doc_name'], p['page'])}\n{p['text']}" for p in batch)


# --------------------------------------------------------------------------- normalisation
def normalise_with_map(s: str) -> tuple[str, list[int]]:
    """Req 7.5: (a) join hyphenated line breaks, (b) collapse whitespace and trim, (c) lower case,
    (d) straight quotes, (e) hyphen for en/em dashes. Returns text and source index per output char."""
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "-":
            j = i + 1
            while j < n and s[j] in " \t":
                j += 1
            if j < n and s[j] in "\r\n":
                j += 2 if s[j] == "\r" and j + 1 < n and s[j + 1] == "\n" else 1
                while j < n and s[j] in " \t":
                    j += 1
                i = j
                continue
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
            i += 1
            continue
        for c in ch.lower():
            c = QUOTES.get(c, DASHES.get(c, c))
            out.append(c)
            idx.append(i)
        i += 1
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normalise(s: str) -> str:
    return normalise_with_map(s)[0]


# --------------------------------------------------------------------------- passage locator
def _page_chars(page: fitz.Page) -> tuple[str, list[tuple | None], list[int]]:
    chars, rects, lines = [], [], []
    line_no = 0
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for c in span.get("chars", []):
                    chars.append(c["c"])
                    rects.append(tuple(c["bbox"]))
                    lines.append(line_no)
            chars.append("\n")
            rects.append(None)
            lines.append(line_no)
            line_no += 1
        chars.append(" ")
        rects.append(None)
        lines.append(line_no)
    return "".join(chars), rects, lines


def locate(pdf_path: Path | None, page_no: int, excerpt: str, page_count: int | None) -> dict:
    """Search only the cited page for the normalised excerpt (Req 7.2-7.5, 7.9)."""
    if pdf_path is None or not Path(pdf_path).exists():
        return {"status": "Not located", "rects": [], "issue": "Invalid reference: unknown document"}
    if page_count is not None and not (1 <= page_no <= page_count):
        return {"status": "Not located", "rects": [], "issue": "Invalid reference: page out of range"}
    needle = normalise(excerpt or "")
    if not needle:
        return {"status": "Not located", "rects": [], "issue": "Empty excerpt"}
    doc = open_pdf(Path(pdf_path))
    try:
        if not (1 <= page_no <= doc.page_count):
            return {"status": "Not located", "rects": [], "issue": "Invalid reference: page out of range"}
        text, rects, lines = _page_chars(doc[page_no - 1])
    finally:
        doc.close()
    hay, idx = normalise_with_map(text)
    pos = hay.find(needle)
    if pos < 0:
        return {"status": "Not located", "rects": [], "issue": "Not located"}
    by_line: dict[int, list[float]] = {}
    for k in range(pos, pos + len(needle)):
        src = idx[k]
        r = rects[src]
        if r is None:
            continue
        ln = lines[src]
        cur = by_line.get(ln)
        by_line[ln] = list(r) if cur is None else [min(cur[0], r[0]), min(cur[1], r[1]), max(cur[2], r[2]), max(cur[3], r[3])]
    return {"status": "Located", "rects": [by_line[k] for k in sorted(by_line)], "issue": None}


def render_page_png(pdf_path: Path, page_no: int, rects: list[list[float]], dpi: int = 150) -> bytes:
    """Render the page with highlights from an in-memory copy; the stored file is never modified."""
    doc = open_pdf(Path(pdf_path))
    try:
        page = doc[page_no - 1]
        for r in rects:
            annot = page.add_highlight_annot(fitz.Rect(r))
            annot.update()
        return page.get_pixmap(dpi=dpi, annots=True).tobytes("png")
    finally:
        doc.close()
