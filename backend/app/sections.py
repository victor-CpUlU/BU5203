"""Section services 2-6: build inputs, run AI tasks through the runner, apply backend checks, store outputs."""
from __future__ import annotations

import re

from . import documents as docs
from .financial import CANONICAL_LABEL, NOT_IN_DB, PANELS
from .llm import TaskSpec, run_llm_task
from .schemas import (BUSINESS_FIELDS, CALIBRATION, DEBT_FIELDS, MEMO_OUTLINE, PANEL_KEYS, PLACEHOLDER,
                      REPAYMENT_DIMENSIONS)
from .storage import AppError, Repo, deal_lock, now_iso
from .verification import (UNAVAILABLE_NAME_PATTERNS, count_sentences, extract_figures, has_decision_language,
                           verify_statement)

SCOPES = {
    "business": {"prompt": "S2A", "section": "s2a", "fields": BUSINESS_FIELDS, "title": "Section 2A business extraction"},
    "debt": {"prompt": "S2B", "section": "s2b", "fields": DEBT_FIELDS, "title": "Section 2B debt and financing extraction"},
}
LEVEL = {"High": 0, "Medium": 1, "Low": 2}


# --------------------------------------------------------------------------- shared context
def intake_payload(deal: dict) -> dict:
    return {k: v["display"] for k, v in deal["intake"].items()}


def load_context(repo: Repo, deal: dict) -> dict:
    deal_id = deal["deal_id"]
    dataset = repo.read(deal_id, "financial/dataset.json")
    csv_ev = repo.read(deal_id, "financial/csv_evidence.json", {})
    doc_ev = repo.read(deal_id, "evidence.json", {})
    return {
        "dataset": dataset,
        "csv": csv_ev,
        "evidence": doc_ev,
        "intake": deal["intake"],
        "comparisons": dataset["comparisons"] if dataset else [],
        "unavailable": dataset["unavailable_metrics"] if dataset else [],
        "known": set(csv_ev) | set(doc_ev) | set(deal["intake"]),
    }


def _audit(repo: Repo, deal_id: str):
    return lambda entry: repo.append_audit(deal_id, entry)


def _items_for_scope(ctx: dict, scope: str) -> list[dict]:
    return [{"evidence_id": e["evidence_id"], "field": e["field_label"], "statement": e["statement"], "issues": e["issues"]}
            for e in ctx["evidence"].values() if e["scope"] == scope]


def _dataset_payload(dataset: dict) -> dict:
    return {
        "file_name": dataset["file_name"],
        "periods": [p["label"] for p in dataset["periods"]],
        "metrics": [{"metric_key": m["key"], "label": m["label"], "unit": m["unit_type"],
                     "values": [{"period": e["period"], "display": e["display"], "evidence_id": e["evidence_id"], "flags": e["flags"]}
                                for e in m["entries"]]}
                    for m in dataset["metrics"] if m["recognised"]],
    }


def _comparisons_payload(dataset: dict) -> list[dict]:
    return [{"metric_key": c["metric_key"], "from_period": c["from_period"], "to_period": c["to_period"],
             "change": c["change_display"], "direction": c["direction"]} for c in dataset["comparisons"]]


def _unavailable_payload(dataset: dict) -> list[dict]:
    return [{"metric": m, "value": NOT_IN_DB} for m in dataset["unavailable_metrics"]]


def _fail(repo: Repo, deal_id: str, key: str, title: str, errors: list[str]) -> None:
    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        prev = deal["sections"][key]
        deal["sections"][key] = {**prev, "last_error": errors, "last_error_at": now_iso()}
        repo.save_deal(deal)
    raise AppError(502, "section_failed", f"{title} failed. Earlier results are unchanged; you can re-run it.", details=errors)


def _finish(repo: Repo, deal_id: str, key: str, message: str | None = None) -> dict:
    deal = repo.get_deal(deal_id)
    Repo.set_section(deal, key, "completed", message)
    Repo.mark_later_stale(deal, key)
    repo.save_deal(deal)
    return deal


