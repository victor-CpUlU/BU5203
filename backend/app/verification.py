"""Number_Verifier, Reference_Validator and text rules (Req 11.5, 15, 17.9, 18.12, 19)."""
from __future__ import annotations

import copy
import re

MONTHS = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
EXCLUDE_PATTERNS = [
    r"\bQ[1-4][\s\-]?(?:FY)?\d{4}\b",
    r"\bFY\s?\d{4}\b",
    r"\b\d{1,2}M-FY\d{4}\b",
    MONTHS + r"\.?\s+\d{1,2},?\s+\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\bEV-\d+\b",
    r"\bCSV-[A-Z0-9_]+-Q[1-4]-(?:FY)?\d{4}\b",
    r"\bF[CAT]-[A-Z0-9_]+(?:-[A-Z0-9_]+)*\b",
    r"\bDI-[A-Z_]+\b",
    r"\bS3-\d+\b",
    r"\bM\d+\b",
    r"\bRISK-\d+\b",
    r"\bP[1-5]\b",
    r"\bSection\s+\d+[A-Z]?\b",
    r"\b(?:[1-9]|1\d|20)\s+(?:quarters?|periods?)\b",
]
EXCLUDE_RE = re.compile("|".join(f"(?:{p})" for p in EXCLUDE_PATTERNS), re.IGNORECASE)
FIGURE_RE = re.compile(
    r"(?<![\w.])([+\-\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
    r"(%|x(?![A-Za-z])|\s?(?:percentage points?|percent|pp|times|days?)(?![A-Za-z]))?"
)
UNIT_MAP = {"%": "%", "x": "x", "percent": "%", "times": "x", "pp": "pp", "percentage point": "pp",
            "percentage points": "pp", "day": "days", "days": "days"}

DIRECTION_WORDS = re.compile(r"\b(increas\w*|decreas\w*|rose|rise[sn]?|fell|fall\w*|up|down|improv\w*|deteriorat\w*|declin\w*|grew|grow\w*|higher|lower)\b", re.I)
# Keyed by the names used in dataset["unavailable_metrics"] (canonical labels plus Project Details names).
UNAVAILABLE_NAME_PATTERNS = {
    "Revenue": r"\brevenue(?!\s+growth)\b",
    "EBITDA": r"(?<!debt/)(?<!debt / )\bebitda\b(?!\s+(?:margin|\(ltm\)|excl))",
    "Net Profit Margin": r"\bnet profit margin\b",
    "Total Debt": r"\btotal debt\b",
    "Net Debt": r"\bnet debt\b",
    "Debt/Equity": r"\bdebt\s?/\s?equity\b",
    "Cash & Cash Equivalents": r"(?<!operating )(?<!free )\bcash\b(?!\s+(?:flow|conversion|generation))",
    "Short-Term Debt": r"\bshort[- ]term debt\b",
    "Quick Ratio": r"\bquick ratio\b",
    "Capital Expenditure": r"\b(capital expenditure|capex)\b",
    "Free Cash Flow": r"\bfree cash flow\b",
    "Interest Expense": r"\binterest expense\b",
}
DECISION_RE = re.compile(
    r"\b(recommend\w*|we approve|approve (?:the|this) (?:facility|loan|request)|decline (?:the|this) (?:facility|loan|request)|"
    r"should be (?:approved|declined)|approve with conditions|approved with conditions|credit decision is)\b", re.I)


# --------------------------------------------------------------------------- text rules
def count_sentences(text: str) -> int:
    return max(1, len(re.findall(r"[.!?](?=\s|$)", text.strip()))) if text.strip() else 0


def has_decision_language(text: str) -> bool:
    return bool(DECISION_RE.search(text or ""))


# --------------------------------------------------------------------------- figures
def normalise_figure(number: str, unit: str | None) -> tuple[str, str | None]:
    n = number.replace(",", "").replace("\u2212", "-").lstrip("+")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    if n in ("-0", ""):
        n = "0"
    u = UNIT_MAP.get(unit.strip().lower()) if unit and unit.strip() else None
    return n, u


def extract_figures(text: str) -> list[dict]:
    masked = EXCLUDE_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    out = []
    for m in FIGURE_RE.finditer(masked):
        number, unit = m.group(1), m.group(2)
        if not unit and re.fullmatch(r"\d{4}", number) and 1900 <= int(number) <= 2100:
            continue  # standalone year
        n, u = normalise_figure(number, unit)
        out.append({"raw": m.group(0).strip(), "number": n, "unit": u})
    return out


def _abs(n: str) -> str:
    return n[1:] if n.startswith("-") else n


