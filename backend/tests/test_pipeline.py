"""End-to-end run of Sections 1-6 through the REST API with a fake LLM (Req 2-24, 29.8, 29.12)."""
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import make_pdf

INTAKE = {"borrower": "Intel Corporation", "facility_type": "Term loan", "amount": "500000000", "currency": "usd",
          "purpose": "Fund foundry capacity expansion", "tenor": "5 years", "repayment": "Bullet at maturity", "collateral": ""}


def test_full_pipeline(env, fake_llm):
    c = TestClient(create_app())
    assert c.get("/api/health").json() == {"status": "ok"}
    assert c.get("/").status_code == 200  # frontend served by the backend

    # Section 1: intake validation and creation
    bad = c.post("/api/deals", json={**INTAKE, "amount": "abc", "borrower": " ", "currency": "US"})
    assert bad.status_code == 422 and {f["field"] for f in bad.json()["fields"]} == {"amount", "borrower", "currency"}
    deal = c.post("/api/deals", json=INTAKE).json()
    did = deal["deal_id"]
    assert deal["intake"]["DI-COLLATERAL"]["display"] == "None provided" and deal["intake"]["DI-AMOUNT"]["display"] == "500000000 USD"
    # Section 2C: the external financial database is auto-connected at deal creation (no analyst action)
    assert deal["financial"]["status"] == "connected" and deal["financial"]["confirmed"] is True
    fin = c.get(f"/api/deals/{did}/financial").json()
    assert fin["sheet"] == "Intel" and fin["company"] == "Intel Corporation"
    assert len(fin["comparisons"]) == 72
    assert len(c.get(f"/api/deals/{did}/dashboard").json()["panels"]) == 5

    # Forecast and scenarios: defaults from the database averages; analyst edits are validated, saved and audited
    fc = c.get(f"/api/deals/{did}/forecast").json()
    assert fc["available"] and fc["status"]["state"] == "default" and set(fc["scenarios"]) == {"base", "upside", "downside"}
    assert fc["assumptions"]["facility"] == {"repayment": "bullet", "tenor_quarters": 20, "fx_rate": None}
    assert fc["facility"]["value"] == 500.0  # 500000000 USD in USD m
    assert fc["assumptions"]["scenarios"]["base"]["revenue_growth"] == fc["history_stats"]["revenue_growth"]["mean"]
    bad_fc = c.post(f"/api/deals/{did}/forecast/preview", json={"assumptions": {"scenarios": {"base": {"ebitda_margin": 500}}}})
    assert bad_fc.status_code == 422 and bad_fc.json()["fields"][0]["field"] == "base.ebitda_margin"
    new = {**fc["assumptions"], "thresholds": {"min_dscr": 1.25}, "horizon_quarters": 8}
    assert c.put(f"/api/deals/{did}/forecast", json={"assumptions": new, "analyst_name": ""}).status_code == 422
    saved = c.put(f"/api/deals/{did}/forecast", json={"assumptions": new, "analyst_name": "Ana"}).json()
    assert saved["status"]["state"] == "saved" and len(saved["periods"]) == 8 and saved["breaches"]
    assert c.get(f"/api/deals/{did}/evidence/FT-MIN_DSCR").json()["display"] == "1.25x"

    # documents
    pdf = make_pdf(env / "intel.pdf", [
        "Item 1. Business. Intel designs and manufactures semiconductor products for customers worldwide.",
        "Borrowings. Intel had $2.5 billion of senior notes outstanding at year end.",
    ])
    not_pdf = c.post(f"/api/deals/{did}/documents", files={"file": ("x.pdf", b"hello", "application/pdf")},
                     data={"doc_type": "10-K", "period_covered": "FY2025", "audited": "Yes"})
    assert not_pdf.status_code == 422
    up = c.post(f"/api/deals/{did}/documents", files={"file": ("intel.pdf", pdf.read_bytes(), "application/pdf")},
                data={"doc_type": "10-K", "period_covered": "FY2025", "audited": "Yes", "display_name": "Intel 2025 10-K"})
    assert up.status_code == 200 and up.json()["document"]["doc_id"] == "D1" and up.json()["document"]["page_count"] == 2

    # Section 3 cannot run before extraction (the database is already connected)
    assert c.post(f"/api/deals/{did}/section3/run").status_code == 409

    # Section 2: extraction with evidence IDs located on the page
    assert c.post(f"/api/deals/{did}/section2/run", json={}).status_code == 200
    s2 = c.get(f"/api/deals/{did}/section2").json()
    evs = list(s2["evidence"].values())
    assert {e["evidence_id"] for e in evs} == {"EV-001", "EV-002"} and all(e["location_status"] == "Located" for e in evs)
    assert all(e["status"] == "Pending" for e in evs)  # items start Pending

    # Section 2 bulk approve: approves every pending item; name is required
    assert c.post(f"/api/deals/{did}/section2/bulk", json={"action": "approve_pending", "analyst_name": ""}).status_code == 422
    bulk2 = c.post(f"/api/deals/{did}/section2/bulk", json={"action": "approve_pending", "analyst_name": "Ana"}).json()
    assert bulk2["changed"] == 2
    assert all(e["status"] == "Approved" for e in c.get(f"/api/deals/{did}/section2").json()["evidence"].values())

    # Section 2 review: approve one item, edit the other (edit resets to Pending and re-checks the passage)
    assert c.post(f"/api/deals/{did}/section2/evidence/EV-001/action", json={"action": "approve", "analyst_name": ""}).status_code == 422
    ap = c.post(f"/api/deals/{did}/section2/evidence/EV-001/action", json={"action": "approve", "analyst_name": "Ana"}).json()
    assert ap["status"] == "Approved"
    ed = c.post(f"/api/deals/{did}/section2/evidence/EV-002/action",
                json={"action": "edit", "analyst_name": "Ana", "text": "Intel had senior notes outstanding."}).json()
    assert ed["status"] == "Pending" and ed["statement"] == "Intel had senior notes outstanding."
    # flag is available too (same format as the other sections) and keeps a note
    fl = c.post(f"/api/deals/{did}/section2/evidence/EV-002/action", json={"action": "flag", "analyst_name": "Ana", "text": "double-check figure"}).json()
    assert fl["status"] == "Flagged" and fl["note"] == "double-check figure"
    # approve it again so it can carry over to the memo
    c.post(f"/api/deals/{did}/section2/evidence/EV-002/action", json={"action": "approve", "analyst_name": "Ana"})

    # Section 4 is gated on Section 3 approval
    assert c.post(f"/api/deals/{did}/section4/run").status_code == 409

    # Section 3: analysis, number checks, approval gate
    s3 = c.post(f"/api/deals/{did}/section3/run").json()
    assert s3["statements"] and all(s["verification"]["mark"] == "Numbers verified" for s in s3["statements"])
    assert not any(d["result"].startswith("Not assessable") for d in s3["divergences"])
    assert [s["group"] for s in s3["statements"]].count("forecast") == 3
    assert all(s["label"] == "ASSUMPTION" for s in s3["statements"] if s["group"] == "forecast")
    blocked = c.post(f"/api/deals/{did}/section3/approve", json={"analyst_name": "Ana"})
    assert blocked.status_code == 409 and blocked.json()["details"]
    assert c.post(f"/api/deals/{did}/section3/statements/S3-1/action", json={"action": "approve", "analyst_name": ""}).status_code == 422
    for s in s3["statements"]:
        assert c.post(f"/api/deals/{did}/section3/statements/{s['id']}/action", json={"action": "approve", "analyst_name": "Ana"}).status_code == 200
    assert c.post(f"/api/deals/{did}/section3/approve", json={"analyst_name": "Ana"}).json()["approved"] is True
    # an edit after approval revokes it and resets the statement to Pending
    edited = c.post(f"/api/deals/{did}/section3/statements/S3-1/action", json={"action": "edit", "analyst_name": "Ana", "text": "Revenue Growth rose to 99.99% in Q2-2026."}).json()
    assert edited["approved"] is False and edited["statements"][0]["status"] == "Pending"
    assert edited["statements"][0]["verification"]["mark"] == "Number mismatch"
    c.post(f"/api/deals/{did}/section3/statements/S3-1/action", json={"action": "flag", "analyst_name": "Ana"})
    assert c.post(f"/api/deals/{did}/section3/approve", json={"analyst_name": "Ana"}).json()["approved"] is True

    # bulk review: approve the verified ones, then approval succeeds
    s3_2 = next(s for s in s3["statements"] if s["id"] == "S3-2")
    c.post(f"/api/deals/{did}/section3/statements/S3-2/action", json={"action": "edit", "analyst_name": "Ana", "text": s3_2["text"] + " "})
    assert c.post(f"/api/deals/{did}/section3/bulk", json={"action": "approve_verified", "analyst_name": ""}).status_code == 422
    bulk = c.post(f"/api/deals/{did}/section3/bulk", json={"action": "approve_verified", "analyst_name": "Ana"}).json()
    assert bulk["changed"] >= 1 and all(s["status"] != "Pending" for s in bulk["s3"]["statements"])
    assert c.post(f"/api/deals/{did}/section3/approve", json={"analyst_name": "Ana"}).json()["approved"] is True

    # Section 4
    s4 = c.post(f"/api/deals/{did}/section4/run").json()
    assert [r["risk_id"] for r in s4["risks"]] == ["RISK-1", "RISK-2", "RISK-3"]

    # Section 5: memo with backend gap statements and pro-forma note
    s5 = c.post(f"/api/deals/{did}/section5/run").json()
    sts = s5["statements"]
    assert [s["id"] for s in sts] == [f"M{i}" for i in range(1, len(sts) + 1)]
    assert {s["section"] for s in sts} == set(range(1, 8))
    # with a forecast, pro-forma debt service and the scenario summaries are backend-generated from FC- values
    proforma = [s for s in sts if s["subsection"] == "dscr_and_debt_servicing" and "pro-forma debt service" in s["text"]]
    assert proforma and proforma[0]["label"] == "ASSUMPTION" and proforma[0]["verification"]["mark"] == "Numbers verified"
    scen = [s for s in sts if s["subsection"] == "forecast_and_scenarios"]
    assert len(scen) >= 3 and all(s["source"] == "backend" and s["status"] == "Pending" for s in scen)
    assert all(s["verification"]["mark"] == "Numbers verified" for s in scen)
    assert any(s["subsection"] == "conflicting_information" and "zero value" in s["text"] for s in sts)
    # A memo statement citing only EV- items approved in Section 2 carries over as "Approved in Section 2"
    carried = [s for s in sts if s.get("note") == "Approved in Section 2"]
    assert carried and all(s["status"] == "Approved" and s["carried_over"] for s in carried)
    assert all(all(r.startswith("EV-") for r in s["refs"]) for s in carried)

    # Section 6: final PDF blocked while statements are Pending
    pending = c.post(f"/api/deals/{did}/exports/memo", json={"analyst_name": "Ana"})
    assert pending.status_code == 409 and "Pending" in pending.json()["message"]
    business = next(s for s in sts if any(r.startswith("EV-") for r in s["refs"]))
    src = c.get(f"/api/deals/{did}/evidence/{business['refs'][0]}", params={"statement_id": business["id"]}).json()
    assert src["location_status"] == "Located" and src["image"].startswith("data:image/png;base64,")
    csv_src = c.get(f"/api/deals/{did}/evidence/CSV-EBITDA_MARGIN-Q1-FY2026").json()
    assert csv_src["display"] == "0.00%" and "zero value" in csv_src["flags"] and csv_src["cell"] == "Intel!D12"
    # Section 6 bulk approve: approves every Pending statement (name required); carried-over ones are already Approved
    assert c.post(f"/api/deals/{did}/memo/bulk", json={"action": "approve_pending", "analyst_name": ""}).status_code == 422
    pending_before = sum(1 for s in sts if s["status"] == "Pending")
    bulk6 = c.post(f"/api/deals/{did}/memo/bulk", json={"action": "approve_pending", "analyst_name": "Ana"}).json()
    assert bulk6["changed"] == pending_before
    assert all(s["status"] != "Pending" for s in c.get(f"/api/deals/{did}/section5").json()["statements"])
    corrected = c.post(f"/api/deals/{did}/memo/statements/{business['id']}/action",
                       json={"action": "correct", "analyst_name": "Ana", "text": "Intel designs and manufactures semiconductors."}).json()
    assert corrected["status"] == "Pending"
    assert c.post(f"/api/deals/{did}/exports/memo", json={"analyst_name": "Ana"}).status_code == 409
    c.post(f"/api/deals/{did}/memo/statements/{business['id']}/action", json={"action": "approve", "analyst_name": "Ana"})

    # optional support check is advisory only
    before = {s["id"]: s["status"] for s in c.get(f"/api/deals/{did}/section5").json()["statements"]}
    c.post(f"/api/deals/{did}/support-check/run")
    after = c.get(f"/api/deals/{did}/section5").json()["statements"]
    assert {s["id"]: s["status"] for s in after} == before

    memo = c.post(f"/api/deals/{did}/exports/memo", json={"analyst_name": "Ana"})
    assert memo.status_code == 200 and memo.content[:4] == b"%PDF"
    assert "Intel_Corporation_CreditMemo_" in memo.headers["content-disposition"]
    audit_pdf = c.post(f"/api/deals/{did}/exports/audit")
    assert audit_pdf.status_code == 200 and "AuditTrail" in audit_pdf.headers["content-disposition"]

    # audit trail is append-only and the API key never reaches stored data
    trail = c.get(f"/api/deals/{did}/audit-trail").json()
    assert [a["seq"] for a in trail] == list(range(1, len(trail) + 1))
    assert {"llm_output", "number_check", "s3_approval", "s3_approval_revoked", "memo_review"} <= {a["type"] for a in trail}
    for f in (env / "data").rglob("*.json"):
        assert "SECRETKEY" not in f.read_text(encoding="utf-8")


