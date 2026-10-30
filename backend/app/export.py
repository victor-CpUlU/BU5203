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
from .sections import describe_forecast_ref, load_context, memo_positions, s3_positions
from .storage import AppError, Repo

MEMO_HEADER = "AI-generated draft reviewed by the analyst. Not a credit decision."
NAVY = colors.HexColor("#0f2d4e")
GOLD = colors.HexColor("#c79214")
GREY = colors.HexColor("#5a6676")
LINE = colors.HexColor("#d2d8e1")
STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=STYLES["BodyText"], fontSize=10, leading=14, spaceAfter=5)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#333333"))
STMT = ParagraphStyle("stmt", parent=BODY, fontSize=10, leading=14, spaceAfter=6, spaceBefore=0)
CAPTION = ParagraphStyle("caption", parent=BODY, fontSize=8, leading=11, textColor=GREY, spaceAfter=2)
REF = ParagraphStyle("ref", parent=BODY, fontSize=8.5, leading=12, textColor=colors.HexColor("#333333"), spaceAfter=3, leftIndent=10, firstLineIndent=-10)
H1 = ParagraphStyle("h1", parent=STYLES["Title"], textColor=NAVY, fontSize=22, spaceAfter=2)
H2 = ParagraphStyle("h2", parent=STYLES["Heading2"], textColor=NAVY, fontSize=13.5, spaceBefore=14, spaceAfter=6, borderWidth=0, borderPadding=0)
H3 = ParagraphStyle("h3", parent=STYLES["Heading3"], textColor=colors.HexColor("#2d6294"), fontSize=10.5, spaceBefore=8, spaceAfter=3)


def sanitise_borrower(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "_", name.strip())[:50] or "Borrower"


def file_name(borrower: str, kind: str, on: date | None = None) -> str:
    d = (on or date.today()).strftime("%Y%m%d")
    return f"{sanitise_borrower(borrower)}_CreditMemo_{d}.pdf" if kind == "memo" else f"{sanitise_borrower(borrower)}_CreditMemo_AuditTrail_{d}.pdf"


