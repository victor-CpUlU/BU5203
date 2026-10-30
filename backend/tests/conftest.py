import json
import socket
import sys
from pathlib import Path

import fitz
import pytest
from hypothesis import settings as hsettings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import llm, settings as app_settings  # noqa: E402

hsettings.register_profile("default", max_examples=100, deadline=None)
hsettings.load_profile("default")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block outbound connections (tests run with a fake LLM and no API key)."""
    real = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(f"Network access blocked in tests: {address}")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data folder and .env with a fake provider configured."""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=openai\nLLM_MODEL=fake-model\nLLM_API_KEY=sk-test-SECRETKEY-1234567890\nSUPPORT_CHECK_ENABLED=true\n")
    monkeypatch.setitem(app_settings._overrides, "data_dir", tmp_path / "data")
    monkeypatch.setitem(app_settings._overrides, "env_path", env_file)
    for k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "SUPPORT_CHECK_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        # Built-in Unicode font so typographic quotes and dashes are real characters in the PDF.
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=11, fontname="china-s")
    doc.save(str(path))
    doc.close()
    return path


def input_of(user: str) -> dict:
    body = user.split("\nINPUT:\n", 1)[1]
    body = body.split("\n\nVALIDATION ERRORS FROM PREVIOUS ATTEMPT", 1)[0]
    return json.loads(body)


class SmartFakeLLM:
    """Builds schema-valid answers from the real input so the whole pipeline can run without a provider."""
    model_name = "fake-model"

    def __init__(self):
        self.calls = []

    def complete(self, system, user, timeout_s):
        self.calls.append(user)
        data = input_of(user)
        head = user.split("\n", 1)[0]
        if head.startswith("SECTION 2A"):
            return json.dumps(self._s2(data, "business_description", "Intel designs and manufactures semiconductor products."))
        if head.startswith("SECTION 2B"):
            return json.dumps(self._s2(data, "existing_debt_obligations", "Intel had $2.5 billion of senior notes outstanding."))
        if head.startswith("SECTION 3"):
            return json.dumps(self._s3(data))
        if head.startswith("SECTION 4"):
            return json.dumps(self._s4(data))
        if head.startswith("SECTION 5"):
            return json.dumps(self._s5(data))
        if head.startswith("SECTION 6"):
            return json.dumps({"assessments": [{"statement_id": s["statement_id"], "assessment": "Supported", "reason": "The excerpt states it."}
                                               for s in data["statements"]]})
        raise AssertionError("unknown prompt")

    @staticmethod
    def _s2(data, field, statement):
        pages = data["pages"]
        import re
        m = re.search(r"\[\[DOC (D\d+) \| [^|]+ \| PAGE (\d+)\]\]\n(.*?)(?=\n\n\[\[DOC|\Z)", pages, re.S)
        doc_id, page, text = m.group(1), int(m.group(2)), m.group(3)
        excerpt = " ".join(text.split())[:120]
        if "2.5 billion" in statement and "$2.5 billion" not in excerpt:
            statement = "Intel had senior notes outstanding."
        return {"items": [{"field": field, "statement": statement, "doc_id": doc_id, "page": page,
                           "section_heading": "Item 1. Business", "excerpt": excerpt, **({"item_key": "senior notes", "as_of": None} if "debt" in field else {})}]}

    @staticmethod
    def _s3(data):
        metrics = {m["metric_key"]: m for m in data["financial_dataset"]["metrics"]}
        comps = data["comparison_records"]

        def stmt(key):
            m = metrics[key]
            last, prev = m["values"][-1], m["values"][-2]
            c = next(c for c in comps if c["metric_key"] == key and c["to_period"] == last["period"])
            return {"text": f"{m['label']} moved from {prev['display']} in {prev['period']} to {last['display']} in {last['period']} ({c['change']}).",
                    "label": "Sourced", "refs": [prev["evidence_id"], last["evidence_id"]],
                    "claims": [{"metric_key": key, "from_period": c["from_period"], "to_period": c["to_period"], "direction": c["direction"], "quoted_change": c["change"]}]}

        panels = [{"panel": p["panel"], "statements": [stmt(k) for k in p["metrics"] if k in metrics]} for p in data["panels"]]
        nv = {"text": "No weakening evidence was identified in the inputs.", "label": "NOT VERIFIED", "refs": [], "claims": []}
        rep = [{"dimension": d, "supports": [stmt("DSCR")], "weakens": [nv]} for d in data["repayment_dimensions"]]
        forecast = []
        for sc in (data.get("forecast") or {}).get("scenarios", []):
            v = next(m for m in sc["metrics"] if m["metric_key"] == "DSCR")["values"][0]
            forecast.append({"text": f"In the {sc['label']}, the projected DSCR is {v['display']} (backend projection).",
                             "label": "ASSUMPTION", "refs": [v["evidence_id"]], "claims": []})
        return {"panels": panels, "cross_metric": [], "repayment_capacity": rep, "forecast": forecast}

    @staticmethod
    def _s4(data):
        m = {x["metric_key"]: x for x in data["financial_dataset"]["metrics"]}
        risks = []
        for i, key in enumerate(["DEBT_EBITDA", "DSCR", "INTEREST_COVERAGE"], start=1):
            v = m[key]["values"][-1]
            risks.append({"rank": i, "identified_risk": f"Risk on {m[key]['label']}", "category": "Financial", "impact": "High", "likelihood": "High",
                          "evidence": {"text": f"{m[key]['label']} was {v['display']} in {v['period']}.", "refs": [v["evidence_id"]]},
                          "time_horizon": "Q3-2025 to Q2-2026 against the requested tenor", "business_context": None,
                          "mitigants": ["Limit further debt"],
                          "terms": [{"term_type": "Covenant", "text": "Maximum Debt/EBITDA of 4.0x. Illustrative; analyst to calibrate against credit policy.",
                                     "label": "ASSUMPTION", "refs": []}]})
        return {"risks": risks, "limitations": []}

    @staticmethod
    def _s5(data):
        risk = data["risks"][0]
        sections = []
        for sec in data["memo_outline"]:
            subs = []
            for ss in sec["subsections"]:
                if ss["key"] == "borrower_and_facility":
                    st = [{"text": f"The borrower requests {data['deal_intake']['DI-AMOUNT']}.", "label": "Sourced", "refs": ["DI-AMOUNT"]}]
                elif ss["key"] == "financial_risks":
                    st = [{"text": risk["evidence"]["text"], "label": "Sourced", "refs": risk["evidence"]["refs"]}]
                elif ss["key"] == "business_model_and_industry" and data["business_information"]:
                    b = data["business_information"][0]
                    st = [{"text": b["statement"], "label": "Sourced", "refs": [b["evidence_id"]]}]
                else:
                    st = [{"text": "Not available in the documents provided.", "label": "NOT VERIFIED", "refs": []}]
                subs.append({"key": ss["key"], "statements": st})
            sections.append({"number": sec["number"], "title": sec["title"], "subsections": subs})
        return {"sections": sections}


@pytest.fixture
def fake_llm(monkeypatch):
    fake = SmartFakeLLM()
    monkeypatch.setattr(llm, "client_factory", lambda s: fake)
    return fake
