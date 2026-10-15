"""REST API (all routes under /api)."""
from __future__ import annotations

import re
import shutil
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import documents as docs
from . import export, lifecycle, review, sections
from .financial import LoadError, build_dashboard, load_csv
from .settings import get_settings
from .storage import AppError, Repo, deal_lock, now_iso

router = APIRouter(prefix="/api")
NOTICE = "Local prototype: no authentication. Do not deploy to a shared environment without adding access control."
DOC_TYPES = ["Annual Report", "10-K", "10-Q", "Audited Financial Statements", "Other"]
INTAKE_FIELDS = [  # (reference, request key, label, max length, required)
    ("DI-BORROWER", "borrower", "Borrower / company name", 200, True),
    ("DI-FACILITY_TYPE", "facility_type", "Facility type", 100, True),
    ("DI-AMOUNT", "amount", "Requested amount", None, True),
    ("DI-PURPOSE", "purpose", "Purpose of loan", 2000, True),
    ("DI-TENOR", "tenor", "Tenor", 100, True),
    ("DI-REPAYMENT", "repayment", "Repayment structure", 2000, True),
    ("DI-COLLATERAL", "collateral", "Collateral / security", 2000, False),
]


def repo() -> Repo:
    return Repo()


def prompts(request: Request):
    return request.app.state.prompts


# --------------------------------------------------------------------------- system
@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/heartbeat")
def heartbeat():
    lifecycle.heartbeat()
    return {"ok": True}


@router.post("/closing")
def closing():
    lifecycle.closing()
    return {"ok": True}


@router.post("/shutdown")
def shutdown():
    lifecycle.request_shutdown()
    return {"ok": True, "message": "The app is closing."}


@router.get("/status")
def status():
    s = get_settings()
    problems = s.llm_settings_problems()
    return {"provider": s.llm_provider or None, "model": s.llm_model or None, "llm_configured": not problems,
            "missing_settings": problems, "support_check_enabled": s.support_check_enabled, "notice": NOTICE,
            "doc_types": DOC_TYPES, "default_csv": s.financial_db_path.name, "thresholds_defaulted": s.defaults_applied}


# --------------------------------------------------------------------------- deals
class IntakeRequest(BaseModel):
    borrower: str | None = None
    facility_type: str | None = None
    amount: str | None = None
    currency: str | None = None
    purpose: str | None = None
    tenor: str | None = None
    repayment: str | None = None
    collateral: str | None = None


def validate_intake(req: IntakeRequest) -> dict:
    data = {k: (v or "").strip() for k, v in req.model_dump().items()}
    errors = []
    for ref, key, label, limit, required in INTAKE_FIELDS:
        v = data[key]
        if required and not v:
            errors.append({"field": key, "reason": f"{label} is required"})
        elif limit and len(v) > limit:
            errors.append({"field": key, "reason": f"{label} must be at most {limit:,} characters"})
    amt = data["amount"].replace(",", "")
    if data["amount"]:
        ok = bool(re.fullmatch(r"\d+(\.\d{1,2})?", amt))
        if ok:
            try:
                ok = Decimal("0.01") <= Decimal(amt) <= Decimal("999999999999.99")
            except InvalidOperation:
                ok = False
        if not ok:
            errors.append({"field": "amount", "reason": "Requested amount must be a number from 0.01 to 999,999,999,999.99 with at most 2 decimals"})
    if not re.fullmatch(r"[A-Za-z]{3}", data["currency"]):
        errors.append({"field": "currency", "reason": "Currency must be a 3-letter code, e.g. USD"})
    if errors:
        raise AppError(422, "invalid_intake", "Please correct the highlighted fields.", fields=errors)
    intake = {}
    for ref, key, label, _, _ in INTAKE_FIELDS:
        if key == "amount":
            cur = data["currency"].upper()
            intake[ref] = {"label": label, "amount": amt, "currency": cur, "display": f"{amt} {cur}"}
        elif key == "collateral":
            intake[ref] = {"label": label, "display": data[key] or "None provided"}
        else:
            intake[ref] = {"label": label, "display": data[key]}
    for v in intake.values():
        v["value"] = v["display"]
    return intake


