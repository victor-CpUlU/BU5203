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
    # Section 2D: the external financial database is auto-connected at deal creation (no analyst action)
    assert deal["financial"]["status"] == "connected" and deal["financial"]["confirmed"] is True
    fin = c.get(f"/api/deals/{did}/financial").json()
    assert "Database has no borrower identifier" in fin["information_gaps"]
    assert len(fin["comparisons"]) == 30
    assert len(c.get(f"/api/deals/{did}/dashboard").json()["panels"]) == 5

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

    # Section 4 is gated on Section 3 approval
    assert c.post(f"/api/deals/{did}/section4/run").status_code == 409

    # Section 3: analysis, number checks, approval gate
    s3 = c.post(f"/api/deals/{did}/section3/run").json()
    assert s3["statements"] and all(s["verification"]["mark"] == "Numbers verified" for s in s3["statements"])
    assert all(d["result"].startswith("Not assessable") for d in s3["divergences"])
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
    assert any("Pro-forma debt service" in s["text"] and s["label"] == "NOT VERIFIED" for s in sts)
    assert any(s["subsection"] == "conflicting_information" and "zero value" in s["text"] for s in sts)

    # Section 6: final PDF blocked while statements are Pending
    pending = c.post(f"/api/deals/{did}/exports/memo", json={"analyst_name": "Ana"})
    assert pending.status_code == 409 and "Pending" in pending.json()["message"]
    business = next(s for s in sts if any(r.startswith("EV-") for r in s["refs"]))
    src = c.get(f"/api/deals/{did}/evidence/{business['refs'][0]}", params={"statement_id": business["id"]}).json()
    assert src["location_status"] == "Located" and src["image"].startswith("data:image/png;base64,")
    csv_src = c.get(f"/api/deals/{did}/evidence/CSV-DSCR-Q1-2026").json()
    assert csv_src["display"] == "0.00x" and "zero value" in csv_src["flags"]
    for s in sts:
        if s["status"] == "Pending":
            assert c.post(f"/api/deals/{did}/memo/statements/{s['id']}/action", json={"action": "approve", "analyst_name": "Ana"}).status_code == 200
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
    rebranded = c.put(f"/api/deals/{did}", json={**INTAKE, "borrower": "Acme Semiconductors"}).json()
    assert rebranded["intake"]["DI-BORROWER"]["display"] == "Acme Semiconductors"
    assert rebranded["financial"]["status"] == "connected"

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