# --------------------------------------------------------------------------- Section 2
def _validate_item(item: dict, scope: str, allowed: set[tuple[str, int]]) -> str | None:
    if not item["statement"].strip():
        return "Missing statement"
    if (item["doc_id"], item["page"]) not in allowed:
        return "Cited document and page were not in the pages supplied"
    if not item["section_heading"].strip():
        return "Missing section heading"
    if not (1 <= len(item["excerpt"].strip()) <= 500):
        return "Supporting excerpt must be 1 to 500 characters"
    if count_sentences(item["statement"]) > 2:
        return "Statement has more than 2 sentences"
    if scope == "business" and len(item["statement"]) > 300:
        return "Statement is longer than 300 characters"
    if scope == "debt":
        excerpt_figs = {(f["number"], f["unit"]) for f in extract_figures(item["excerpt"])}
        excerpt_nums = {f["number"] for f in extract_figures(item["excerpt"])}
        for f in extract_figures(item["statement"]):
            if (f["number"], f["unit"]) not in excerpt_figs and f["number"] not in excerpt_nums:
                return f"Figure {f['raw']} does not appear in the supporting excerpt"
    return None


def run_section2(repo: Repo, prompts, settings, deal_id: str, scopes: list[str]) -> dict:
    deal = repo.get_deal(deal_id)
    eligible = [d for d in deal["documents"] if not d.get("failed") and not d.get("extraction_excluded")]
    if not eligible:
        raise AppError(409, "no_documents", "No documents with extractable text are available. Upload at least one readable PDF first.")
    pages = []
    for d in eligible:
        for p in repo.read(deal_id, f"pages/{d['doc_id']}.json", []):
            pages.append({**p, "doc_id": d["doc_id"], "doc_name": d["display_name"]})
    doc_list = [{"doc_id": d["doc_id"], "doc_name": d["display_name"], "doc_type": d["doc_type"],
                 "period_covered": d["period_covered"], "audited": d["audited"]} for d in eligible]
    messages = {}
    for scope in scopes:
        messages[scope] = _run_scope(repo, prompts, settings, deal_id, scope, pages, doc_list)
    return {"messages": messages}