def auto_connect_financial(r: Repo, deal_id: str) -> None:
    """Simulate an automatic connection to the external financial database (default CSV).

    Runs at deal creation. No analyst action and no confirmation prompt: a file with no
    Borrower column is treated as belonging to this deal's borrower (confirm=True), which the
    loader records as the information gap "Database has no borrower identifier". A missing or
    malformed database file does not block deal creation; the deal keeps financial.status="error"
    and the message is surfaced in Section 2.
    """
    s = get_settings()
    deal = r.get_deal(deal_id)
    try:
        res = load_csv(s.financial_db_path, deal["intake"]["DI-BORROWER"]["display"], True, s.large_swing, s.stable_band)
    except LoadError as exc:
        with deal_lock(deal_id):
            deal = r.get_deal(deal_id)
            deal["financial"].update({"status": "error", "source": None, "file_name": s.financial_db_path.name,
                                      "error": str(exc), "loaded_at": now_iso()})
            r.save_deal(deal)
            r.append_audit(deal_id, {"type": "financial_connect_failed", "analyst_name": "System",
                                     "file_name": s.financial_db_path.name, "error": str(exc)})
        return
    ds = res["dataset"]
    with deal_lock(deal_id):
        r.append_audit(deal_id, {"type": "financial_connected", "analyst_name": "System", "file_name": ds["file_name"],
                                 "values": len(res["evidence"])})
        r.write(deal_id, "financial/dataset.json", ds)
        r.write(deal_id, "financial/csv_evidence.json", res["evidence"])
        deal = r.get_deal(deal_id)
        deal["financial"].update({"status": "connected", "confirmed": True, "source": None,
                                  "file_name": ds["file_name"], "error": None, "loaded_at": now_iso()})
        r.save_deal(deal)


@router.post("/deals")
def create_deal(req: IntakeRequest):
    r = repo()
    deal = r.create_deal(validate_intake(req))
    r.append_audit(deal["deal_id"], {"type": "deal_created", "analyst_name": "System", "intake": {k: v["display"] for k, v in deal["intake"].items()}})
    auto_connect_financial(r, deal["deal_id"])
    return r.get_deal(deal["deal_id"])


@router.get("/deals")
def list_deals():
    return repo().list_deals()


@router.get("/deals/{deal_id}")
def get_deal(deal_id: str):
    r = repo()
    deal = r.get_deal(deal_id)
    s5 = r.read(deal_id, "s5.json")
    deal["memo_counts"] = {k: sum(1 for s in s5["statements"] if s["status"] == k) for k in ("Approved", "Flagged", "Pending")} if s5 else None
    return deal


@router.put("/deals/{deal_id}")
def update_deal(deal_id: str, req: IntakeRequest):
    """Edit the loan request (deal intake). If the borrower changes, the external financial database is
    re-connected for the new borrower; any completed later sections are marked out of date so the analyst
    re-runs them against the edited request."""
    r = repo()
    new_intake = validate_intake(req)
    with deal_lock(deal_id):
        deal = r.get_deal(deal_id)
        old_intake = deal["intake"]
        changed = [ref for ref in new_intake if old_intake.get(ref, {}).get("display") != new_intake[ref]["display"]]
        borrower_changed = old_intake.get("DI-BORROWER", {}).get("display") != new_intake["DI-BORROWER"]["display"]
        deal["intake"] = new_intake
        r.append_audit(deal_id, {"type": "deal_edited", "analyst_name": "System",
                                 "changed_fields": changed,
                                 "intake": {k: v["display"] for k, v in new_intake.items()}})
        # Editing the request can invalidate downstream analysis that quoted the old DI- values.
        if changed:
            Repo.mark_later_stale(deal, "s2a")  # from Section 3 onward
        r.save_deal(deal)
    if borrower_changed:
        # Re-fetch the financial database for the new borrower (overwrites the connected dataset).
        auto_connect_financial(r, deal_id)
    return r.get_deal(deal_id)


