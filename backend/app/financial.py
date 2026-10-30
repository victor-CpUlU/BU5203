"""Financial database handling (Req 8-14).

The database is the semiconductor workbook (.xlsx): one KPI sheet per company whose cells are the
workbook's own formulas over a "<Company> Inputs" sheet. Ratios are taken from the workbook as it
defines them; the backend never defines a credit ratio. If the workbook has no saved formula results,
the backend evaluates the workbook's own formulas (see workbook.py). A legacy single-borrower CSV is
still accepted.

The only arithmetic here is the period-over-period change used to label direction and to verify
AI comparison claims (Comparison_Records), and the divergence-pattern check built on those records.
Forecasts and scenarios are in forecast.py.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from .workbook import BLANK, Workbook, WorkbookError, XlErr, excel_date

CANONICAL = [
    ("REVENUE", "Revenue"),
    ("REVENUE_GROWTH", "Revenue Growth (Q/Q)"),
    ("REVENUE_GROWTH_YOY", "Revenue Growth (Y/Y)"),
    ("EBITDA", "EBITDA"),
    ("EBITDA_LTM", "EBITDA (LTM)"),
    ("EBITDA_MARGIN", "EBITDA Margin"),
    ("EBITDA_EXCL_IMPAIRMENT", "EBITDA excl. Asset Impairment Charges"),
    ("TOTAL_DEBT", "Total Debt"),
    ("NET_DEBT", "Net Debt"),
    ("DEBT_EQUITY", "Debt/Equity"),
    ("DEBT_EBITDA", "Debt/EBITDA (LTM)"),
    ("CASH", "Cash & Cash Equivalents"),
    ("SHORT_TERM_DEBT", "Short-Term Debt"),
    ("WORKING_CAPITAL", "Working Capital"),
    ("CURRENT_RATIO", "Current Ratio"),
    ("QUICK_RATIO", "Quick Ratio"),
    ("OPERATING_CASH_FLOW", "Operating Cash Flow"),
    ("OCF_MARGIN", "Operating Cash Flow Margin"),
    ("CAPEX", "Capital Expenditure"),
    ("FCF", "Free Cash Flow"),
    ("DSO", "Days Sales Outstanding (DSO)"),
    ("INTEREST_EXPENSE", "Interest Expense"),
    ("INTEREST_COVERAGE", "Interest Coverage"),
    ("DSCR", "Debt Service Coverage Ratio (DSCR)"),
]
CANONICAL_KEYS = [k for k, _ in CANONICAL]
CANONICAL_LABEL = dict(CANONICAL)
# Labels as written in the workbook or the legacy CSV that map to a canonical key.
LABEL_ALIASES = {
    "revenue growth": "REVENUE_GROWTH",
    "debt/ebitda": "DEBT_EBITDA",
    "debt-service coverage ratio (dscr)": "DSCR",
    "net revenue": "REVENUE",
}
LABEL_MAP = {**{label.lower(): key for key, label in CANONICAL}, **LABEL_ALIASES}
# Workbook rows that repeat another row (kept out of the dataset).
SKIP_LABELS = {"free cash flow (check vs. inputs / company-reported)"}
# Present for some companies only; not reported as a gap when absent.
OPTIONAL_KEYS = {"EBITDA_EXCL_IMPAIRMENT"}
# Supporting rows: charted and citable, but the AI need not comment on each one.
MEMO_KEYS = {"REVENUE_GROWTH_YOY", "EBITDA_LTM", "EBITDA_EXCL_IMPAIRMENT"}
LOWER_IS_BETTER = {"DEBT_EBITDA", "DSO", "TOTAL_DEBT", "NET_DEBT", "DEBT_EQUITY", "SHORT_TERM_DEBT", "INTEREST_EXPENSE"}
NEUTRAL = {"CAPEX"}  # neither direction is better in itself
NEGATIVE_OK = {"REVENUE_GROWTH", "REVENUE_GROWTH_YOY", "NET_DEBT"}  # negative net debt = net cash

PANELS = [
    ("profitability", "Profitability",
     ["REVENUE", "REVENUE_GROWTH", "REVENUE_GROWTH_YOY", "EBITDA", "EBITDA_LTM", "EBITDA_EXCL_IMPAIRMENT", "EBITDA_MARGIN"], ["Net Profit Margin"]),
    ("leverage", "Leverage", ["TOTAL_DEBT", "NET_DEBT", "DEBT_EQUITY", "DEBT_EBITDA"], []),
    ("liquidity", "Liquidity", ["CASH", "SHORT_TERM_DEBT", "WORKING_CAPITAL", "CURRENT_RATIO", "QUICK_RATIO"], []),
    ("cash_flow", "Cash Flow", ["OPERATING_CASH_FLOW", "OCF_MARGIN", "CAPEX", "FCF", "DSO"], []),
    ("debt_servicing", "Debt Servicing", ["INTEREST_EXPENSE", "INTEREST_COVERAGE", "DSCR"], []),
]
UNAVAILABLE_METRICS = [m for p in PANELS for m in p[3]]

# Divergence patterns from the Project Details. Each named metric must be a Canonical_Metric in
# the dataset; no proxies are substituted (REVENUE_GROWTH is not "Revenue").
NAME_TO_CANONICAL = {"Revenue": "REVENUE", "EBITDA": "EBITDA", "Operating Cash Flow": "OPERATING_CASH_FLOW",
                     "Total Debt": "TOTAL_DEBT", "DSCR": "DSCR", "Cash": "CASH", "Short-term Debt": "SHORT_TERM_DEBT"}
DIVERGENCE_PATTERNS = [
    ("P1", "Revenue up with EBITDA down (possible margin compression)", ["Revenue", "EBITDA"], ["up", "down"]),
    ("P2", "Revenue up with Operating Cash Flow down (weaker cash conversion)", ["Revenue", "Operating Cash Flow"], ["up", "down"]),
    ("P3", "Debt up with EBITDA down (increasing leverage)", ["Total Debt", "EBITDA"], ["up", "down"]),
    ("P4", "Debt up with DSCR down (weakening debt-servicing capacity)", ["Total Debt", "DSCR"], ["up", "down"]),
    ("P5", "Cash down with Short-term Debt up (increasing liquidity pressure)", ["Cash", "Short-term Debt"], ["down", "up"]),
]

FLAG_ORDER = ["unparseable value", "blank in database", "formula error", "not meaningful (n/m)",
              "zero value", "negative value", "large swing", "unit not stated"]
NOT_IN_DB = "Not available in database"

PCT_RE = re.compile(r"^(-?\d+(?:\.(\d+))?)%$")
MULT_RE = re.compile(r"^(-?\d+(?:\.(\d+))?)x$")
PLAIN_RE = re.compile(r"^(-?\d+(?:\.(\d+))?)$")
HEADER_RE = re.compile(r"^Q([1-4]) (\d{4}) \((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}) (\d{4})\)$")


class LoadError(Exception):
    pass


# --------------------------------------------------------------------------- values
def parse_cell(text: str | None, metric_key: str) -> dict:
    """Parse one CSV cell. Display is kept character-for-character (Req 9)."""
    t = (text or "").strip()
    for rx, unit in ((PCT_RE, "percent"), (MULT_RE, "multiple"), (PLAIN_RE, None)):
        m = rx.match(t)
        if m:
            if unit is None:
                unit = "days" if metric_key == "DSO" else "amount"
            return {"display": t, "value": Decimal(m.group(1)), "unit": unit, "decimals": len(m.group(2) or ""), "flags": []}
    return {"display": NOT_IN_DB, "value": None, "unit": None, "decimals": 0, "flags": ["unparseable value"]}


def format_value(value: Decimal, unit: str, decimals: int) -> str:
    q = Decimal(1).scaleb(-decimals) if decimals > 0 else Decimal(1)
    s = format(Decimal(value).quantize(q, rounding=ROUND_HALF_UP), "f")
    return s + {"percent": "%", "multiple": "x"}.get(unit, "")


def map_label(label: str) -> tuple[str, bool]:
    key = LABEL_MAP.get(label.strip().lower())
    if key:
        return key, True
    return unrecognised_key(label), False


def unrecognised_key(label: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", label.strip().upper()).strip("_") or "METRIC"


def parse_period_header(header: str) -> dict:
    h = header.strip()
    m = HEADER_RE.match(h)
    if not m:
        raise LoadError(f"Unparseable period column header: \"{header}\"")
    q, year, mon, day, end_year = m.groups()
    try:
        end = datetime.strptime(f"{mon} {day} {end_year}", "%b %d %Y").date()
    except ValueError as exc:
        raise LoadError(f"Unparseable period column header: \"{header}\"") from exc
    return {"label": f"Q{q}-{year}", "end_date": end.isoformat(), "header": header}


# --------------------------------------------------------------------------- anomalies
def apply_anomaly_flags(metric_key: str, unit: str | None, cells: list[dict], thresholds: dict, unit_stated: bool = False) -> None:
    """Attach flags in FLAG_ORDER. Values are never altered (Req 10)."""
    for i, c in enumerate(cells):
        flags = set(c["flags"])
        v = c["value"]
        if v is not None:
            if v == 0:
                flags.add("zero value")
            if v < 0 and metric_key not in NEGATIVE_OK:
                flags.add("negative value")
            if i > 0 and cells[i - 1]["value"] is not None:
                prev = cells[i - 1]["value"]
                t = Decimal(str(thresholds.get(unit or "amount", 0)))
                if unit == "amount":
                    if (prev == 0 and v != 0) or (prev != 0 and abs(v - prev) > t / 100 * abs(prev)):
                        flags.add("large swing")
                elif unit and abs(v - prev) > t:
                    flags.add("large swing")
        if unit == "amount" and not unit_stated:
            flags.add("unit not stated")
        c["flags"] = [f for f in FLAG_ORDER if f in flags]


# --------------------------------------------------------------------------- comparisons
def raw_change(unit: str, from_v: Decimal, to_v: Decimal) -> Decimal | None:
    if unit == "amount":
        if from_v == 0:
            return None
        return (to_v - from_v) / abs(from_v) * 100
    return to_v - from_v


def direction(change: Decimal | None, band: float, to_v: Decimal) -> str:
    if change is None:
        return "up" if to_v > 0 else "down" if to_v < 0 else "~"
    b = Decimal(str(band))
    if -b <= change <= b:
        return "~"
    return "up" if change > b else "down"


def change_display(unit: str, change: Decimal | None) -> str:
    if change is None:
        return "Not computable"
    places, suffix = {"percent": (1, " pp"), "multiple": (2, "x"), "days": (1, " days"), "amount": (1, "%")}[unit]
    q = abs(change).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if change < 0 and q != 0 else "+"
    return f"{sign}{format(q, 'f')}{suffix}"


def build_comparisons(metrics: list[dict], stable_band: dict) -> list[dict]:
    out = []
    for m in metrics:
        unit = m["unit_type"]
        if unit is None:
            continue
        entries = m["entries"]
        for a, b in zip(entries, entries[1:]):
            if a["value"] is None or b["value"] is None:
                continue  # a null breaks the chain; no bridging (Req 12.7)
            fv, tv = Decimal(a["value"]), Decimal(b["value"])
            ch = raw_change(unit, fv, tv)
            out.append({
                "metric_key": m["key"], "metric_label": m["label"], "unit": unit,
                "from_period": a["period"], "to_period": b["period"],
                "change": None if ch is None else str(ch), "change_display": change_display(unit, ch),
                "direction": direction(ch, stable_band[unit], tv),
                "from_evidence_id": a["evidence_id"], "to_evidence_id": b["evidence_id"],
                "basis": "quarter-on-quarter",
            })
    return out


def sustained_label(metric_key: str, comparisons: list[dict]) -> str | None:
    recs = [c for c in comparisons if c["metric_key"] == metric_key]
    if len(recs) < 2:
        return None
    a, b = recs[-2]["direction"], recs[-1]["direction"]
    if a != b or a == "~":
        return None
    if metric_key in NEUTRAL:
        return "sustained increase" if a == "up" else "sustained decrease"
    good = "down" if metric_key in LOWER_IS_BETTER else "up"
    return "sustained improvement" if a == good else "sustained deterioration"


def better_direction(metric_key: str) -> str:
    return "neutral" if metric_key in NEUTRAL else "lower" if metric_key in LOWER_IS_BETTER else "higher"


def divergence_assessability(present_keys: set[str], comparisons: list[dict] | None = None) -> list[dict]:
    """Which patterns can be checked, and (when they can) the consecutive quarters where the backend's
    comparison directions match the pattern. Uses Comparison_Records only; nothing is recalculated."""
    out = []
    comps = comparisons or []
    for pid, desc, names, dirs in DIVERGENCE_PATTERNS:
        missing = [n for n in names if NAME_TO_CANONICAL.get(n) not in present_keys]
        rec = {"pattern_id": pid, "description": desc, "required_metrics": names, "assessable": not missing,
               "missing_metrics": missing, "observed": [], "statement": None}
        if missing:
            rec["statement"] = "Not assessable: data not available in database"
        else:
            k1, k2 = (NAME_TO_CANONICAL[n] for n in names)
            by1 = {(c["from_period"], c["to_period"]): c for c in comps if c["metric_key"] == k1}
            for c2 in (c for c in comps if c["metric_key"] == k2):
                c1 = by1.get((c2["from_period"], c2["to_period"]))
                if c1 and c1["direction"] == dirs[0] and c2["direction"] == dirs[1]:
                    rec["observed"].append({"from_period": c2["from_period"], "to_period": c2["to_period"],
                                            "evidence_ids": [c1["from_evidence_id"], c1["to_evidence_id"], c2["from_evidence_id"], c2["to_evidence_id"]],
                                            "changes": {k1: c1["change_display"], k2: c2["change_display"]}})
            rec["statement"] = ("Observed: " + "; ".join(f"{o['from_period']} to {o['to_period']}" for o in rec["observed"])
                                if rec["observed"] else "Not observed in the database periods")
        out.append(rec)
    return out


# --------------------------------------------------------------------------- shared dataset assembly
def _finish_dataset(file_name: str, periods: list[dict], metrics: list[dict], gaps: list[str], stable_band: dict,
                    extra: dict | None = None, unavailable_extra: list[str] | None = None) -> dict:
    present = {m["key"] for m in metrics if m["recognised"] and any(e["value"] is not None for e in m["entries"])}
    have = {m["key"] for m in metrics}
    missing_canonical = [CANONICAL_LABEL[k] for k in CANONICAL_KEYS if k not in have and k not in OPTIONAL_KEYS]
    comparisons = build_comparisons([m for m in metrics if m["recognised"]], stable_band)
    divergence = divergence_assessability(present, comparisons)
    for d in divergence:
        if not d["assessable"]:
            gaps.append(f"Divergence pattern {d['pattern_id']} ({d['description']}) not assessable: "
                        f"{', '.join(d['missing_metrics'])} not available in database")
    unavailable = list(UNAVAILABLE_METRICS) + [m for m in missing_canonical + (unavailable_extra or []) if m not in UNAVAILABLE_METRICS]
    flagged = [{"evidence_id": e["evidence_id"], "metric": m["label"], "period": e["period"], "display": e["display"], "flags": e["flags"]}
               for m in metrics for e in m["entries"] if e["flags"]]
    return {
        "file_name": file_name,
        "periods": periods,
        "metrics": metrics,
        "comparisons": comparisons,
        "sustained": {k: sustained_label(k, comparisons) for k in present},
        "divergence": divergence,
        "unavailable_metrics": unavailable,
        "information_gaps": gaps,
        "flagged_values": flagged,
        "loaded_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        **(extra or {}),
    }


# --------------------------------------------------------------------------- legacy CSV loader
def load_csv(path: Path, borrower: str, confirm_whole_file: bool | None, thresholds: dict, stable_band: dict) -> dict:
    """Return {"status": "ok"|"needs_confirmation", ...}; raise LoadError (nothing is written) on failure."""
    path = Path(path)
    if not path.exists():
        raise LoadError(f"File not found: {path.name}")
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise LoadError(f"The file {path.name} could not be read: {exc}") from exc
    if df.shape[0] == 0:
        raise LoadError(f"The file {path.name} has no data rows.")
    cols = list(df.columns)
    if not cols or cols[0].strip().lower() != "metric":
        raise LoadError(f"The file {path.name} must have a first column headed \"Metric\".")
    borrower_col = next((c for c in cols[1:] if c.strip().lower() == "borrower"), None)
    period_cols = [c for c in cols[1:] if c != borrower_col]
    if not period_cols:
        raise LoadError(f"The file {path.name} has no period column.")

    gaps: list[str] = []
    if borrower_col:
        want = borrower.strip().lower()
        df = df[df[borrower_col].str.strip().str.lower() == want]
        if df.shape[0] == 0:
            raise LoadError("No rows match the borrower.")
    else:
        if confirm_whole_file is None:
            return {"status": "needs_confirmation",
                    "message": f"The file {path.name} has no borrower column. Confirm that the whole file belongs to {borrower}."}
        if confirm_whole_file is False:
            raise LoadError("Loading stopped: the file was not confirmed as belonging to the borrower.")
        gaps.append("Database has no borrower identifier")

    periods = [parse_period_header(c) for c in period_cols]
    labels = [p["label"] for p in periods]
    dup = next((p["header"] for i, p in enumerate(periods) if p["label"] in labels[:i]), None)
    if dup:
        raise LoadError(f"Duplicate period column: \"{dup}\"")
    order = sorted(range(len(periods)), key=lambda i: periods[i]["end_date"])

    rows, seen = [], {}
    for _, row in df.iterrows():
        label_written = row[cols[0]]
        key, recognised = map_label(label_written)
        if key in seen:
            raise LoadError(f"Duplicate metric row: \"{label_written.strip()}\"")
        seen[key] = True
        rows.append((key, recognised, label_written, row))

    by_key = {r[0]: r for r in rows}
    ordered = [by_key[k] for k in CANONICAL_KEYS if k in by_key] + [r for r in rows if not r[1]]
    metrics, evidence = [], {}
    for key, recognised, label_written, row in ordered:
        cells = []
        for i in order:
            cell = parse_cell(row[period_cols[i]], key)
            cell["period"] = periods[i]["label"]
            cell["header"] = periods[i]["header"]
            cells.append(cell)
        units = [c["unit"] for c in cells if c["unit"]]
        unit = max(set(units), key=units.count) if units else None
        apply_anomaly_flags(key, unit, cells, thresholds)
        label = CANONICAL_LABEL.get(key, label_written.strip())
        entries = []
        for c in cells:
            ev_id = f"CSV-{key}-{c['period']}"
            entry = {"period": c["period"], "display": c["display"], "value": None if c["value"] is None else str(c["value"]),
                     "unit": c["unit"], "decimals": c["decimals"], "flags": c["flags"], "evidence_id": ev_id}
            entries.append(entry)
            evidence[ev_id] = {"evidence_id": ev_id, "type": "csv", "file_name": path.name, "metric_key": key,
                               "metric_label_as_written": label_written.strip(), "column_header": c["header"],
                               "period": c["period"], "display": c["display"], "value": entry["value"],
                               "unit": c["unit"], "flags": c["flags"]}
        if unit == "amount":
            gaps.append(f"Unit not stated in database for \"{label_written.strip()}\"")
        metrics.append({"key": key, "label": label, "label_as_written": label_written.strip(), "recognised": recognised,
                        "flags": [] if recognised else ["Unrecognised metric"], "unit_type": unit, "unit_label": None,
                        "basis": None, "entries": entries})

    dataset = _finish_dataset(path.name, [periods[i] for i in order], metrics, gaps, stable_band, {"source_type": "csv"})
    return {"status": "ok", "dataset": dataset, "evidence": evidence}


# --------------------------------------------------------------------------- workbook loader
UNIT_TYPE = {"%": "percent", "x": "multiple", "days": "days"}
# Currency units used in the workbook: (ISO code, scale of one unit in currency units)
CURRENCY_UNITS = {"usd m": ("USD", 1_000_000), "us$ m": ("USD", 1_000_000), "nt$ bn": ("TWD", 1_000_000_000),
                  "usd bn": ("USD", 1_000_000_000), "nt$ m": ("TWD", 1_000_000)}
PERIOD_RE = re.compile(r"^Q([1-4])\s+FY(\d{4})$")
SUFFIXES = {"corporation", "corp", "inc", "incorporated", "co", "company", "ltd", "limited", "plc", "llc", "holdings",
            "group", "the", "sa", "ag", "nv"}


def normalise_company(name: str) -> str:
    s = re.sub(r"\(.*?\)", " ", name.lower().replace("&", " and "))
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", s).split() if w not in SUFFIXES]
    return " ".join(words)


def company_sheets(wb: Workbook) -> list[dict]:
    """KPI sheets: a sheet whose A4 reads "Financial Performance Indicators" and that has a matching "<name> Inputs" sheet."""
    out = []
    for name in wb.sheet_names:
        if wb.text(name, "A4").strip().lower() != "financial performance indicators" or f"{name} Inputs" not in wb.sheet_names:
            continue
        title = wb.text(name, "A1")
        company = re.split(r"\s[\u2013\u2014-]\s", title, maxsplit=1)[0].strip() or name
        abbrev = re.findall(r"\(([^)]+)\)", company)
        out.append({"sheet": name, "company": company, "aliases": [name, company] + abbrev})
    return out


def match_borrower(sheets: list[dict], borrower: str) -> dict | None:
    want = normalise_company(borrower)
    if not want:
        return None
    exact, partial = [], []
    for s in sheets:
        cands = {normalise_company(a) for a in s["aliases"]} - {""}
        if want in cands:
            exact.append(s)
        elif any(want.startswith(c + " ") or c.startswith(want + " ") for c in cands):
            partial.append(s)
    hits = exact or partial
    if len(hits) > 1:
        raise LoadError(f"The borrower \"{borrower}\" matches more than one company in the financial database: "
                        f"{', '.join(h['sheet'] for h in hits)}. Use the full company name.")
    return hits[0] if hits else None


def _fmt(value: Decimal, places: int) -> str:
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    v = value.quantize(q, rounding=ROUND_HALF_UP)
    if v == 0:
        v = abs(v)
    return f"{v:,.{places}f}"


def workbook_cell(raw, unit: str, amount_places: int) -> dict:
    """Turn a workbook value into a database entry. Display is the workbook value in its stated unit,
    rounded for presentation; the entry's value is the displayed number so every figure reconciles."""
    if raw is BLANK:
        return {"display": NOT_IN_DB, "value": None, "unit": unit, "decimals": 0, "flags": ["blank in database"], "error": None}
    if isinstance(raw, XlErr):
        return {"display": NOT_IN_DB, "value": None, "unit": unit, "decimals": 0, "flags": ["formula error"], "error": raw.code}
    if isinstance(raw, str):
        if raw.strip().lower() == "n/m":
            return {"display": "n/m", "value": None, "unit": unit, "decimals": 0, "flags": ["not meaningful (n/m)"], "error": None}
        return {"display": NOT_IN_DB, "value": None, "unit": unit, "decimals": 0, "flags": ["unparseable value"], "error": None}
    if isinstance(raw, bool):
        return {"display": NOT_IN_DB, "value": None, "unit": unit, "decimals": 0, "flags": ["unparseable value"], "error": None}
    d = Decimal(repr(float(raw)))
    if unit == "percent":
        places, d, suffix = 2, d * 100, "%"
    elif unit == "multiple":
        places, suffix = 2, "x"
    elif unit == "days":
        places, suffix = 1, ""
    else:
        places, suffix = amount_places, ""
    display = _fmt(d, places) + suffix
    value = Decimal(_fmt(d, places).replace(",", ""))
    return {"display": display, "value": value, "unit": unit, "decimals": places, "flags": [], "error": None}