def _run_scope(repo, prompts, settings, deal_id, scope, pages, doc_list) -> str | None:
    cfg = SCOPES[scope]
    keywords = settings.keywords_business if scope == "business" else settings.keywords_debt
    selected = docs.select_pages(pages, keywords)
    deal = repo.get_deal(deal_id)
    raw_items: list[tuple[dict, set]] = []
    message = None
    if not selected:
        message = f"No relevant pages were found for {'business information' if scope == 'business' else 'debt and financing information'}."
    for batch in docs.batch_pages(selected, settings.page_limit):
        allowed = {(p["doc_id"], p["page"]) for p in batch}
        payload = {"scope": scope, "deal_intake": intake_payload(deal),
                   "fields": [{"key": k, "label": lbl} for k, lbl in cfg["fields"]],
                   "documents": doc_list, "pages": docs.render_batch(batch)}
        res = run_llm_task(TaskSpec(cfg["prompt"], retry_transport=True), payload, prompts, settings, set(), _audit(repo, deal_id))
        if not res["ok"]:
            _fail(repo, deal_id, cfg["section"], cfg["title"], res["errors"])
        for it in res["output"]["items"]:
            raw_items.append((it, allowed))

    order = {k: i for i, (k, _) in enumerate(cfg["fields"])}
    indexed = sorted(enumerate(raw_items), key=lambda x: (order[x[1][0]["field"]], docs.order_key(x[1][0]), x[0]))
    fields = {k: {"key": k, "label": lbl, "issues": [], "evidence_ids": [], "rejected": [], "conflicts": []} for k, lbl in cfg["fields"]}
    accepted: list[dict] = []
    for _, (item, allowed) in indexed:
        f = fields[item["field"]]
        reason = _validate_item(item, scope, allowed)
        if reason is None and scope == "business" and sum(1 for a in accepted if a["field"] == item["field"]) >= 5:
            reason = "More than 5 items for this field"
        if reason:
            f["rejected"].append({"statement": item["statement"], "doc_id": item["doc_id"], "page": item["page"], "reason": reason})
            if scope == "debt" and "Invalid output" not in f["issues"]:
                f["issues"].append("Invalid output")
            continue
        accepted.append(item)

    with deal_lock(deal_id):
        deal = repo.get_deal(deal_id)
        evidence = repo.read(deal_id, "evidence.json", {})
        archive = repo.read(deal_id, "evidence_archive.json", {})
        for ev_id in [k for k, v in evidence.items() if v["scope"] == scope]:
            archive[ev_id] = {**evidence.pop(ev_id), "archived_at": now_iso()}
        doc_meta = {d["doc_id"]: d for d in deal["documents"]}
        for item in accepted:
            ev_id = f"EV-{deal['next_ev_seq']:03d}"
            deal["next_ev_seq"] += 1
            meta = doc_meta.get(item["doc_id"])
            pdf = repo.path(deal_id, "documents", f"{item['doc_id']}.pdf") if meta else None
            loc = docs.locate(pdf, item["page"], item["excerpt"], meta["page_count"] if meta else None)
            issues = [] if loc["status"] == "Located" else [loc["issue"]]
            evidence[ev_id] = {"evidence_id": ev_id, "type": "document", "scope": scope, "field": item["field"],
                               "field_label": dict(cfg["fields"])[item["field"]], "statement": item["statement"].strip(),
                               "doc_id": item["doc_id"], "doc_name": meta["display_name"] if meta else item["doc_id"],
                               "page": item["page"], "section_heading": item["section_heading"].strip(),
                               "excerpt": item["excerpt"].strip(), "location_status": loc["status"], "rects": loc["rects"],
                               "issues": issues, "review_flag": loc["status"] != "Located",
                               "item_key": item.get("item_key"), "as_of": item.get("as_of"), "created_at": now_iso()}
            fields[item["field"]]["evidence_ids"].append(ev_id)
        if scope == "debt":
            _detect_conflicts(fields, evidence)
        for f in fields.values():
            if not f["evidence_ids"]:
                f["issues"].insert(0, "Not available")
        s2 = repo.read(deal_id, "s2.json", {})
        s2[scope] = {"fields": list(fields.values()), "message": message, "pages_sent": len(selected), "completed_at": now_iso()}
        repo.write(deal_id, "evidence_archive.json", archive)
        repo.write(deal_id, "evidence.json", evidence)
        repo.write(deal_id, "s2.json", s2)
        repo.save_deal(deal)
        _finish(repo, deal_id, cfg["section"], message)
    return message


def _detect_conflicts(fields: dict, evidence: dict) -> None:
    """Same debt item and period stated with different figures in different documents -> Conflicting (Req 6.4)."""
    groups: dict[tuple, list[str]] = {}
    for f in fields.values():
        for ev_id in f["evidence_ids"]:
            e = evidence[ev_id]
            if e.get("item_key"):
                groups.setdefault((re.sub(r"\s+", " ", e["item_key"].strip().lower()), (e.get("as_of") or "").strip().lower()), []).append(ev_id)
    for (key, as_of), ids in groups.items():
        docs_seen = {evidence[i]["doc_id"] for i in ids}
        figs = {frozenset(x["number"] for x in extract_figures(evidence[i]["statement"])) for i in ids}
        if len(docs_seen) >= 2 and len(figs) > 1:
            for f in fields.values():
                if any(i in f["evidence_ids"] for i in ids):
                    if "Conflicting" not in f["issues"]:
                        f["issues"].append("Conflicting")
                    f["conflicts"].append({"item_key": key, "as_of": as_of or None, "candidates": ids, "preferred": None})
            for i in ids:
                if "Conflicting" not in evidence[i]["issues"]:
                    evidence[i]["issues"].append("Conflicting")


# --------------------------------------------------------------------------- Section 3
def _all_s3(out: dict) -> list[tuple[str, dict]]:
    pairs = []
    for p in out["panels"]:
        for i, s in enumerate(p["statements"]):
            pairs.append((f"panel:{p['panel']}#{i + 1}", s))
    for i, s in enumerate(out.get("cross_metric", [])):
        pairs.append((f"cross#{i + 1}", s))
    for r in out["repayment_capacity"]:
        for kind in ("supports", "weakens"):
            for i, s in enumerate(r[kind]):
                pairs.append((f"repayment:{r['dimension']}:{kind}#{i + 1}", s))
    return pairs