class CiteLedger:
    """Assigns a stable [n] marker to each distinct Evidence_ID the first time it is cited, so the memo
    body stays readable and all source detail is consolidated in one 'Sources and references' list."""

    def __init__(self, ctx: dict):
        self.ctx = ctx
        self.order: list[str] = []
        self.num: dict[str, int] = {}

    def mark(self, refs: list[str]) -> str:
        """Return a compact superscript-style marker group like ' [1][2]' for a statement's refs."""
        nums = []
        for r in refs:
            if r not in self.num:
                self.order.append(r)
                self.num[r] = len(self.order)
            nums.append(self.num[r])
        return "".join(f'<super><font size="7" color="#0f2d4e">[{n}]</font></super>' for n in nums)

    def entries(self) -> list[tuple[int, str, str]]:
        """(number, kind, full description) for every cited source, in first-citation order."""
        out = []
        for r in self.order:
            n = self.num[r]
            if r in self.ctx["evidence"]:
                e = self.ctx["evidence"][r]
                lp = e.get("located_page")
                desc = f"{e['doc_name']}, page {e['page']}" + (f" (found on physical page {lp})" if lp and lp != e["page"] else "")
                if e.get("section_heading"):
                    desc += f" ({e['section_heading']})"
                if e.get("excerpt"):
                    desc += f': \u201c{e["excerpt"]}\u201d'
                out.append((n, "Document", f"{r} \u2014 {desc}"))
            elif r in self.ctx["csv"]:
                e = self.ctx["csv"][r]
                desc = f"Financial database ({e['file_name']}{', cell ' + e['cell'] if e.get('cell') else ''}): {e['metric_label_as_written']}, {e['column_header']} = {e['display']}{' ' + e['unit_label'] if e.get('unit_label') else ''}"
                if e.get("flags"):
                    desc += f" [flags: {', '.join(e['flags'])}]"
                out.append((n, "Financial database", f"{r} \u2014 {desc}"))
            elif r in self.ctx["intake"]:
                e = self.ctx["intake"][r]
                out.append((n, "Deal intake", f"{r} \u2014 Deal intake: {e['label']} = {e['display']}"))
            elif r in self.ctx.get("forecast", {}):
                out.append((n, "Forecast", f"{r} \u2014 {describe_forecast_ref(self.ctx['forecast'][r])}"))
            else:
                out.append((n, "Unresolved", f"{r} \u2014 reference does not exist"))
        return out


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
    ledger = CiteLedger(ctx)
    borrower = deal["intake"]["DI-BORROWER"]["display"]
    i = deal["intake"]
    counts = {k: sum(1 for s in s5["statements"] if s["status"] == k) for k in ("Approved", "Flagged")}

    # ---- cover block -------------------------------------------------------
    story = [Paragraph(f"Credit Memorandum", H1),
             Paragraph(escape(borrower), ParagraphStyle("sub", parent=BODY, fontSize=13, textColor=GOLD, spaceAfter=10)),
             _summary_box([
                 ("Borrower", i["DI-BORROWER"]["display"]),
                 ("Facility type", i["DI-FACILITY_TYPE"]["display"]),
                 ("Amount requested", i["DI-AMOUNT"]["display"]),
                 ("Tenor", i["DI-TENOR"]["display"]),
                 ("Repayment", i["DI-REPAYMENT"]["display"]),
                 ("Purpose", i["DI-PURPOSE"]["display"]),
                 ("Reviewing analyst", name),
                 ("Review date", _review_date(repo.audit(deal_id))),
             ]),
             Spacer(1, 4),
             Paragraph(escape(f"Statements: {counts['Approved']} approved" + (f", {counts['Flagged']} flagged" if counts["Flagged"] else "")
                              + ". Figures are drawn from the financial database and cited documents; the AI performs no calculations."), CAPTION),
             Spacer(1, 8)]

    # ---- memo body ---------------------------------------------------------
    for number, title, subs in MEMO_OUTLINE:
        story.append(Paragraph(f"{number}.\u2003{escape(title)}", H2))
        story.append(_rule())
        wrote_any = False
        for key, sub_title in subs:
            sts = [s for s in s5["statements"] if s["section"] == number and s["subsection"] == key]
            if not sts:
                continue
            wrote_any = True
            story.append(Paragraph(escape(sub_title), H3))
            for s in sts:
                parts = []
                if s["status"] == "Flagged":
                    parts.append('<font color="#b00020"><b>\u26a0 FLAGGED</b></font> ')
                if s["label"] == "ASSUMPTION":
                    parts.append('<font color="#8a5a00"><b>[Assumption]</b></font> ')
                elif s["label"] == "NOT VERIFIED":
                    parts.append('<font color="#9c1c1c"><b>[Not verified]</b></font> ')
                parts.append(escape(s["text"]))
                parts.append(ledger.mark(s["refs"]))
                if s["status"] == "Flagged" and s.get("note"):
                    parts.append(f'<br/><font size="8" color="#b00020">Flag note: {escape(s["note"])}</font>')
                story.append(Paragraph("".join(parts), STMT))
        if not wrote_any:
            story.append(Paragraph("No content in this section.", CAPTION))

    # ---- consolidated sources ---------------------------------------------
    entries = ledger.entries()
    story.append(Paragraph("Sources and references", H2))
    story.append(_rule())
    if entries:
        story.append(Paragraph("Each [n] marker in the memo refers to the numbered source below.", CAPTION))
        for n, _kind, desc in entries:
            story.append(Paragraph(f'<b>[{n}]</b> {escape(desc)}', REF))
    else:
        story.append(Paragraph("No sources were cited in this memo.", CAPTION))

    path = repo.path(deal_id, "exports", file_name(borrower, "memo"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _build(path, story, MEMO_HEADER)
    return path


def _summary_box(rows: list[tuple[str, str]]) -> Table:
    data = [[Paragraph(f"<b>{escape(k)}</b>", SMALL), Paragraph(escape(str(v)), SMALL)] for k, v in rows]
    t = Table(data, colWidths=[42 * mm, 132 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBEFORE", (0, 0), (0, -1), 2, GOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _rule() -> Table:
    t = Table([[""]], colWidths=[174 * mm], rowHeights=[1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, GOLD), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


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
              Paragraph(escape(f"Financial database: {ctx['dataset']['file_name'] if ctx['dataset'] else 'not loaded'}"
                               + (f" (sheet {ctx['dataset']['sheet']}). {ctx['dataset'].get('calculation_note', '')}" if ctx["dataset"] and ctx["dataset"].get("sheet") else "")), BODY)]
    fs = ctx.get("forecast_state") or {}
    if fs.get("available"):
        st = fs["status"]
        state = (f"Saved by {st.get('saved_by')} at {st.get('saved_at')}" if st["state"] == "saved"
                 else "Historical-average defaults (not saved by the analyst)")
        story += [Paragraph("Forecast and scenario assumptions (backend model)", H2), Paragraph(escape(state), BODY),
                  _table([["Evidence ID", "Assumption", "Value", "Source"]] +
                         [[i, (e["scenario_label"] + ": " if e.get("scenario_label") else "") + e["label"], e["display"], e["source"]]
                          for i, e in fs["evidence"].items() if e["type"] in ("forecast_assumption", "forecast_threshold")],
                         [40 * mm, 60 * mm, 30 * mm, 44 * mm])]
    story.append(Paragraph("Section 3 financial analysis review", H2))
    approval = next((a for a in reversed(audit) if a.get("type") == "s3_approval"), None)
    story.append(Paragraph(escape(f"Approval: {approval['analyst_name']} at {approval['timestamp']}" if approval else "Approval: not recorded"), BODY))
    story.append(Paragraph("Each statement is named by its position (e.g. \"Section 3, Leverage panel, statement 2\"); "
                           "the short ID in brackets (S3-n) is the reference used in the audit entries.", CAPTION))
    s3pos = s3_positions(s3["statements"])
    for s in s3["statements"]:
        mark = s["verification"]["mark"]
        if s["verification"]["unmatched"]:
            mark += " (" + "; ".join(f"{u['value']}: {u['reason']}" for u in s["verification"]["unmatched"]) + ")"
        hist = _history(audit, s["id"], ("s3_review",))
        rows = [["Item", "Detail"],
                ["Statement", f"{s3pos[s['id']]['position']} ({s['id']})"],
                ["Text", s["text"]],
                ["Label / status / number check", f"{s['label']} / {s['status']} / {mark}"],
                ["Evidence", ", ".join(s["refs"]) or "No supporting reference"]]
        if s["text"] != s["original_text"]:
            rows.append(["AI original text", s["original_text"]])
        rows += [["Review", h] for h in hist] or [["Review", "No analyst action recorded"]]
        story += [_table(rows, [42 * mm, 132 * mm]), Spacer(1, 4)]
    story.append(Paragraph("Memo statements", H2))
    story.append(Paragraph("Each statement is named by its position in the memo: \"Section 1.3, statement 1\" is the first statement of "
                           "subsection 3 (Key strengths and risks) of Section 1 (Executive Summary). The short ID in brackets (M-n, "
                           "numbered through the whole memo) is the reference used in the audit entries.", CAPTION))
    mpos = memo_positions(s5["statements"])
    for s in s5["statements"]:
        p = mpos[s["id"]]
        rows = [["Item", "Detail"],
                ["Statement", f"{p['position']} ({s['id']})"],
                ["Location in memo", p["path"]],
                ["Text", s["text"]],
                ["Written by", "Backend (from the database / forecast), not the AI" if s.get("source") == "backend" else "AI, checked by the backend"],
                ["Label / status", f"{s['label']} / {'PENDING' if s['status'] == 'Pending' else s['status']}" + (f" ({s['note']})" if s.get("note") else "")],
                ["Number check", s["verification"]["mark"] + (" (" + "; ".join(f"{u['value']}: {u['reason']}" for u in s["verification"]["unmatched"]) + ")"
                                                              if s["verification"]["unmatched"] else "")]]
        if s["text"] != s["original_text"]:
            rows.append(["AI original text", s["original_text"]])
        rows += [["Review", h] for h in _history(audit, s["id"], ("memo_review", "memo_status"))] or [["Review", "No status change recorded"]]
        if not s["refs"]:
            rows.append(["Evidence", "No supporting reference"])
        for r in s["refs"]:
            if r in ctx["evidence"]:
                e = ctx["evidence"][r]
                lp = e.get("located_page")
                page_desc = f"page {e['page']}" + (f" (found on physical page {lp})" if lp and lp != e["page"] else "")
                rows.append([r, f"{e['doc_id']} {e['doc_name']}, {page_desc} ({e['location_status']}): \"{e['excerpt']}\""])
            elif r in ctx["csv"]:
                e = ctx["csv"][r]
                rows.append([r, f"{e['file_name']}{', cell ' + e['cell'] if e.get('cell') else ''}: {e['metric_label_as_written']}, "
                                f"{e['column_header']} = {e['display']}{' ' + e['unit_label'] if e.get('unit_label') else ''}"
                                + (f" | flags: {', '.join(e['flags'])}" if e["flags"] else "")])
            elif r in ctx["intake"]:
                rows.append([r, f"Deal intake: {ctx['intake'][r]['display']}"])
            elif r in ctx.get("forecast", {}):
                rows.append([r, describe_forecast_ref(ctx["forecast"][r])])
            else:
                rows.append([r, "Reference does not exist"])
        story += [_table(rows, [32 * mm, 142 * mm]), Spacer(1, 5)]
    path = repo.path(deal_id, "exports", file_name(borrower, "audit"))
    path.parent.mkdir(parents=True, exist_ok=True)
    _build(path, story, f"Audit Trail - {borrower}")
    return path


def _history(audit: list[dict], sid: str, types: tuple) -> list[str]:
    """Every recorded action on one statement, oldest first: who, when, what, and the change it made."""
    out = []
    for a in audit:
        if a.get("statement_id") != sid or a.get("type") not in types:
            continue
        who = a.get("analyst_name") or "System"
        action = a.get("action") or ("set by the system" if a.get("type") == "memo_status" else a.get("type"))
        line = f"{a['timestamp'][:19].replace('T', ' ')} | {who} | {action}"
        if a.get("status_before") or a.get("status_after"):
            line += f" | {a.get('status_before') or 'new'} -> {a.get('status_after') or a.get('status_before')}"
        if a.get("note"):
            line += f" | note: {a['note']}"
        if a.get("comment"):
            line += f" | comment: {a['comment']}"
        if a.get("text_after") and a.get("text_before") and a["text_after"] != a["text_before"]:
            line += f" | text changed from \"{a['text_before']}\" to \"{a['text_after']}\""
        out.append(line)
    return out


def repo_now() -> str:
    from .storage import now_iso
    return now_iso()