@router.delete("/deals/{deal_id}")
def delete_deal(deal_id: str):
    """Delete the deal and all of its stored data (documents, evidence, section outputs, audit trail, exports)."""
    r = repo()
    r.get_deal(deal_id)  # 404 if it does not exist
    with deal_lock(deal_id):
        r.delete_tree(r.deal_dir(deal_id))
    return {"deleted": True, "deal_id": deal_id}


# --------------------------------------------------------------------------- documents
@router.post("/deals/{deal_id}/documents")
def upload_document(deal_id: str, file: UploadFile = File(...), doc_type: str = Form(...), period_covered: str = Form(...),
                    audited: str = Form(...), display_name: str | None = Form(None)):
    r, s = repo(), get_settings()
    r.get_deal(deal_id)
    errors = []
    if doc_type not in DOC_TYPES:
        errors.append({"field": "doc_type", "reason": "Choose a document type"})
    if not (1 <= len(period_covered.strip()) <= 50):
        errors.append({"field": "period_covered", "reason": "Period covered must be 1 to 50 characters"})
    if audited not in ("Yes", "No"):
        errors.append({"field": "audited", "reason": "Choose Yes or No"})
    if errors:
        raise AppError(422, "invalid_upload", "Please correct the highlighted fields.", fields=errors)
    limit = int(s.max_upload_mb * 1024 * 1024)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        size = 0
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                break
            tmp.write(chunk)
        tmp_path = Path(tmp.name)
    try:
        if size > limit:
            raise AppError(413, "too_large", f"The file is larger than the {s.max_upload_mb:g} MB limit.")
        try:
            pages = docs.extract_pages(tmp_path)
        except docs.PdfError as exc:
            raise AppError(422, "invalid_pdf", f"Only readable PDF files are accepted. {exc}") from exc
        with deal_lock(deal_id):
            deal = r.get_deal(deal_id)
            doc_id = f"D{deal['next_doc_seq']}"
            deal["next_doc_seq"] += 1
            dest = r.path(deal_id, "documents", f"{doc_id}.pdf")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_path), dest)
            r.write(deal_id, f"pages/{doc_id}.json", pages)
            no_text = [p["page"] for p in pages if p["no_text_layer"]]
            name = (display_name or "").strip() or (file.filename or doc_id)
            meta = {"doc_id": doc_id, "display_name": name[:255], "file_name": file.filename, "doc_type": doc_type,
                    "period_covered": period_covered.strip(), "audited": audited == "Yes", "page_count": len(pages),
                    "no_text_pages": no_text, "extraction_excluded": len(no_text) == len(pages), "failed": False, "uploaded_at": now_iso()}
            deal["documents"].append(meta)
            r.save_deal(deal)
            r.append_audit(deal_id, {"type": "document_uploaded", "analyst_name": "System", "doc_id": doc_id, "display_name": meta["display_name"]})
        warnings = []
        if no_text:
            warnings.append(f"{doc_id}: pages with no text layer: {', '.join(map(str, no_text[:50]))}{' ...' if len(no_text) > 50 else ''}")
        if meta["extraction_excluded"]:
            warnings.append(f"{doc_id} has no extractable text and is excluded from extraction.")
        return {"document": meta, "warnings": warnings}
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/deals/{deal_id}/documents")
def list_documents(deal_id: str):
    return repo().get_deal(deal_id)["documents"]


# --------------------------------------------------------------------------- financial database
@router.get("/deals/{deal_id}/financial")
def get_financial(deal_id: str):
    ds = repo().read(deal_id, "financial/dataset.json")
    if not ds:
        raise AppError(404, "no_dataset", "The financial database is not connected for this deal.")
    return ds


@router.get("/deals/{deal_id}/dashboard")
def dashboard(deal_id: str):
    ds = repo().read(deal_id, "financial/dataset.json")
    if not ds:
        raise AppError(404, "no_dataset", "The financial database is not connected for this deal.")
    return build_dashboard(ds)


# --------------------------------------------------------------------------- sections
class ScopesRequest(BaseModel):
    scopes: list[str] = ["business", "debt"]