def test_edit_and_delete_deal(env, fake_llm):
    c = TestClient(create_app())
    deal = c.post("/api/deals", json=INTAKE).json()
    did = deal["deal_id"]
    assert deal["financial"]["status"] == "connected"

    # edit the loan request (same borrower): fields update, financial stays connected
    edited = c.put(f"/api/deals/{did}", json={**INTAKE, "amount": "750000000", "tenor": "7 years"})
    assert edited.status_code == 200
    body = edited.json()
    assert body["intake"]["DI-AMOUNT"]["display"] == "750000000 USD" and body["intake"]["DI-TENOR"]["display"] == "7 years"
    assert body["financial"]["status"] == "connected"

    # changing the borrower re-connects the external database for the new name
    rebranded = c.put(f"/api/deals/{did}", json={**INTAKE, "borrower": "Micron Technology"}).json()
    assert rebranded["intake"]["DI-BORROWER"]["display"] == "Micron Technology"
    assert rebranded["financial"]["status"] == "connected"
    assert c.get(f"/api/deals/{did}/financial").json()["sheet"] == "Micron"
    # a borrower that is not in the database: connection error, and the earlier company's figures are removed
    unknown = c.put(f"/api/deals/{did}", json={**INTAKE, "borrower": "Acme Semiconductors"}).json()
    assert unknown["financial"]["status"] == "error" and "No company" in unknown["financial"]["error"]
    assert c.get(f"/api/deals/{did}/financial").status_code == 404

    # validation still applies on edit
    bad = c.put(f"/api/deals/{did}", json={**INTAKE, "amount": "abc"})
    assert bad.status_code == 422 and any(f["field"] == "amount" for f in bad.json()["fields"])

    # audit records the edits
    trail = c.get(f"/api/deals/{did}/audit-trail").json()
    assert any(a["type"] == "deal_edited" for a in trail)

    # delete removes the deal from the list and from disk
    assert c.delete(f"/api/deals/{did}").json() == {"deleted": True, "deal_id": did}
    assert all(d["deal_id"] != did for d in c.get("/api/deals").json())
    assert c.get(f"/api/deals/{did}").status_code == 404
    assert not (env / "data" / "deals" / did).exists()
    # deleting a non-existent deal is a 404
    assert c.delete(f"/api/deals/{did}").status_code == 404
