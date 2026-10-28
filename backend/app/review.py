"""Analyst review: Section 3 gate (Req 16) and Section 6 memo verification (Req 20, 22). Audit entry is written first."""
from __future__ import annotations

import base64

from . import documents as docs
from .sections import evidence_snapshot, load_context
from .storage import AppError, Repo, deal_lock, now_iso
from .verification import verify_statement


def valid_name(name: str | None) -> str:
    n = (name or "").strip()
    if not (1 <= len(n) <= 100):
        raise AppError(422, "analyst_name", "A valid analyst name (1 to 100 characters) is required.", fields=[{"field": "analyst_name", "reason": "required"}])
    return n


def valid_text(text: str | None, limit: int, field: str) -> str:
    t = (text or "").strip()
    if not (1 <= len(t) <= limit):
        raise AppError(422, "text_length", f"The {field} must be 1 to {limit:,} characters.", fields=[{"field": field, "reason": f"1-{limit} characters"}])
    return t


# --------------------------------------------------------------------------- Section 2 (evidence review)
def s2_action(repo: Repo, deal_id: str, ev_id: str, action: str, analyst: str | None, text: str | None = None) -> dict:
    """Approve or edit a Section 2 evidence item. Approving lets a memo statement that cites only
    approved EV- items carry over to Section 6 as 'Approved in Section 2'. Editing the statement
    re-locates the passage on the cited page and resets the item to Pending."""
    name = valid_name(analyst)
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        evidence = repo.read(deal_id, "evidence.json", {})
        e = evidence.get(ev_id)
        if e is None or e.get("type") != "document":
            raise AppError(404, "evidence_not_found", "Evidence item not found.")
        entry = {"type": "s2_review", "evidence_id": ev_id, "scope": e["scope"], "field": e["field"], "action": action,
                 "analyst_name": name, "status_before": e.get("status", "Pending"), "text_before": e["statement"]}
        if action == "approve":
            entry["status_after"] = "Approved"
            repo.append_audit(deal_id, entry)
            e["status"], e["note"] = "Approved", None
        elif action == "flag":
            note = (text or "").strip()
            if len(note) > 500:
                raise AppError(422, "text_length", "The flag note must be at most 500 characters.")
            entry.update({"status_after": "Flagged", "note": note})
            repo.append_audit(deal_id, entry)
            e["status"], e["note"] = "Flagged", note or "Flagged by analyst"
        elif action == "edit":
            new_text = valid_text(text, 2000, "edited statement")
            meta = next((d for d in deal["documents"] if d["doc_id"] == e["doc_id"]), None)
            pdf = repo.path(deal_id, "documents", f"{e['doc_id']}.pdf") if meta else None
            loc = docs.locate(pdf, e["page"], e["excerpt"], meta["page_count"] if meta else None)
            entry.update({"text_after": new_text, "status_after": "Pending", "location_status": loc["status"]})
            repo.append_audit(deal_id, entry)
            e.update({"statement": new_text, "status": "Pending", "note": None, "location_status": loc["status"], "rects": loc["rects"],
                      "located_page": loc["located_page"], "page_offset": loc.get("page_offset", 0),
                      "issues": [loc["issue"]] if loc["issue"] else [], "review_flag": loc["status"] != "Located"})
        else:
            raise AppError(422, "bad_action", "Unknown action (use approve, flag or edit).")
        repo.write(deal_id, "evidence.json", evidence)
    return {"evidence_id": ev_id, "status": e["status"], "statement": e["statement"], "location_status": e["location_status"],
            "issues": e["issues"], "note": e.get("note"), "original_statement": e.get("original_statement", e["statement"])}