def s3_rules(out: dict, present_keys: set[str]) -> list[str]:
    errs = []
    if [p["panel"] for p in out["panels"]] != PANEL_KEYS:
        errs.append(f"panels must be exactly, in order: {PANEL_KEYS}")
    if [r["dimension"] for r in out["repayment_capacity"]] != REPAYMENT_DIMENSIONS:
        errs.append(f"repayment_capacity dimensions must be exactly, in order: {REPAYMENT_DIMENSIONS}")
    panel_metrics = {k: m for k, _, m, _ in PANELS}
    for p in out["panels"]:
        cited = {r for s in p["statements"] for r in s["refs"]}
        for mk in panel_metrics.get(p["panel"], []):
            if mk in present_keys and not any(r.startswith(f"CSV-{mk}-") for r in cited):
                errs.append(f"panel {p['panel']} must comment on {mk} and cite its CSV Evidence_IDs")
    for owner, s in _all_s3(out):
        csv_refs = [r for r in s["refs"] if r.startswith("CSV-")]
        ev_refs = [r for r in s["refs"] if r.startswith("EV-")]
        if s["label"] == "Sourced" and owner.startswith(("panel", "cross")) and not csv_refs:
            errs.append(f"{owner}: a Sourced trend statement must cite the CSV Evidence_ID of every period it references")
        if s["label"] == "Sourced" and not s["refs"]:
            errs.append(f"{owner}: Sourced statements must cite at least one Evidence_ID")
        if s["label"] == "ASSUMPTION" and not ev_refs:
            errs.append(f"{owner}: an ASSUMPTION (possible explanation) must cite at least one EV- Evidence_ID")
        if has_decision_language(s["text"]):
            errs.append(f"{owner}: no lending recommendation or credit decision language is allowed")
    return errs


def run_section3(repo: Repo, prompts, settings, deal_id: str) -> dict:
    deal = repo.get_deal(deal_id)
    missing = []
    if deal["financial"]["status"] != "loaded":
        missing.append("the financial database (CSV) has not been loaded")
    for k, name in (("s2a", "Section 2A business extraction"), ("s2b", "Section 2B debt and financing extraction")):
        if deal["sections"][k]["status"] not in ("completed",):
            missing.append(f"{name} has not completed")
    if missing:
        raise AppError(409, "precondition", "Section 3 cannot run yet: " + "; ".join(missing) + ".")
    ctx = load_context(repo, deal)
    ds = ctx["dataset"]
    present = {m["key"] for m in ds["metrics"] if m["recognised"] and any(e["value"] is not None for e in m["entries"])}
    payload = {
        "deal_intake": intake_payload(deal),
        "business_information": _items_for_scope(ctx, "business"),
        "debt_and_financing": _items_for_scope(ctx, "debt"),
        "financial_dataset": _dataset_payload(ds),
        "comparison_records": _comparisons_payload(ds),
        "sustained_trends": {k: v for k, v in ds["sustained"].items() if v},
        "unavailable_metrics": _unavailable_payload(ds),
        "divergence_patterns": [{"pattern_id": d["pattern_id"], "description": d["description"],
                                 "status": "assessable" if d["assessable"] else "not assessable"} for d in ds["divergence"]],
        "panels": [{"panel": k, "title": t, "metrics": m} for k, t, m, _ in PANELS],
        "repayment_dimensions": REPAYMENT_DIMENSIONS,
    }
    spec = TaskSpec("S3", rules=lambda o: s3_rules(o, present), refs=lambda o: [(own, r) for own, s in _all_s3(o) for r in s["refs"]])
    res = run_llm_task(spec, payload, prompts, settings, ctx["known"], _audit(repo, deal_id))
    if not res["ok"]:
        _fail(repo, deal_id, "s3", "Section 3 financial trend analysis", res["errors"])
    statements = []
    for n, (owner, s) in enumerate(_all_s3(res["output"]), start=1):
        group = owner.split("#")[0]
        v = verify_statement(s, ctx, "S3")
        statements.append({"id": f"S3-{n}", "group": group, "text": s["text"], "original_text": s["text"], "label": s["label"],
                           "refs": s["refs"], "claims": s["claims"], "verification": v, "status": "Pending", "comments": []})
    divergences = [{"pattern_id": d["pattern_id"], "description": d["description"],
                    "result": "Assessable" if d["assessable"] else "Not assessable: data not available in database",
                    "missing_metrics": d["missing_metrics"]} for d in ds["divergence"]]
    with deal_lock(deal_id):
        repo.append_audit(deal_id, {"type": "number_check", "section": "s3",
                                    "results": [{"statement_id": s["id"], "mark": s["verification"]["mark"],
                                                 "unmatched": s["verification"]["unmatched"]} for s in statements]})
        repo.write(deal_id, "s3.json", {"statements": statements, "divergences": divergences, "approved": False,
                                        "approval": None, "generated_at": now_iso()})
        _finish(repo, deal_id, "s3")
    return repo.read(deal_id, "s3.json")