@router.post("/deals/{deal_id}/section2/run")
def run_s2(deal_id: str, req: ScopesRequest, request: Request):
    scopes = [x for x in req.scopes if x in sections.SCOPES] or ["business", "debt"]
    return sections.run_section2(repo(), prompts(request), get_settings(), deal_id, scopes)


@router.get("/deals/{deal_id}/section2")
def get_s2(deal_id: str):
    r = repo()
    r.get_deal(deal_id)
    return {"s2": r.read(deal_id, "s2.json", {}), "evidence": r.read(deal_id, "evidence.json", {})}


@router.post("/deals/{deal_id}/section3/run")
def run_s3(deal_id: str, request: Request):
    return sections.run_section3(repo(), prompts(request), get_settings(), deal_id)


@router.get("/deals/{deal_id}/section3")
def get_s3(deal_id: str):
    return repo().read(deal_id, "s3.json") or {}


class ActionRequest(BaseModel):
    action: str
    analyst_name: str | None = None
    text: str | None = None


@router.post("/deals/{deal_id}/section3/statements/{sid}/action")
def s3_statement_action(deal_id: str, sid: str, req: ActionRequest):
    return review.s3_action(repo(), deal_id, sid, req.action, req.analyst_name, req.text)


class NameRequest(BaseModel):
    analyst_name: str | None = None


class BulkRequest(BaseModel):
    action: str
    analyst_name: str | None = None


@router.post("/deals/{deal_id}/section3/bulk")
def s3_bulk_action(deal_id: str, req: BulkRequest):
    return review.s3_bulk(repo(), deal_id, req.action, req.analyst_name)


@router.post("/deals/{deal_id}/section3/approve")
def s3_approve(deal_id: str, req: NameRequest):
    return review.s3_approve(repo(), deal_id, req.analyst_name)


@router.post("/deals/{deal_id}/section4/run")
def run_s4(deal_id: str, request: Request):
    return sections.run_section4(repo(), prompts(request), get_settings(), deal_id)


@router.get("/deals/{deal_id}/section4")
def get_s4(deal_id: str):
    return repo().read(deal_id, "s4.json") or {}


@router.post("/deals/{deal_id}/section5/run")
def run_s5(deal_id: str, request: Request):
    return sections.run_section5(repo(), prompts(request), get_settings(), deal_id)


@router.get("/deals/{deal_id}/section5")
def get_s5(deal_id: str):
    r = repo()
    s5 = r.read(deal_id, "s5.json") or {}
    if s5:
        support = r.read(deal_id, "s6_support.json", {})
        for st in s5["statements"]:
            a = support.get(st["id"])
            st["support"] = a if a and a.get("text_at_check") == st["text"] else None
    return s5


@router.post("/deals/{deal_id}/memo/statements/{sid}/action")
def memo_statement_action(deal_id: str, sid: str, req: ActionRequest):
    return review.memo_action(repo(), deal_id, sid, req.action, req.analyst_name, req.text)


@router.get("/deals/{deal_id}/evidence/{ev_id}")
def evidence(deal_id: str, ev_id: str, statement_id: str | None = None):
    return review.evidence_lookup(repo(), deal_id, ev_id, statement_id)


@router.post("/deals/{deal_id}/support-check/run")
def support_check(deal_id: str, request: Request):
    return sections.run_support_check(repo(), prompts(request), get_settings(), deal_id)


@router.get("/deals/{deal_id}/audit-trail")
def audit_trail(deal_id: str):
    r = repo()
    r.get_deal(deal_id)
    return r.audit(deal_id)


# --------------------------------------------------------------------------- exports
@router.post("/deals/{deal_id}/exports/memo")
def export_memo(deal_id: str, req: NameRequest):
    p = export.memo_pdf(repo(), deal_id, req.analyst_name or "")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@router.post("/deals/{deal_id}/exports/audit")
def export_audit(deal_id: str):
    p = export.audit_pdf(repo(), deal_id)
    return FileResponse(p, media_type="application/pdf", filename=p.name)