# --------------------------------------------------------------------------- Number_Verifier
def verify_statement(stmt: dict, ctx: dict, mode: str = "S3") -> dict:
    """Check every figure and comparison claim in `stmt` against supplied data. Pure: inputs are not mutated.

    ctx: csv (id -> entry with display/unit), comparisons (list), evidence (EV id -> record with excerpt),
         intake (DI id -> {"value": str}), unavailable (list of names).
    """
    stmt = copy.deepcopy(stmt)
    refs = stmt.get("refs") or []
    text = stmt.get("text") or ""
    exact: set[tuple[str, str | None]] = set()
    absolute: set[tuple[str, str | None]] = set()
    unmatched: list[dict] = []

    csv = ctx.get("csv", {})
    for r in refs:
        e = csv.get(r)
        if e and e.get("value") is not None:
            for f in extract_figures(e["display"]):
                exact.add((f["number"], f["unit"]))
                if e.get("unit") == "days":
                    exact.add((f["number"], "days"))
                    exact.add((f["number"], None))
        ev = ctx.get("evidence", {}).get(r)
        if ev:
            for f in extract_figures(ev.get("excerpt", "")):
                exact.add((f["number"], f["unit"]))
        fc = ctx.get("forecast", {}).get(r)
        if fc:  # backend forecast value, forecast assumption or analyst threshold: quote its display exactly
            for f in extract_figures(fc.get("display", "")):
                exact.add((f["number"], f["unit"]))
        if mode in ("S4", "S5", "S6") and r in ctx.get("intake", {}):
            for f in extract_figures(str(ctx["intake"][r].get("display", ctx["intake"][r].get("value", "")))):
                exact.add((f["number"], f["unit"]))

    unit_for = {"percent": "pp", "multiple": "x", "days": "days", "amount": "%"}

    def add_change(c: dict) -> None:
        if c.get("change") is None:
            return
        for f in extract_figures(c["change_display"]):
            absolute.add((_abs(f["number"]), unit_for[c["unit"]]))

    cited = set(refs)
    for c in ctx.get("comparisons", []):
        if c["from_evidence_id"] in cited and c["to_evidence_id"] in cited:
            add_change(c)

    for claim in stmt.get("claims") or []:
        match = next((c for c in ctx.get("comparisons", []) if c["metric_key"] == claim.get("metric_key")
                      and c["from_period"] == claim.get("from_period") and c["to_period"] == claim.get("to_period")), None)
        label = f"{claim.get('metric_key')} {claim.get('from_period')}->{claim.get('to_period')}"
        if not match:
            unmatched.append({"value": label, "reason": "no Comparison_Record for this metric and these periods"})
            continue
        add_change(match)
        if claim.get("direction") != match["direction"]:
            unmatched.append({"value": label, "reason": "direction differs"})
            continue
        qc = (claim.get("quoted_change") or "").strip()
        if qc and match.get("change") is None:
            if qc.lower() != (match.get("change_display") or "").lower():  # e.g. a change from zero is "Not computable"
                unmatched.append({"value": qc, "reason": "change differs"})
        elif qc:
            figs = extract_figures(qc)
            want = [(_abs(f["number"]), f["unit"]) for f in extract_figures(match["change_display"])]
            if not figs or (_abs(figs[0]["number"]), figs[0]["unit"]) not in want:
                unmatched.append({"value": qc, "reason": "change differs"})

    for f in extract_figures(text):
        key = (f["number"], f["unit"])
        if key in exact or (_abs(f["number"]), f["unit"]) in absolute:
            continue
        unmatched.append({"value": f["raw"], "reason": "no matching cited value"})

    lower = text.lower()
    if "not available in database" not in lower and "not assessable" not in lower:
        figures_or_direction = bool(extract_figures(text)) or bool(DIRECTION_WORDS.search(text))
        for name, pattern in UNAVAILABLE_NAME_PATTERNS.items():
            if name in ctx.get("unavailable", []) and re.search(pattern, lower) and figures_or_direction:
                unmatched.append({"value": name, "reason": "no matching cited value"})

    return {"mark": "Numbers verified" if not unmatched else "Number mismatch", "unmatched": unmatched}


# --------------------------------------------------------------------------- Reference_Validator
def validate_refs(cited: list[tuple[str, str]], known: set[str]) -> dict:
    """Exact, case-sensitive membership of every cited Evidence_ID (Req 19.1-19.2)."""
    unknown = [{"owner_id": owner, "evidence_id": ev} for owner, ev in cited if ev not in known]
    return {"result": "pass" if not unknown else "fail", "unknown": unknown}