# --------------------------------------------------------------------------- Section 4
def s4_rules(out: dict) -> list[str]:
    errs = []
    risks = out["risks"]
    if len(risks) < 3 and not any("fewer than 3" in l.lower() for l in out.get("limitations", [])):
        errs.append("return 3 to 5 risks, or state in limitations that fewer than 3 risks are supported by the evidence provided")
    if [r["rank"] for r in risks] != list(range(1, len(risks) + 1)):
        errs.append("ranks must be consecutive starting at 1, in list order")
    keys = [(LEVEL[r["impact"]], LEVEL[r["likelihood"]], 0 if any(x.startswith("CSV-") for x in r["evidence"]["refs"]) else 1) for r in risks]
    if keys != sorted(keys):
        errs.append("order risks by impact (High first), then likelihood (High first), then risks citing CSV evidence first")
    for r in risks:
        tag = f"risk {r['rank']}"
        if not r["evidence"]["refs"]:
            errs.append(f"{tag}: evidence must cite at least one Evidence_ID")
        for t in r["terms"]:
            if extract_figures(t["text"]) and (t["label"] != "ASSUMPTION" or CALIBRATION not in t["text"]):
                errs.append(f"{tag}: a term with a numeric threshold must be labelled ASSUMPTION and include \"{CALIBRATION}\"")
        texts = [r["identified_risk"], r["evidence"]["text"], r["time_horizon"]] + r["mitigants"] + [t["text"] for t in r["terms"]]
        if r.get("business_context"):
            texts.append(r["business_context"]["text"])
        if any(has_decision_language(x) for x in texts):
            errs.append(f"{tag}: no approval, decline or lending recommendation is allowed")
    return errs


def _s4_refs(out: dict) -> list[tuple[str, str]]:
    pairs = []
    for r in out["risks"]:
        own = f"risk {r['rank']}"
        pairs += [(own, x) for x in r["evidence"]["refs"]]
        if r.get("business_context"):
            pairs += [(own, x) for x in r["business_context"]["refs"]]
        for t in r["terms"]:
            pairs += [(own, x) for x in t["refs"]]
    return pairs