def s2_bulk(repo: Repo, deal_id: str, action: str, analyst: str | None) -> dict:
    """Bulk-approve every Pending Section 2 evidence item; one audit entry per item (same record as a click)."""
    name = valid_name(analyst)
    if action != "approve_pending":
        raise AppError(422, "bad_action", "Unknown bulk action.")
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        evidence = repo.read(deal_id, "evidence.json", {})
        changed = 0
        for ev_id, e in evidence.items():
            if e.get("type") == "document" and e.get("status", "Pending") == "Pending":
                repo.append_audit(deal_id, {"type": "s2_review", "evidence_id": ev_id, "scope": e["scope"], "field": e["field"],
                                            "action": "approve (bulk: approve_pending)", "analyst_name": name,
                                            "status_before": "Pending", "status_after": "Approved", "text_before": e["statement"]})
                e["status"], e["note"] = "Approved", None
                changed += 1
        if changed:
            repo.write(deal_id, "evidence.json", evidence)
    return {"changed": changed}


# --------------------------------------------------------------------------- Section 3
def s3_action(repo: Repo, deal_id: str, sid: str, action: str, analyst: str | None, text: str | None = None) -> dict:
    name = valid_name(analyst)
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        s3 = repo.read(deal_id, "s3.json")
        if not s3:
            raise AppError(409, "precondition", "Run Section 3 first.")
        st = next((s for s in s3["statements"] if s["id"] == sid), None)
        if st is None:
            raise AppError(404, "statement_not_found", "Statement not found.")
        entry = {"type": "s3_review", "statement_id": sid, "panel": st["group"], "action": action, "analyst_name": name,
                 "status_before": st["status"], "text_before": st["text"]}
        if action in ("approve", "flag"):
            new_status = "Approved" if action == "approve" else "Flagged"
            entry["status_after"] = new_status
            repo.append_audit(deal_id, entry)
            st["status"] = new_status
        elif action == "comment":
            comment = valid_text(text, 2000, "comment")
            entry["comment"] = comment
            repo.append_audit(deal_id, entry)
            st["comments"].append({"text": comment, "analyst_name": name, "at": now_iso()})
        elif action == "edit":
            new_text = valid_text(text, 5000, "edited statement")
            ctx = load_context(repo, deal)
            verification = verify_statement({**st, "text": new_text}, ctx, "S3")
            entry.update({"text_after": new_text, "status_after": "Pending", "number_check": verification})
            repo.append_audit(deal_id, entry)
            st.update({"text": new_text, "status": "Pending", "verification": verification})
        else:
            raise AppError(422, "bad_action", "Unknown action.")
        if action != "comment" and s3.get("approved"):
            repo.append_audit(deal_id, {"type": "s3_approval_revoked", "analyst_name": name, "reason": f"{action} on {sid}"})
            s3["approved"], s3["approval"] = False, None
            deal["s3_approved"] = False
            Repo.mark_later_stale(deal, "s3")
            deal["s3_approved"] = False
            repo.save_deal(deal)
        repo.write(deal_id, "s3.json", s3)
        return s3


def s3_bulk(repo: Repo, deal_id: str, action: str, analyst: str | None) -> dict:
    """Bulk review of Pending statements; one audit entry per statement (same record as individual clicks).

    approve_verified: approve every Pending statement marked "Numbers verified".
    flag_mismatches:  flag every Pending statement marked "Number mismatch".
    """
    name = valid_name(analyst)
    if action not in ("approve_verified", "flag_mismatches"):
        raise AppError(422, "bad_action", "Unknown bulk action.")
    want_mark, new_status = ("Numbers verified", "Approved") if action == "approve_verified" else ("Number mismatch", "Flagged")
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        s3 = repo.read(deal_id, "s3.json")
        if not s3:
            raise AppError(409, "precondition", "Run Section 3 first.")
        changed = 0
        for st in s3["statements"]:
            if st["status"] == "Pending" and st["verification"]["mark"] == want_mark:
                repo.append_audit(deal_id, {"type": "s3_review", "statement_id": st["id"], "panel": st["group"],
                                            "action": f"{'approve' if new_status == 'Approved' else 'flag'} (bulk: {action})",
                                            "analyst_name": name, "status_before": "Pending", "status_after": new_status,
                                            "text_before": st["text"]})
                st["status"] = new_status
                changed += 1
        if changed and s3.get("approved"):
            repo.append_audit(deal_id, {"type": "s3_approval_revoked", "analyst_name": name, "reason": f"bulk {action}"})
            s3["approved"], s3["approval"] = False, None
            Repo.mark_later_stale(deal, "s3")
            deal["s3_approved"] = False
            repo.save_deal(deal)
        repo.write(deal_id, "s3.json", s3)
        return {"changed": changed, "s3": s3}


