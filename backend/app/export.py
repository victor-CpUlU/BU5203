"""Credit Memo PDF and Audit Trail PDF with ReportLab (Req 23, 24)."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .schemas import MEMO_OUTLINE
from .sections import load_context
from .storage import AppError, Repo

MEMO_HEADER = "AI-generated draft reviewed by the analyst. Not a credit decision."
STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["BodyText"], fontSize=9.5, leading=13, spaceAfter=4)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#333333"))
H1, H2, H3 = STYLES["Title"], STYLES["Heading2"], STYLES["Heading3"]


def sanitise_borrower(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "_", name.strip())[:50] or "Borrower"


def file_name(borrower: str, kind: str, on: date | None = None) -> str:
    d = (on or date.today()).strftime("%Y%m%d")
    return f"{sanitise_borrower(borrower)}_CreditMemo_{d}.pdf" if kind == "memo" else f"{sanitise_borrower(borrower)}_CreditMemo_AuditTrail_{d}.pdf"


def citation(ref: str, ctx: dict) -> str:
    if ref in ctx["evidence"]:
        e = ctx["evidence"][ref]
        return f"[{e['doc_name']}, p.{e['page']}]"
    if ref in ctx["csv"]:
        e = ctx["csv"][ref]
        return f"[Financial database: {e['metric_label_as_written']}, {e['column_header']}]"
    if ref in ctx["intake"]:
        return f"[Deal intake: {ctx['intake'][ref]['label']}]"
    return f"[Unknown reference {ref}]"


def _build(path: Path, story: list, header: str) -> None:
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Oblique", 8)
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.drawString(18 * mm, A4[1] - 12 * mm, header)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    tmp = path.with_name(path.name + ".tmp")
    try:
        SimpleDocTemplate(str(tmp), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=16 * mm).build(
            story, onFirstPage=on_page, onLaterPages=on_page)
        os.replace(tmp, path)
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        raise AppError(500, "pdf_failed", "PDF generation failed. Nothing was changed.") from exc


def _review_date(audit: list[dict]) -> str:
    stamps = [a["timestamp"] for a in audit if a.get("type") in ("memo_review", "memo_status")]
    return (max(stamps) if stamps else audit[-1]["timestamp"] if audit else date.today().isoformat())[:10]


def memo_pdf(repo: Repo, deal_id: str, analyst: str) -> Path:
    deal = repo.get_deal(deal_id)
    s5 = repo.read(deal_id, "s5.json")
    if not s5:
        raise AppError(409, "precondition", "Generate the memo (Section 5) first.")
    pending = [s for s in s5["statements"] if s["status"] == "Pending"]
    if pending:
        raise AppError(409, "pending_statements", f"{len(pending)} statement(s) are still Pending. Approve or flag every statement first.")
    name = (analyst or "").strip()
    if not name:
        raise AppError(422, "analyst_name", "The analyst name is required to generate the final memo.")
    ctx = load_context(repo, deal)
    borrower = deal["intake"]["DI-BORROWER"]["display"]
    story = [Paragraph(f"Credit Memo: {escape(borrower)}", H1),
             Paragraph(escape(f"Facility: {deal['intake']['DI-FACILITY_TYPE']['display']} | Amount: {deal['intake']['DI-AMOUNT']['display']}"), BODY),
             Paragraph(escape(f"Analyst: {name} | Review date: {_review_date(repo.audit(deal_id))}"), BODY),
             Spacer(1, 6)]
    for number, title, subs in MEMO_OUTLINE:
        story.append(Paragraph(f"{number}. {escape(title)}", H2))
        for key, sub_title in subs:
            sts = [s for s in s5["statements"] if s["section"] == number and s["subsection"] == key]
            if not sts:
                continue
            story.append(Paragraph(escape(sub_title), H3))
            for s in sts:
                parts = []
                if s["status"] == "Flagged":
                    parts.append('<font color="#b00020"><b>FLAGGED</b></font>')
                if s["label"] in ("ASSUMPTION", "NOT VERIFIED"):
                    parts.append(f"<b>[{s['label']}]</b>")
                parts.append(escape(s["text"]))
                cites = " ".join(escape(citation(r, ctx)) for r in s["refs"])
                if cites:
                    parts.append(f'<font size="8" color="#1f4e79">{cites}</font>')
                parts.append(f"({s['id']})")
                if s["status"] == "Flagged" and s.get("note"):
                    parts.append(f'<font size="8" color="#b00020">Flag note: {escape(s["note"])}</font>')
                story.append(Paragraph(" ".join(parts), BODY))
    path = repo.path(deal_id, "exports", file_name(borrower, "memo"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _build(path, story, MEMO_HEADER)
    return path


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[Paragraph(escape(str(c)), SMALL) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def audit_pdf(repo: Repo, deal_id: str) -> Path:
    deal = repo.get_deal(deal_id)
    s5 = repo.read(deal_id, "s5.json")
    if not s5:
        raise AppError(409, "precondition", "Section 5 must be run first: no memo has been generated.")
    ctx = load_context(repo, deal)
    s3 = repo.read(deal_id, "s3.json") or {"statements": []}
    audit = repo.audit(deal_id)
    borrower = deal["intake"]["DI-BORROWER"]["display"]
    counts = {k: sum(1 for s in s5["statements"] if s["status"] == k) for k in ("Approved", "Flagged", "Pending")}
    story = [Paragraph(f"Audit Trail: {escape(borrower)}", H1),
             Paragraph(escape(f"Generated {repo_now()} | Statements: {len(s5['statements'])} | Approved {counts['Approved']}, "
                              f"Flagged {counts['Flagged']}, Pending {counts['Pending']}"), BODY)]
    if counts["Pending"]:
        story.append(Paragraph(f'<font color="#b00020"><b>Analyst review is incomplete: {counts["Pending"]} statement(s) are PENDING.</b></font>', BODY))
    story += [Paragraph("Deal summary", H2),
              _table([["Reference", "Field", "Value"]] + [[k, v["label"], v["display"]] for k, v in deal["intake"].items()], [32 * mm, 45 * mm, 97 * mm]),
              Paragraph("Documents", H2),
              _table([["doc_id", "Name", "Type", "Period", "Audited", "Pages"]] +
                     [[d["doc_id"], d["display_name"], d["doc_type"], d["period_covered"], "Yes" if d["audited"] else "No", d["page_count"]]
                      for d in deal["documents"]], [14 * mm, 62 * mm, 30 * mm, 26 * mm, 18 * mm, 14 * mm]),
              Paragraph(escape(f"Financial database: {ctx['dataset']['file_name'] if ctx['dataset'] else 'not loaded'}"), BODY),
              Paragraph("Section 3 financial analysis review", H2)]
    approval = next((a for a in reversed(audit) if a.get("type") == "s3_approval"), None)
    story.append(Paragraph(escape(f"Approval: {approval['analyst_name']} at {approval['timestamp']}" if approval else "Approval: not recorded"), BODY))
    for s in s3["statements"]:
        mark = s["verification"]["mark"]
        if s["verification"]["unmatched"]:
            mark += " (" + "; ".join(f"{u['value']}: {u['reason']}" for u in s["verification"]["unmatched"]) + ")"
        line = f"{s['id']} [{s['status']}] {s['text']} | {mark}"
        if s["text"] != s["original_text"]:
            line += f" | Original text: {s['original_text']}"
        story.append(Paragraph(escape(line), SMALL))
    story.append(Paragraph("Memo statements", H2))
    for s in s5["statements"]:
        last = next((a for a in reversed(audit) if a.get("statement_id") == s["id"] and a.get("type") in ("memo_review", "memo_status")), None)
        rows = [["Item", "Detail"], ["Statement", f"{s['id']} (section {s['section']}): {s['text']}"],
                ["Label / status", f"{s['label']} / {'PENDING' if s['status'] == 'Pending' else s['status']}" + (f" ({s['note']})" if s.get("note") else "")],
                ["Last status change", f"{last['analyst_name']} at {last['timestamp']}" if last else "None"]]
        for a in audit:
            if a.get("statement_id") == s["id"] and a.get("action") == "correct":
                rows.append(["Correction", f"{a['analyst_name']} at {a['timestamp']}: \"{a['text_before']}\" -> \"{a['text_after']}\""])
        if not s["refs"]:
            rows.append(["Evidence", "No supporting reference"])
        for r in s["refs"]:
            if r in ctx["evidence"]:
                e = ctx["evidence"][r]
                rows.append([r, f"{e['doc_id']} {e['doc_name']}, page {e['page']} ({e['location_status']}): \"{e['excerpt']}\""])
            elif r in ctx["csv"]:
                e = ctx["csv"][r]
                rows.append([r, f"{e['file_name']}: {e['metric_label_as_written']}, {e['column_header']} = {e['display']}"
                                + (f" | flags: {', '.join(e['flags'])}" if e["flags"] else "")])
            elif r in ctx["intake"]:
                rows.append([r, f"Deal intake: {ctx['intake'][r]['display']}"])
            else:
                rows.append([r, "Reference does not exist"])
        story += [_table(rows, [32 * mm, 142 * mm]), Spacer(1, 5)]
    path = repo.path(deal_id, "exports", file_name(borrower, "audit"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _build(path, story, f"Audit Trail - {borrower}")
    return path


def repo_now() -> str:
    from .storage import now_iso
    return now_iso()
