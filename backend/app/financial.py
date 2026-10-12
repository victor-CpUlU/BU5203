"""Financial database (CSV) handling. Ratios are read from the CSV, never calculated (Req 8-14).

The only arithmetic here is the period-over-period change used to label direction and to verify
AI comparison claims (Comparison_Records). No credit ratio is derived.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

CANONICAL = [
    ("REVENUE_GROWTH", "Revenue Growth"),
    ("EBITDA_MARGIN", "EBITDA Margin"),
    ("DEBT_EBITDA", "Debt/EBITDA"),
    ("INTEREST_COVERAGE", "Interest Coverage"),
    ("CURRENT_RATIO", "Current Ratio"),
    ("DSCR", "Debt-Service Coverage Ratio (DSCR)"),
    ("OPERATING_CASH_FLOW", "Operating Cash Flow"),
    ("OCF_MARGIN", "Operating Cash Flow Margin"),
    ("WORKING_CAPITAL", "Working Capital"),
    ("DSO", "Days Sales Outstanding (DSO)"),
]
CANONICAL_KEYS = [k for k, _ in CANONICAL]
CANONICAL_LABEL = dict(CANONICAL)
LABEL_MAP = {label.lower(): key for key, label in CANONICAL}
LOWER_IS_BETTER = {"DEBT_EBITDA", "DSO"}

PANELS = [
    ("profitability", "Profitability", ["REVENUE_GROWTH", "EBITDA_MARGIN"], ["Revenue", "EBITDA", "Net Profit Margin"]),
    ("leverage", "Leverage", ["DEBT_EBITDA"], ["Total Debt", "Net Debt", "Debt / Equity"]),
    ("liquidity", "Liquidity", ["CURRENT_RATIO", "WORKING_CAPITAL"], ["Cash", "Short-term Debt", "Quick Ratio"]),
    ("cash_flow", "Cash Flow", ["OPERATING_CASH_FLOW", "OCF_MARGIN", "DSO"], ["Capital Expenditure", "Free Cash Flow"]),
    ("debt_servicing", "Debt Servicing", ["DSCR", "INTEREST_COVERAGE"], ["Interest Expense"]),
]
UNAVAILABLE_METRICS = [m for p in PANELS for m in p[3]]

# Divergence patterns from the Project Details. Each named metric must be a Canonical_Metric in
# the dataset; no proxies are substituted (REVENUE_GROWTH is not "Revenue").
NAME_TO_CANONICAL = {"Operating Cash Flow": "OPERATING_CASH_FLOW", "DSCR": "DSCR"}
DIVERGENCE_PATTERNS = [
    ("P1", "Revenue up with EBITDA down (possible margin compression)", ["Revenue", "EBITDA"]),
    ("P2", "Revenue up with Operating Cash Flow down (weaker cash conversion)", ["Revenue", "Operating Cash Flow"]),
    ("P3", "Debt up with EBITDA down (increasing leverage)", ["Total Debt", "EBITDA"]),
    ("P4", "Debt up with DSCR down (weakening debt-servicing capacity)", ["Total Debt", "DSCR"]),
    ("P5", "Cash down with Short-term Debt up (increasing liquidity pressure)", ["Cash", "Short-term Debt"]),
]

FLAG_ORDER = ["unparseable value", "zero value", "negative value", "large swing", "unit not stated"]
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
def apply_anomaly_flags(metric_key: str, unit: str | None, cells: list[dict], thresholds: dict) -> None:
    """Attach flags in FLAG_ORDER. Values are never altered (Req 10)."""
    for i, c in enumerate(cells):
        flags = set(c["flags"])
        v = c["value"]
        if v is not None:
            if v == 0:
                flags.add("zero value")
            if v < 0 and metric_key != "REVENUE_GROWTH":
                flags.add("negative value")
            if i > 0 and cells[i - 1]["value"] is not None:
                prev = cells[i - 1]["value"]
                t = Decimal(str(thresholds.get(unit or "amount", 0)))
                if unit == "amount":
                    if (prev == 0 and v != 0) or (prev != 0 and abs(v - prev) > t / 100 * abs(prev)):
                        flags.add("large swing")
                elif unit and abs(v - prev) > t:
                    flags.add("large swing")
        if unit == "amount":
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
    good = "down" if metric_key in LOWER_IS_BETTER else "up"
    return "sustained improvement" if a == good else "sustained deterioration"


def divergence_assessability(present_keys: set[str]) -> list[dict]:
    out = []
    for pid, desc, names in DIVERGENCE_PATTERNS:
        missing = [n for n in names if NAME_TO_CANONICAL.get(n) not in present_keys]
        out.append({"pattern_id": pid, "description": desc, "required_metrics": names,
                    "assessable": not missing, "missing_metrics": missing,
                    "statement": None if not missing else "Not assessable: data not available in database"})
    return out


# --------------------------------------------------------------------------- loader
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
                        "flags": [] if recognised else ["Unrecognised metric"], "unit_type": unit, "entries": entries})

    present = {m["key"] for m in metrics if m["recognised"] and any(e["value"] is not None for e in m["entries"])}
    missing_canonical = [CANONICAL_LABEL[k] for k in CANONICAL_KEYS if k not in {m["key"] for m in metrics}]
    comparisons = build_comparisons([m for m in metrics if m["recognised"]], stable_band)
    divergence = divergence_assessability(present)
    for d in divergence:
        if not d["assessable"]:
            gaps.append(f"Divergence pattern {d['pattern_id']} ({d['description']}) not assessable: "
                        f"{', '.join(d['missing_metrics'])} not available in database")
    unavailable = UNAVAILABLE_METRICS + [m for m in missing_canonical if m not in UNAVAILABLE_METRICS]
    flagged = [{"evidence_id": e["evidence_id"], "metric": m["label"], "period": e["period"], "display": e["display"], "flags": e["flags"]}
               for m in metrics for e in m["entries"] if e["flags"]]
    dataset = {
        "file_name": path.name,
        "periods": [periods[i] for i in order],
        "metrics": metrics,
        "comparisons": comparisons,
        "sustained": {k: sustained_label(k, comparisons) for k in present},
        "divergence": divergence,
        "unavailable_metrics": unavailable,
        "information_gaps": gaps,
        "flagged_values": flagged,
        "loaded_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
    }
    return {"status": "ok", "dataset": dataset, "evidence": evidence}


# --------------------------------------------------------------------------- dashboard
def build_dashboard(dataset: dict) -> dict:
    by_key = {m["key"]: m for m in dataset["metrics"]}
    comps = dataset["comparisons"]
    panels = []
    for pkey, title, metric_keys, unavailable in PANELS:
        metrics, not_avail = [], list(unavailable)
        for k in metric_keys:
            m = by_key.get(k)
            if not m or all(e["value"] is None for e in m["entries"]):
                not_avail.append(CANONICAL_LABEL[k])
                continue
            latest = m["entries"][-1]
            recs = [c for c in comps if c["metric_key"] == k]
            last = max(recs, key=lambda c: [p["label"] for p in dataset["periods"]].index(c["to_period"])) if recs else None
            metrics.append({
                "key": k, "label": m["label"], "unit": m["unit_type"],
                "series": [{"period": e["period"], "value": None if e["value"] is None else float(e["value"]),
                            "display": e["display"], "flags": e["flags"], "evidence_id": e["evidence_id"]} for e in m["entries"]],
                "latest": {"period": latest["period"], "display": latest["display"], "flags": latest["flags"]},
                "latest_comparison": last,
                "sustained": dataset["sustained"].get(k),
            })
        panels.append({"key": pkey, "title": title, "metrics": metrics, "not_available": not_avail})
    return {"periods": [p["label"] for p in dataset["periods"]], "panels": panels, "file_name": dataset["file_name"]}