def load_workbook(path: Path, borrower: str, thresholds: dict, stable_band: dict) -> dict:
    path = Path(path)
    if not path.exists():
        raise LoadError(f"File not found: {path.name}")
    try:
        wb = Workbook(path)
    except WorkbookError as exc:
        raise LoadError(str(exc)) from exc
    sheets = company_sheets(wb)
    if not sheets:
        raise LoadError(f"The workbook {path.name} has no company sheets (A4 must read \"Financial Performance Indicators\").")
    hit = match_borrower(sheets, borrower)
    if hit is None:
        raise LoadError(f"No company in the financial database matches the borrower \"{borrower}\". "
                        f"Companies available: {', '.join(s['company'] for s in sheets)}.")
    sheet = hit["sheet"]

    # Period columns: row 4 headers like "Q2 FY2026"; row 5 period end (Excel date); row 6 calendar quarter.
    cols, periods = [], []
    col = 3
    while True:
        letter = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[col - 1] if col <= 26 else None
        if letter is None:
            break
        head = wb.text(sheet, f"{letter}4").strip()
        m = PERIOD_RE.match(head)
        if not m:
            break
        end_raw = wb.value(sheet, f"{letter}5")
        if not isinstance(end_raw, float):
            raise LoadError(f"Period column {head} on sheet {sheet} has no period end date in row 5.")
        end = excel_date(end_raw)
        cal = wb.text(sheet, f"{letter}6").strip()
        label = f"Q{m.group(1)}-FY{m.group(2)}"
        if label in [p["label"] for p in periods]:
            raise LoadError(f"Duplicate period column: \"{head}\" on sheet {sheet}")
        periods.append({"label": label, "end_date": end.isoformat(), "calendar_quarter": cal,
                        "header": f"{head} (period end {end.isoformat()}{'; ' + cal if cal else ''})"})
        cols.append(letter)
        col += 1
    if not periods:
        raise LoadError(f"Sheet {sheet} has no period columns (row 4 headers like \"Q2 FY2026\").")
    basis_col = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[col - 1] if col <= 26 else None
    order = sorted(range(len(periods)), key=lambda i: periods[i]["end_date"])

    gaps: list[str] = []
    rows, seen = [], set()
    unit_labels = []
    for r in wb.rows(sheet):
        if r < 9:
            continue
        label_written = wb.text(sheet, f"A{r}").strip()
        unit_text = wb.text(sheet, f"B{r}").strip()
        if not label_written or not unit_text or label_written.lower() in SKIP_LABELS:
            continue
        key, recognised = map_label(label_written)
        if key in seen:
            raise LoadError(f"Duplicate metric row: \"{label_written}\" on sheet {sheet}")
        seen.add(key)
        rows.append((key, recognised, label_written, unit_text, r))
        if unit_text.lower() in CURRENCY_UNITS:
            unit_labels.append(unit_text)
    currency_unit = max(set(unit_labels), key=unit_labels.count) if unit_labels else None
    currency = CURRENCY_UNITS.get((currency_unit or "").lower())
    amount_places = 0 if currency and currency[1] == 1_000_000 else 2

    by_key = {r[0]: r for r in rows}
    ordered = [by_key[k] for k in CANONICAL_KEYS if k in by_key] + [r for r in rows if not r[1]]
    metrics, evidence = [], {}
    calc = {"saved": 0, "evaluated": 0}
    for key, recognised, label_written, unit_text, r in ordered:
        ut = unit_text.lower()
        unit = UNIT_TYPE.get(ut) or ("amount" if ut in CURRENCY_UNITS else None)
        unit_stated = unit is not None
        unit = unit or "amount"
        cells = []
        for i in order:
            ref = f"{cols[i]}{r}"
            if wb.formula(sheet, ref) is not None:
                calc["saved" if wb.raw(sheet, ref) is not BLANK else "evaluated"] += 1
            cell = workbook_cell(wb.value(sheet, ref), unit, amount_places)
            cell.update({"period": periods[i]["label"], "header": periods[i]["header"], "cell": f"{sheet}!{ref}",
                         "formula": wb.formula(sheet, ref)})
            cells.append(cell)
        apply_anomaly_flags(key, unit, cells, thresholds, unit_stated=unit_stated)
        label = CANONICAL_LABEL.get(key, label_written)
        basis = wb.text(sheet, f"{basis_col}{r}").strip() if basis_col else ""
        entries = []
        for c in cells:
            ev_id = f"CSV-{key}-{c['period']}"
            entry = {"period": c["period"], "display": c["display"], "value": None if c["value"] is None else str(c["value"]),
                     "unit": c["unit"], "decimals": c["decimals"], "flags": c["flags"], "evidence_id": ev_id, "cell": c["cell"]}
            entries.append(entry)
            evidence[ev_id] = {"evidence_id": ev_id, "type": "csv", "file_name": path.name, "sheet": sheet, "cell": c["cell"],
                               "formula": c["formula"], "formula_error": c["error"], "metric_key": key,
                               "metric_label_as_written": label_written, "column_header": c["header"], "period": c["period"],
                               "display": c["display"], "value": entry["value"], "unit": c["unit"],
                               "unit_label": unit_text if unit == "amount" else None, "basis": basis or None, "flags": c["flags"]}
        if not unit_stated:
            gaps.append(f"Unit not stated in database for \"{label_written}\"")
        metrics.append({"key": key, "label": label, "label_as_written": label_written, "recognised": recognised,
                        "flags": [] if recognised else ["Unrecognised metric"], "unit_type": unit,
                        "unit_label": unit_text if unit == "amount" else None, "basis": basis or None, "entries": entries})

    blanks = [f"{m['label']} {e['period']}" for m in metrics for e in m["entries"] if "blank in database" in e["flags"] or "formula error" in e["flags"]]
    if blanks:
        gaps.append("Values not available in the database (blank inputs or formula errors): " + ", ".join(blanks))
    if calc["evaluated"]:
        note = (f"The workbook has no saved formula results, so the backend evaluated the workbook's own formulas "
                f"({calc['evaluated']} cells) exactly as written; no ratio is defined by the backend.")
    else:
        note = "Values are the workbook's saved formula results."
    extra = {"source_type": "workbook", "sheet": sheet, "company": hit["company"], "currency_unit": currency_unit,
             "currency": currency[0] if currency else None, "currency_scale": currency[1] if currency else None,
             "amount_decimals": amount_places, "calculation_note": note,
             "companies_in_database": [s["company"] for s in sheets]}
    dataset = _finish_dataset(path.name, [periods[i] for i in order], metrics, gaps, stable_band, extra)
    return {"status": "ok", "dataset": dataset, "evidence": evidence}