def approval_blockers(s3: dict) -> list[dict]:
    out = []
    for s in s3["statements"]:
        if s["status"] == "Pending":
            out.append({"statement_id": s["id"], "reason": "Still Pending: approve or flag it"})
        elif s["verification"]["mark"] == "Number mismatch" and s["status"] != "Flagged":
            out.append({"statement_id": s["id"], "reason": "Number mismatch: correct it or flag it"})
    return out


def s3_approve(repo: Repo, deal_id: str, analyst: str | None) -> dict:
    name = valid_name(analyst)
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        s3 = repo.read(deal_id, "s3.json")
        if not s3 or deal["sections"]["s3"]["status"] != "completed":
            raise AppError(409, "precondition", "Run Section 3 (and make sure it is up to date) before approving.")
        blockers = approval_blockers(s3)
        if blockers:
            raise AppError(409, "approval_blocked", f"{len(blockers)} statement(s) prevent approval.", details=blockers)
        repo.append_audit(deal_id, {"type": "s3_approval", "action": "approve financial analysis", "analyst_name": name})
        s3["approved"], s3["approval"] = True, {"analyst_name": name, "at": now_iso()}
        deal["s3_approved"] = True
        repo.write(deal_id, "s3.json", s3)
        repo.save_deal(deal)
        return s3


# --------------------------------------------------------------------------- Section 6
def memo_action(repo: Repo, deal_id: str, sid: str, action: str, analyst: str | None, text: str | None = None) -> dict:
    name = valid_name(analyst)
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        s5 = repo.read(deal_id, "s5.json")
        if not s5:
            raise AppError(409, "precondition", "Generate the memo first.")
        st = next((s for s in s5["statements"] if s["id"] == sid), None)
        if st is None:
            raise AppError(404, "statement_not_found", "Statement not found.")
        ctx = load_context(repo, deal)
        entry = {"type": "memo_review", "statement_id": sid, "action": action, "analyst_name": name, "status_before": st["status"],
                 "text_before": st["text"], "refs": st["refs"], "evidence_snapshot": evidence_snapshot(ctx, st["refs"])}
        if action == "approve":
            entry.update({"status_after": "Approved", "text_after": st["text"], "correction": ""})
            repo.append_audit(deal_id, entry)
            st.update({"status": "Approved", "note": st["note"] if st["status"] == "Approved" else None})
        elif action == "flag":
            note = (text or "").strip()
            if len(note) > 500:
                raise AppError(422, "text_length", "The flag note must be at most 500 characters.")
            entry.update({"status_after": "Flagged", "text_after": st["text"], "correction": "", "note": note})
            repo.append_audit(deal_id, entry)
            st.update({"status": "Flagged", "note": note or "Flagged by analyst", "carried_over": False})
        elif action == "correct":
            new_text = valid_text(text, 2000, "corrected statement")
            verification = verify_statement({**st, "text": new_text}, ctx, "S5")
            entry.update({"status_after": "Pending", "text_after": new_text, "correction": new_text})
            repo.append_audit(deal_id, entry)
            st.update({"text": new_text, "status": "Pending", "note": "Corrected by analyst; review again", "verification": verification, "carried_over": False})
        else:
            raise AppError(422, "bad_action", "Unknown action.")
        repo.write(deal_id, "s5.json", s5)
        return st