def run_section4(repo: Repo, prompts, settings, deal_id: str) -> dict:
    deal = repo.get_deal(deal_id)
    if not deal["s3_approved"]:
        raise AppError(409, "s3_not_approved", "Section 3 approval is required before Section 4 can run.")
    ctx = load_context(repo, deal)
    s3 = repo.read(deal_id, "s3.json")
    ds = ctx["dataset"]
    payload = {
        "deal_intake": intake_payload(deal),
        "approved_financial_analysis": [{"statement_id": s["id"], "group": s["group"], "text": s["text"], "label": s["label"],
                                         "refs": s["refs"], "status": s["status"]} for s in s3["statements"]],
        "business_information": _items_for_scope(ctx, "business"),
        "debt_and_financing": _items_for_scope(ctx, "debt"),
        "financial_dataset": _dataset_payload(ds),
        "comparison_records": _comparisons_payload(ds),
        "unavailable_metrics": _unavailable_payload(ds),
    }
    res = run_llm_task(TaskSpec("S4", rules=s4_rules, refs=_s4_refs), payload, prompts, settings, ctx["known"], _audit(repo, deal_id))
    if not res["ok"]:
        _fail(repo, deal_id, "s4", "Section 4 risks and mitigants", res["errors"])
    risks = []
    for r in res["output"]["risks"]:
        v = verify_statement({"text": r["evidence"]["text"], "refs": r["evidence"]["refs"]}, ctx, "S4")
        risks.append({**r, "risk_id": f"RISK-{r['rank']}", "verification": v})
    with deal_lock(deal_id):
        repo.append_audit(deal_id, {"type": "number_check", "section": "s4",
                                    "results": [{"risk_id": r["risk_id"], "mark": r["verification"]["mark"],
                                                 "unmatched": r["verification"]["unmatched"]} for r in risks]})
        repo.write(deal_id, "s4.json", {"risks": risks, "limitations": res["output"]["limitations"], "generated_at": now_iso()})
        _finish(repo, deal_id, "s4")
    return repo.read(deal_id, "s4.json")


# --------------------------------------------------------------------------- Section 5
def s5_rules(out: dict) -> list[str]:
    errs = []
    got = [(s["number"], s["title"], [ss["key"] for ss in s["subsections"]]) for s in out["sections"]]
    want = [(n, t, [k for k, _ in subs]) for n, t, subs in MEMO_OUTLINE]
    if got != want:
        errs.append("sections and subsections must match memo_outline exactly (7 sections, same numbers, titles and subsection keys in order)")
    for s in out["sections"]:
        for ss in s["subsections"]:
            for st in ss["statements"]:
                tag = f"section {s['number']} {ss['key']}"
                if st["text"].strip() == PLACEHOLDER and st["label"] != "NOT VERIFIED":
                    errs.append(f"{tag}: the placeholder statement must be labelled NOT VERIFIED")
                if st["label"] == "Sourced" and not st["refs"]:
                    errs.append(f"{tag}: every Sourced statement must cite at least one Evidence_ID")
                if has_decision_language(st["text"]):
                    errs.append(f"{tag}: the memo must not recommend approval or decline or state a credit decision")
    return errs


def _s5_refs(out: dict) -> list[tuple[str, str]]:
    return [(f"section {s['number']} {ss['key']}", r) for s in out["sections"] for ss in s["subsections"]
            for st in ss["statements"] for r in st["refs"]]


def _gap_statements(ds: dict, s3: dict, s4: dict) -> tuple[list[dict], list[dict]]:
    """Backend-generated Information Gaps statements from the recorded gaps and Anomaly_Flags (Req 18.6)."""
    missing, conflicting = [], []
    by_label = {m["label_as_written"]: m for m in ds["metrics"]}
    for g in ds["information_gaps"]:
        refs = []
        m = re.match(r'Unit not stated in database for "(.+)"', g)
        if m and m.group(1) in by_label:
            refs = [e["evidence_id"] for e in by_label[m.group(1)]["entries"]]
        missing.append({"text": g + ".", "label": "Sourced" if refs else "NOT VERIFIED", "refs": refs})
    texts = " ".join([s["text"] for s in s3["statements"]] + [r["evidence"]["text"] for r in s4["risks"]]).lower()
    for name in ds["unavailable_metrics"]:
        pat = UNAVAILABLE_NAME_PATTERNS.get(name)
        if pat and re.search(pat, texts):
            missing.append({"text": f"{name}: {NOT_IN_DB}.", "label": "NOT VERIFIED", "refs": []})
    for f in ds["flagged_values"]:
        review_flags = [x for x in f["flags"] if x != "unit not stated"]
        if review_flags:
            conflicting.append({"text": f"{f['metric']} for {f['period']} ({f['display']}) is flagged for analyst review: {', '.join(review_flags)}.",
                                "label": "Sourced", "refs": [f["evidence_id"]]})
    return missing, conflicting