def load_database(path: Path, borrower: str, thresholds: dict, stable_band: dict) -> dict:
    """Connect to the financial database: the semiconductor workbook (.xlsx) or a legacy CSV."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return load_workbook(path, borrower, thresholds, stable_band)
    return load_csv(path, borrower, True, thresholds, stable_band)


# --------------------------------------------------------------------------- dashboard
def build_dashboard(dataset: dict) -> dict:
    by_key = {m["key"]: m for m in dataset["metrics"]}
    comps = dataset["comparisons"]
    labels = [p["label"] for p in dataset["periods"]]
    panels = []
    for pkey, title, metric_keys, unavailable in PANELS:
        metrics, not_avail = [], list(unavailable)
        for k in metric_keys:
            m = by_key.get(k)
            if not m or all(e["value"] is None for e in m["entries"]):
                if k not in OPTIONAL_KEYS:
                    not_avail.append(CANONICAL_LABEL[k])
                continue
            latest = m["entries"][-1]
            recs = [c for c in comps if c["metric_key"] == k]
            last = max(recs, key=lambda c: labels.index(c["to_period"])) if recs else None
            metrics.append({
                "key": k, "label": m["label"], "unit": m["unit_type"], "unit_label": m.get("unit_label"),
                "basis": m.get("basis"), "better": better_direction(k), "memo": k in MEMO_KEYS,
                "series": [{"period": e["period"], "value": None if e["value"] is None else float(e["value"]),
                            "display": e["display"], "flags": e["flags"], "evidence_id": e["evidence_id"]} for e in m["entries"]],
                "latest": {"period": latest["period"], "display": latest["display"], "flags": latest["flags"]},
                "latest_comparison": last,
                "sustained": dataset["sustained"].get(k),
            })
        panels.append({"key": pkey, "title": title, "metrics": metrics, "not_available": not_avail})
    return {"periods": labels, "panels": panels, "file_name": dataset["file_name"], "company": dataset.get("company"),
            "currency_unit": dataset.get("currency_unit"), "calculation_note": dataset.get("calculation_note")}