def memo_bulk(repo: Repo, deal_id: str, action: str, analyst: str | None) -> dict:
    """Bulk-approve every Pending memo statement; one audit entry per statement (same record as a click)."""
    name = valid_name(analyst)
    if action != "approve_pending":
        raise AppError(422, "bad_action", "Unknown bulk action.")
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        s5 = repo.read(deal_id, "s5.json")
        if not s5:
            raise AppError(409, "precondition", "Generate the memo first.")
        ctx = load_context(repo, deal)
        changed = 0
        for st in s5["statements"]:
            if st["status"] == "Pending":
                repo.append_audit(deal_id, {"type": "memo_review", "statement_id": st["id"], "action": "approve (bulk: approve_pending)",
                                            "analyst_name": name, "status_before": "Pending", "status_after": "Approved",
                                            "text_before": st["text"], "text_after": st["text"], "correction": "",
                                            "refs": st["refs"], "evidence_snapshot": evidence_snapshot(ctx, st["refs"])})
                st.update({"status": "Approved", "note": None})
                changed += 1
        if changed:
            repo.write(deal_id, "s5.json", s5)
    return {"changed": changed, "s5": s5}


def evidence_lookup(repo: Repo, deal_id: str, ev_id: str, statement_id: str | None) -> dict:
    deal = repo.get_deal(deal_id)
    ctx = load_context(repo, deal)
    if ev_id in ctx["csv"]:
        e = ctx["csv"][ev_id]
        return {"type": "csv", "evidence_id": ev_id, "file_name": e["file_name"], "metric_label": e["metric_label_as_written"],
                "column_header": e["column_header"], "period": e["period"], "display": e["display"],
                "flags": e["flags"] or ["None"]}
    if ev_id in ctx["intake"]:
        e = ctx["intake"][ev_id]
        return {"type": "deal_intake", "evidence_id": ev_id, "label": e["label"], "value": e["display"]}
    e = ctx["evidence"].get(ev_id)
    if e is None:
        raise AppError(404, "evidence_not_found", f"Evidence {ev_id} does not exist for this deal.")
    meta = next((d for d in deal["documents"] if d["doc_id"] == e["doc_id"]), None)
    pdf = repo.path(deal_id, "documents", f"{e['doc_id']}.pdf")
    result = {"type": "document", "evidence_id": ev_id, "doc_id": e["doc_id"], "doc_name": e["doc_name"], "page": e["page"],
              "section_heading": e["section_heading"], "excerpt": e["excerpt"], "statement": e["statement"], "issues": e["issues"]}
    if meta is None or not pdf.exists() or not (1 <= e["page"] <= meta["page_count"]):
        result.update({"location_status": "Source document unavailable", "image": None})
        _flag_on_activation(repo, deal_id, statement_id, ev_id, "Source document unavailable", always=True)
        return result
    loc = docs.locate(pdf, e["page"], e["excerpt"], meta["page_count"])
    # Render the physical page where the passage was actually found (may differ from the cited page
    # when the document has unnumbered front matter), so highlights align with the rendered image.
    render_page = loc["located_page"] or e["page"]
    png = docs.render_page_png(pdf, render_page, loc["rects"])
    result.update({"location_status": loc["status"], "image": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
                   "located_page": loc["located_page"], "page_offset": loc.get("page_offset", 0)})
    if loc["status"] != "Located":
        _flag_on_activation(repo, deal_id, statement_id, ev_id, "Source passage not located")
    else:
        _flag_on_activation(repo, deal_id, statement_id, ev_id, None)
    return result


def _flag_on_activation(repo: Repo, deal_id: str, statement_id: str | None, ev_id: str, note: str | None, always: bool = False) -> None:
    """Record activation; flag the citing statement the first time its source cannot be located (Req 20.5, 20.11)."""
    if not statement_id:
        return
    with deal_lock(deal_id):
        s5 = repo.read(deal_id, "s5.json")
        if not s5:
            return
        st = next((s for s in s5["statements"] if s["id"] == statement_id), None)
        if st is None or ev_id not in st["refs"]:
            return
        first = ev_id not in st["activated"]
        if first:
            st["activated"].append(ev_id)
        if note and (first or always) and st["status"] != "Flagged":
            repo.append_audit(deal_id, {"type": "memo_review", "statement_id": statement_id, "action": "auto-flag", "analyst_name": "System",
                                        "status_before": st["status"], "status_after": "Flagged", "note": note, "text_before": st["text"],
                                        "text_after": st["text"], "refs": st["refs"]})
            st["status"], st["note"] = "Flagged", note
        repo.write(deal_id, "s5.json", s5)
