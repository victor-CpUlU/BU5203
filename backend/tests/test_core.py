"""Number_Verifier, Reference_Validator, passage locator, redaction, prompts and the LLM runner (Req 1.8, 7, 15, 19, 25, 27)."""
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app import llm
from app.documents import locate, normalise
from app.llm import TaskSpec, extract_instruction_prompts, load_prompts, run_llm_task
from app.security import redact
from app.settings import get_settings
from app.verification import extract_figures, validate_refs, verify_statement
from conftest import ROOT, make_pdf

CTX = {
    "csv": {"CSV-DSCR-Q1-2026": {"display": "0.00x", "unit": "multiple", "value": "0.00"},
            "CSV-DSCR-Q2-2026": {"display": "0.64x", "unit": "multiple", "value": "0.64"},
            "CSV-DSO-Q2-2026": {"display": "22.8", "unit": "days", "value": "22.8"}},
    "comparisons": [{"metric_key": "DSCR", "from_period": "Q1-2026", "to_period": "Q2-2026", "unit": "multiple", "change": "0.64",
                     "change_display": "+0.64x", "direction": "up", "from_evidence_id": "CSV-DSCR-Q1-2026", "to_evidence_id": "CSV-DSCR-Q2-2026"}],
    "evidence": {}, "intake": {}, "unavailable": ["Revenue", "EBITDA", "Cash"],
}


def test_verifier_matches_and_mismatches():
    ok = {"text": "DSCR rose from 0.00x in Q1-2026 to 0.64x in Q2-2026 (+0.64x).", "refs": ["CSV-DSCR-Q1-2026", "CSV-DSCR-Q2-2026"],
          "claims": [{"metric_key": "DSCR", "from_period": "Q1-2026", "to_period": "Q2-2026", "direction": "up", "quoted_change": "+0.64x"}]}
    assert verify_statement(ok, CTX)["mark"] == "Numbers verified"
    bad = {**ok, "text": "DSCR rose to 0.80x in Q2-2026."}
    r = verify_statement(bad, CTX)
    assert r["mark"] == "Number mismatch" and r["unmatched"][0]["value"] == "0.80x"
    wrong_dir = {**ok, "claims": [{**ok["claims"][0], "direction": "down"}]}
    assert verify_statement(wrong_dir, CTX)["unmatched"][0]["reason"] == "direction differs"
    assert bad["text"] == "DSCR rose to 0.80x in Q2-2026."  # text unchanged


def test_verifier_unavailable_metric_and_exclusions():
    r = verify_statement({"text": "Revenue increased strongly in FY2025.", "refs": []}, CTX)
    assert r["mark"] == "Number mismatch"
    assert verify_statement({"text": "Revenue is Not available in database.", "refs": []}, CTX)["mark"] == "Numbers verified"
    assert verify_statement({"text": "DSO was 22.8 days in Q2-2026 over 4 quarters.", "refs": ["CSV-DSO-Q2-2026"]}, CTX)["mark"] == "Numbers verified"
    assert [f["number"] for f in extract_figures("See EV-012, CSV-DSCR-Q2-2026, Section 5 and 2026; value 4.11x")] == ["4.11"]


def test_reference_validator():
    known = {"EV-001", "CSV-DSCR-Q2-2026", "DI-AMOUNT"}
    assert validate_refs([("s", "EV-001"), ("s", "DI-AMOUNT")], known)["result"] == "pass"
    r = validate_refs([("s", "EV-999"), ("s", "ev-001")], known)
    assert r["result"] == "fail" and len(r["unknown"]) == 2


def test_passage_locator(tmp_path):
    pdf = make_pdf(tmp_path / "t.pdf", ["Intel operates manufact-\nuring facilities in \u201cArizona\u201d \u2013 and Ireland.", "Other page text."])
    hit = locate(pdf, 1, 'Intel operates manufacturing facilities in "Arizona" - and Ireland.', 2)
    assert hit["status"] == "Located" and hit["rects"]
    assert locate(pdf, 2, "Intel operates manufacturing", 2)["status"] == "Not located"
    assert locate(pdf, 5, "x", 2)["issue"] == "Invalid reference: page out of range"
    assert locate(pdf, 1, "   ", 2)["issue"] == "Empty excerpt"


@given(st.text(max_size=200))
def test_normalise_idempotent(s):
    assert normalise(normalise(s)) == normalise(s)


@given(st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=8, max_size=40), st.text(max_size=60))
def test_redaction_removes_every_window(secret, noise):
    text = noise + secret + noise + secret[2:10]
    out = redact(text, [secret])
    assert all(secret[i:i + 8] not in out for i in range(len(secret) - 7))