def run_section5(repo: Repo, prompts, settings, deal_id: str) -> dict:
    deal = repo.get_deal(deal_id)
    if deal["sections"]["s4"]["status"] != "completed":
        raise AppError(409, "precondition", "Section 4 must be completed first (and be up to date) before the memo can be generated.")
    ctx = load_context(repo, deal)
    ds, s3, s4 = ctx["dataset"], repo.read(deal_id, "s3.json"), repo.read(deal_id, "s4.json")
    payload = {
        "memo_outline": [{"number": n, "title": t, "subsections": [{"key": k, "title": st} for k, st in subs]} for n, t, subs in MEMO_OUTLINE],
        "deal_intake": intake_payload(deal),
        "business_information": _items_for_scope(ctx, "business"),
        "debt_and_financing": _items_for_scope(ctx, "debt"),
        "approved_financial_analysis": [{"statement_id": s["id"], "group": s["group"], "text": s["text"], "label": s["label"], "refs": s["refs"]}
                                        for s in s3["statements"] if s["status"] == "Approved"],
        "risks": [{k: r[k] for k in ("risk_id", "identified_risk", "category", "impact", "likelihood", "evidence", "time_horizon",
                                     "business_context", "mitigants", "terms")} for r in s4["risks"]],
        "risk_limitations": s4["limitations"],
        "financial_dataset": _dataset_payload(ds),
        "comparison_records": _comparisons_payload(ds),
        "unavailable_metrics": _unavailable_payload(ds),
        "information_gaps": ds["information_gaps"],
    }
    res = run_llm_task(TaskSpec("S5", rules=s5_rules, refs=_s5_refs, soft_unknown_refs=True), payload, prompts, settings,
                       ctx["known"], _audit(repo, deal_id))
    if not res["ok"]:
        _fail(repo, deal_id, "s5", "Section 5 credit memo", res["errors"])
    missing_gaps, anomaly_gaps = _gap_statements(ds, s3, s4)
    verified_csv = {r for s in s3["statements"] if s["status"] == "Approved" and s["verification"]["mark"] == "Numbers verified"
                    for r in s["refs"] if r.startswith("CSV-")}
    titles = {n: (t, dict(subs)) for n, t, subs in MEMO_OUTLINE}
    statements, n = [], 0
    for sec in res["output"]["sections"]:
        for ss in sec["subsections"]:
            items = [{**st, "source": "ai"} for st in ss["statements"]]
            extra = []
            if ss["key"] == "dscr_and_debt_servicing" and not any("pro-forma" in st["text"].lower() or "pro forma" in st["text"].lower() for st in items):
                extra.append({"text": "Pro-forma debt service including the requested facility has not been assessed and must be assessed by the analyst.",
                              "label": "NOT VERIFIED", "refs": [], "source": "backend"})
            if ss["key"] == "missing_information":
                extra += [{**g, "source": "backend"} for g in missing_gaps]
            if ss["key"] == "conflicting_information":
                extra += [{**g, "source": "backend"} for g in anomaly_gaps]
            if extra:
                items = [st for st in items if st["text"].strip() != PLACEHOLDER] + extra
            for st in items:
                n += 1
                statements.append(_memo_statement(f"M{n}", sec["number"], titles[sec["number"]], ss["key"], st, ctx, verified_csv))
    unknown = {e for _, e in res.get("unknown_refs", [])}
    for st in statements:
        bad = [r for r in st["refs"] if r in unknown or r not in ctx["known"]]
        if bad:
            st["status"], st["note"] = "Flagged", "Reference does not exist: " + ", ".join(bad)
        elif st["label"] in ("Sourced", "ASSUMPTION") and not st["refs"]:
            st["status"], st["note"] = "Flagged", "No supporting reference"
    with deal_lock(deal_id):
        repo.append_audit(deal_id, {"type": "number_check", "section": "s5",
                                    "results": [{"statement_id": s["id"], "mark": s["verification"]["mark"],
                                                 "unmatched": s["verification"]["unmatched"]} for s in statements]})
        for s in statements:
            if s["status"] != "Pending":
                repo.append_audit(deal_id, {"type": "memo_status", "statement_id": s["id"], "status_before": None,
                                            "status_after": s["status"], "note": s["note"], "analyst_name": "System",
                                            "text_after": s["text"], "evidence_snapshot": evidence_snapshot(ctx, s["refs"])})
        repo.write(deal_id, "s5.json", {"statements": statements, "generated_at": now_iso()})
        repo.write(deal_id, "s6_support.json", {})
        _finish(repo, deal_id, "s5")
    return repo.read(deal_id, "s5.json")