def test_prompt_files_match_instructions():
    files = load_prompts(ROOT / "backend" / "app" / "prompts")
    instr = extract_instruction_prompts((ROOT / "Instructions.md").read_text(encoding="utf-8"))
    assert set(files) == set(instr) == {"MASTER", "S2A", "S2B", "S3", "S4", "S5", "S6"}
    for pid in files:
        assert files[pid].version == instr[pid].version and files[pid].text == instr[pid].text, pid
    text = (ROOT / "Instructions.md").read_text(encoding="utf-8")
    assert "Layer 2" not in text and "Layer 7" not in text


def test_missing_prompt_file(tmp_path):
    with pytest.raises(llm.PromptLoadError) as exc:
        load_prompts(tmp_path)
    assert exc.value.prompt_id == "MASTER"


class Scripted:
    model_name = "fake"

    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def complete(self, system, user, timeout_s):
        self.calls.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _run(env, monkeypatch, responses, **spec):
    client = Scripted(responses)
    monkeypatch.setattr(llm, "client_factory", lambda s: client)
    prompts = load_prompts(ROOT / "backend" / "app" / "prompts")
    audits = []
    res = run_llm_task(TaskSpec("S6", **spec), {"statements": []}, prompts, get_settings(), {"EV-001"}, audits.append)
    return res, client, audits


def test_runner_retries_with_errors(env, monkeypatch):
    good = json.dumps({"assessments": []})
    res, client, audits = _run(env, monkeypatch, ["not json", good])
    assert res["ok"] and len(client.calls) == 2 and "VALIDATION ERRORS FROM PREVIOUS ATTEMPT" in client.calls[1]
    assert len(audits) == 2 and audits[0]["input_hash"] == audits[1]["input_hash"]
    res, client, _ = _run(env, monkeypatch, ["{}", "{}", "{}"])
    assert not res["ok"] and len(client.calls) == 3


def test_runner_transport_rule(env, monkeypatch):
    err = llm.LLMTransportError("timeout")
    res, client, _ = _run(env, monkeypatch, [err, json.dumps({"assessments": []})])
    assert not res["ok"] and len(client.calls) == 1  # Sections 3-6: stop
    res, client, _ = _run(env, monkeypatch, [err, json.dumps({"assessments": []})], retry_transport=True)
    assert res["ok"] and len(client.calls) == 2  # Section 2: counts against the retry budget


def test_runner_soft_unknown_refs(env, monkeypatch):
    out = json.dumps({"assessments": [{"statement_id": "M1", "assessment": "Supported", "reason": "ok"}]})
    refs = lambda o: [("M1", "EV-404")]
    res, _, _ = _run(env, monkeypatch, [out] * 3, refs=refs)
    assert not res["ok"]
    res, _, _ = _run(env, monkeypatch, [out] * 3, refs=refs, soft_unknown_refs=True)
    assert res["ok"] and res["unknown_refs"] == [("M1", "EV-404")]


def test_extract_json_from_cli_output():
    out = "\x1b[32m> Thinking...\x1b[0m\nHere you go:\n{\"assessments\": [{\"a\": {\"b\": 1}}]}\nDone."
    assert json.loads(llm.extract_json_object(out)) == {"assessments": [{"a": {"b": 1}}]}
    assert json.loads(llm.extract_json_object("```json\n{\"x\": 1}\n```")) == {"x": 1}


def test_kiro_cli_settings_and_missing_binary(env):
    (env / ".env").write_text("LLM_PROVIDER=kiro_cli\nKIRO_CLI_PATH=definitely-not-installed-kiro\n")
    s = get_settings()
    assert s.llm_settings_problems() == []
    client = llm.make_client(s)
    with pytest.raises(llm.LLMTransportError, match="Kiro CLI not found"):
        client.complete("sys", "user", 5)


def test_kiro_cli_subprocess(env, tmp_path):
    """A stand-in CLI script proves the prompt goes via stdin and the JSON is read from stdout."""
    import sys
    script = tmp_path / "fake_kiro.py"
    script.write_text("import sys,json\ndata=sys.stdin.read()\nassert '--no-interactive' in sys.argv\n"
                      "print('status line')\nprint(json.dumps({'got_task': '=== TASK ===' in data}))\n")
    bat = tmp_path / "fake_kiro.bat"
    bat.write_text(f'@"{sys.executable}" "{script}" %*\n')
    client = llm.KiroCliClient("", "", str(bat))
    assert json.loads(client.complete("SYSTEM", "TASK BODY", 30)) == {"got_task": True}


def test_missing_settings_block_calls(env, monkeypatch):
    (env / ".env").write_text("LLM_PROVIDER=unknown\n")
    with pytest.raises(Exception) as exc:
        llm.make_client(get_settings())
    assert "LLM_PROVIDER" in str(exc.value) and "LLM_API_KEY" in str(exc.value)