def _memo_statement(sid, number, titles, key, st, ctx, verified_csv) -> dict:
    v = verify_statement(st, ctx, "S5")
    status, note = "Pending", None
    refs = st["refs"]
    if st["source"] == "backend" and refs and all(r.startswith("CSV-") for r in refs) and v["mark"] == "Numbers verified":
        status, note = "Approved", "Generated by the Backend from the financial database (not AI-written)"
    elif refs and all(r.startswith("CSV-") and r in verified_csv for r in refs):
        only_csv = verify_statement({"text": st["text"], "refs": refs}, {"csv": ctx["csv"], "comparisons": ctx["comparisons"]}, "S3")
        if only_csv["mark"] == "Numbers verified":
            status, note = "Approved", "Verified in Section 3 financial review"
    return {"id": sid, "section": number, "section_title": titles[0], "subsection": key, "subsection_title": titles[1][key],
            "text": st["text"], "original_text": st["text"], "label": st["label"], "refs": refs, "source": st["source"],
            "status": status, "note": note, "verification": v, "activated": []}


def evidence_snapshot(ctx: dict, refs: list[str]) -> list[dict]:
    out = []
    for r in refs:
        if r in ctx["evidence"]:
            e = ctx["evidence"][r]
            out.append({"evidence_id": r, "doc_id": e["doc_id"], "doc_name": e["doc_name"], "page": e["page"], "excerpt": e["excerpt"]})
        elif r in ctx["csv"]:
            e = ctx["csv"][r]
            out.append({"evidence_id": r, "metric_label": e["metric_label_as_written"], "column_header": e["column_header"], "display": e["display"]})
        elif r in ctx["intake"]:
            out.append({"evidence_id": r, "value": ctx["intake"][r]["display"]})
        else:
            out.append({"evidence_id": r, "unknown": True})
    return out


# --------------------------------------------------------------------------- Section 6 support check
def run_support_check(repo: Repo, prompts, settings, deal_id: str) -> dict:
    if not settings.support_check_enabled:
        raise AppError(409, "support_disabled", "The AI support check is disabled in .env (SUPPORT_CHECK_ENABLED=false).")
    deal = repo.get_deal(deal_id)
    s5 = repo.read(deal_id, "s5.json")
    if not s5:
        raise AppError(409, "precondition", "Generate the memo (Section 5) first.")
    ctx = load_context(repo, deal)
    targets = [s for s in s5["statements"] if any(r in ctx["evidence"] for r in s["refs"])]
    if not targets:
        return repo.read(deal_id, "s6_support.json", {})
    payload = {"statements": [{"statement_id": s["id"], "text": s["text"],
                               "excerpts": [{"evidence_id": r, "excerpt": ctx["evidence"][r]["excerpt"]} for r in s["refs"] if r in ctx["evidence"]]}
                              for s in targets]}
    ids = {s["id"] for s in targets}
    rules = lambda o: [f"unknown statement_id {a['statement_id']}" for a in o["assessments"] if a["statement_id"] not in ids]
    res = run_llm_task(TaskSpec("S6", rules=rules), payload, prompts, settings, ctx["known"], _audit(repo, deal_id))
    if not res["ok"]:
        raise AppError(502, "support_unavailable", "The AI support check is unavailable. Review and PDF generation are not affected.", details=res["errors"])
    by_id = {s["id"]: s for s in targets}
    with deal_lock(deal_id):
        store = repo.read(deal_id, "s6_support.json", {})
        for a in res["output"]["assessments"]:
            store[a["statement_id"]] = {"assessment": a["assessment"], "reason": a["reason"], "text_at_check": by_id[a["statement_id"]]["text"],
                                        "checked_at": now_iso()}
        repo.write(deal_id, "s6_support.json", store)
    return store
