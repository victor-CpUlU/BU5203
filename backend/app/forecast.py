"""Backend forecast and scenario analysis (Section 3). Deterministic Python; the AI calculates nothing.

Model (quarterly, from the latest database quarter):
  Revenue_t           = Revenue_{t-1} x (1 + revenue growth per quarter)
  EBITDA_t            = Revenue_t x EBITDA margin
  Capex_t             = Revenue_t x capex % of revenue
  CFADS_t             = EBITDA_t - Capex_t        (cash flow available for debt service; pre-tax, before working capital)
  Interest_t          = latest quarterly interest expense x (1 + change) + facility balance x facility rate / 4
  Principal_t         = existing short-term debt repaid evenly over N quarters + facility repayments (bullet or equal instalments)
  Debt service_t      = Interest_t + Principal_t
  DSCR_t              = CFADS_t / Debt service_t
  Interest coverage_t = EBITDA_t / Interest_t
  Total debt_t        = latest total debt - short-term debt repaid + facility balance
  Debt/EBITDA_t       = Total debt_t / EBITDA of the last 4 quarters (history + forecast)
  Cash_t              = Cash_{t-1} + CFADS_t - Debt service_t   (starts from latest cash and cash equivalents)

Base-case assumptions default to the averages of the database quarters; upside and downside add
illustrative shocks from config/analysis.toml. The analyst can change every assumption.
"""
from __future__ import annotations

import re
import statistics
from decimal import Decimal

from .financial import CANONICAL_LABEL, _fmt

SCENARIOS = [("base", "Base case"), ("upside", "Upside case"), ("downside", "Downside case")]
SCENARIO_LABEL = dict(SCENARIOS)
PARAMS = [
    ("revenue_growth", "Revenue growth per quarter (Q/Q)"),
    ("ebitda_margin", "EBITDA margin"),
    ("capex_pct_revenue", "Capital expenditure (% of revenue)"),
    ("interest_change", "Change in interest expense on existing debt"),
    ("facility_rate", "Interest rate on the requested facility (% per year)"),
]
PARAM_LABEL = dict(PARAMS)
PARAM_LIMITS = {"revenue_growth": (-90.0, 200.0), "ebitda_margin": (-100.0, 100.0), "capex_pct_revenue": (0.0, 200.0),
                "interest_change": (-100.0, 500.0), "facility_rate": (0.0, 50.0)}
THRESHOLDS = [  # key, label, unit, forecast metric, kind
    ("min_dscr", "Minimum DSCR", "multiple", "DSCR", "min"),
    ("min_interest_coverage", "Minimum interest coverage", "multiple", "INTEREST_COVERAGE", "min"),
    ("max_debt_ebitda", "Maximum Debt/EBITDA", "multiple", "DEBT_EBITDA", "max"),
    ("min_cash", "Minimum cash after debt service", "amount", "CASH", "min"),
]
OUTPUT_METRICS = [
    ("REVENUE", "Revenue", "amount"),
    ("EBITDA", "EBITDA", "amount"),
    ("CAPEX", "Capital expenditure", "amount"),
    ("CFADS", "Cash flow available for debt service (EBITDA - capex)", "amount"),
    ("INTEREST_EXPENSE", "Interest expense (existing debt + facility)", "amount"),
    ("PRINCIPAL", "Scheduled principal repayments", "amount"),
    ("DEBT_SERVICE", "Debt service (interest + principal)", "amount"),
    ("DSCR", "DSCR (cash flow available / debt service)", "multiple"),
    ("INTEREST_COVERAGE", "Interest coverage (EBITDA / interest)", "multiple"),
    ("TOTAL_DEBT", "Total debt including the facility", "amount"),
    ("DEBT_EBITDA", "Debt/EBITDA (LTM)", "multiple"),
    ("CASH", "Cash after debt service", "amount"),
    ("FACILITY_BALANCE", "Requested facility balance outstanding", "amount"),
]
METRIC_LABEL = {k: l for k, l, _ in OUTPUT_METRICS}
METRIC_UNIT = {k: u for k, _, u in OUTPUT_METRICS}
AI_METRICS = ["REVENUE", "EBITDA", "CFADS", "DEBT_SERVICE", "DSCR", "INTEREST_COVERAGE", "DEBT_EBITDA", "CASH"]
REQUIRED = ["REVENUE", "REVENUE_GROWTH", "EBITDA", "EBITDA_MARGIN", "CAPEX", "INTEREST_EXPENSE", "TOTAL_DEBT", "SHORT_TERM_DEBT", "CASH"]
# History plotted next to the forecast only where the workbook uses the same definition as the model.
HISTORY_COMPARABLE = {"REVENUE": "REVENUE", "EBITDA": "EBITDA", "CAPEX": "CAPEX", "TOTAL_DEBT": "TOTAL_DEBT",
                      "CASH": "CASH", "DEBT_EBITDA": "DEBT_EBITDA", "INTEREST_EXPENSE": "INTEREST_EXPENSE"}
CURRENCY_ALIASES = {"NTD": "TWD", "NT$": "TWD", "US$": "USD"}
REPAYMENT_LABEL = {"bullet": "Bullet: full repayment at the end of the tenor", "amortising": "Equal quarterly instalments over the tenor"}
NOTES = [
    "Forecast figures are backend projections from the stated assumptions, not reported results.",
    "Cash flow available for debt service is EBITDA less capital expenditure: before tax, working-capital changes, dividends and buybacks.",
    "Long-term debt maturities are not in the financial database and are not included in debt service; compare with the 2B debt maturity profile.",
    "Interest on existing debt is held at the latest quarter's run-rate (adjusted by the scenario change); the facility is drawn at the start of the forecast and its proceeds are assumed to be spent on the stated purpose.",
    "The forecast DSCR and interest coverage use the model definitions above, which differ from the company-specific definitions of the historical DSCR and interest coverage in the workbook.",
    "When cash flow available for debt service is negative, DSCR is negative and its size is not meaningful; read the shortfall quarters and cash after debt service instead.",
]


class ForecastInputError(Exception):
    def __init__(self, errors: list[dict]):
        super().__init__("Invalid forecast assumptions")
        self.errors = errors


# --------------------------------------------------------------------------- helpers
def _r2(x: float) -> float:
    return float(Decimal(repr(x)).quantize(Decimal("0.01")))


def _series(ds: dict, key: str) -> list[tuple[str, float | None]]:
    m = next((m for m in ds["metrics"] if m["key"] == key), None)
    if not m:
        return []
    return [(e["period"], None if e["value"] is None else float(e["value"])) for e in m["entries"]]


def _latest(ds: dict, key: str) -> tuple[str, float] | None:
    vals = [(p, v) for p, v in _series(ds, key) if v is not None]
    return vals[-1] if vals else None


def _stats(points: list[tuple[str, float]]) -> dict | None:
    if not points:
        return None
    vals = [v for _, v in points]
    return {"n": len(vals), "mean": _r2(statistics.fmean(vals)), "median": _r2(statistics.median(vals)),
            "min": _r2(min(vals)), "max": _r2(max(vals)), "latest": _r2(vals[-1]),
            "from_period": points[0][0], "to_period": points[-1][0]}


def next_periods(label: str, n: int) -> list[str]:
    m = re.fullmatch(r"Q([1-4])-(FY)?(\d{4})", label)
    if not m:
        return [f"F{i}" for i in range(1, n + 1)]
    q, fy, year = int(m.group(1)), m.group(2) or "", int(m.group(3))
    out = []
    for _ in range(n):
        q += 1
        if q > 4:
            q, year = 1, year + 1
        out.append(f"Q{q}-{fy}{year}")
    return out


def parse_tenor_quarters(text: str) -> int | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(years?|yrs?|y\b|months?|mos?|m\b|quarters?|qtrs?|q\b)", (text or "").lower())
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    q = n * 4 if unit.startswith("y") else n / 3 if unit.startswith("m") else n
    return max(1, int(round(q)))


def parse_repayment(text: str) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("amort", "instal", "equal", "quarterly repayment", "monthly repayment")):
        return "amortising"
    if "bullet" in t or "at maturity" in t or "balloon" in t:
        return "bullet"
    return "amortising"


def history_stats(ds: dict) -> dict:
    rev = {p: v for p, v in _series(ds, "REVENUE")}
    capex_pct = [(p, v / rev[p] * 100) for p, v in _series(ds, "CAPEX") if v is not None and rev.get(p)]
    out = {
        "revenue_growth": _stats([(p, v) for p, v in _series(ds, "REVENUE_GROWTH") if v is not None]),
        "ebitda_margin": _stats([(p, v) for p, v in _series(ds, "EBITDA_MARGIN") if v is not None]),
        "capex_pct_revenue": _stats(capex_pct),
        "interest_change": None,
        "facility_rate": None,
    }
    li, ld = _latest(ds, "INTEREST_EXPENSE"), _latest(ds, "TOTAL_DEBT")
    if li and ld and ld[1] > 0:
        out["implied_rate_existing_debt"] = _r2(li[1] * 4 / ld[1] * 100)
    return out


# --------------------------------------------------------------------------- assumptions
def missing_inputs(ds: dict | None) -> list[str]:
    if not ds:
        return ["financial database"]
    labels = {m["key"]: m["label"] for m in ds["metrics"]}
    out = []
    for k in REQUIRED:
        if _latest(ds, k) is None:
            out.append(labels.get(k) or CANONICAL_LABEL.get(k, k))
    return out


def default_assumptions(ds: dict, deal: dict, cfg: dict) -> dict:
    st = history_stats(ds)
    base = {
        "revenue_growth": st["revenue_growth"]["mean"],
        "ebitda_margin": st["ebitda_margin"]["mean"],
        "capex_pct_revenue": st["capex_pct_revenue"]["mean"] if st["capex_pct_revenue"] else 0.0,
        "interest_change": 0.0,
        "facility_rate": float(cfg["facility_rate"]),
    }
    scen = {"base": base}
    for s in ("upside", "downside"):
        scen[s] = {p: _clamp(p, _r2(base[p] + cfg[s][p])) for p, _ in PARAMS}
    tenor = parse_tenor_quarters(deal["intake"]["DI-TENOR"]["display"])
    horizon = min(cfg["max_horizon_quarters"], max(4, tenor)) if tenor else cfg["default_horizon_quarters"]
    return {
        "scenarios": scen,
        "facility": {"repayment": parse_repayment(deal["intake"]["DI-REPAYMENT"]["display"]),
                     "tenor_quarters": tenor or horizon, "fx_rate": None},
        "horizon_quarters": horizon,
        "thresholds": {k: None for k, *_ in THRESHOLDS},
    }


def _clamp(p: str, v: float) -> float:
    lo, hi = PARAM_LIMITS[p]
    return min(hi, max(lo, v))


def validate_assumptions(raw: dict, defaults: dict, cfg: dict) -> dict:
    """Return clean assumptions or raise ForecastInputError with per-field reasons."""
    errs: list[dict] = []
    out = {"scenarios": {}, "facility": {}, "thresholds": {}}

    def num(v, field, lo=None, hi=None, allow_none=False):
        if v is None or v == "":
            if allow_none:
                return None
            errs.append({"field": field, "reason": "A number is required"})
            return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            errs.append({"field": field, "reason": "Must be a number"})
            return None
        if x != x or x in (float("inf"), float("-inf")):
            errs.append({"field": field, "reason": "Must be a finite number"})
            return None
        if (lo is not None and x < lo) or (hi is not None and x > hi):
            errs.append({"field": field, "reason": f"Must be between {lo:g} and {hi:g}"})
            return None
        return _r2(x)

    scen_in = (raw or {}).get("scenarios") or {}
    for s, _ in SCENARIOS:
        vals = scen_in.get(s) or {}
        out["scenarios"][s] = {}
        for p, label in PARAMS:
            lo, hi = PARAM_LIMITS[p]
            v = num(vals.get(p, defaults["scenarios"][s][p]), f"{s}.{p}", lo, hi)
            out["scenarios"][s][p] = v if v is not None else defaults["scenarios"][s][p]
    fac = (raw or {}).get("facility") or {}
    rep = fac.get("repayment", defaults["facility"]["repayment"])
    if rep not in REPAYMENT_LABEL:
        errs.append({"field": "facility.repayment", "reason": "Choose bullet or amortising"})
        rep = defaults["facility"]["repayment"]
    tenor = num(fac.get("tenor_quarters", defaults["facility"]["tenor_quarters"]), "facility.tenor_quarters", 1, 120)
    fx = num(fac.get("fx_rate", defaults["facility"]["fx_rate"]), "facility.fx_rate", 0.000001, 1e9, allow_none=True)
    out["facility"] = {"repayment": rep, "tenor_quarters": int(tenor) if tenor else defaults["facility"]["tenor_quarters"], "fx_rate": fx}
    h = num((raw or {}).get("horizon_quarters", defaults["horizon_quarters"]), "horizon_quarters", 4, cfg["max_horizon_quarters"])
    out["horizon_quarters"] = int(h) if h else defaults["horizon_quarters"]
    th = (raw or {}).get("thresholds") or {}
    for k, label, unit, _, _ in THRESHOLDS:
        out["thresholds"][k] = num(th.get(k), f"thresholds.{k}", -1e12, 1e12, allow_none=True)
    if errs:
        raise ForecastInputError(errs)
    return out


def assumption_sources(assumptions: dict, defaults: dict, stats: dict, cfg: dict) -> dict:
    out = {}
    for s, _ in SCENARIOS:
        out[s] = {}
        for p, _ in PARAMS:
            if assumptions["scenarios"][s][p] != defaults["scenarios"][s][p]:
                out[s][p] = "Set by the analyst"
            elif s == "base":
                st = stats.get(p)
                out[s][p] = (f"Default: historical average of {st['n']} quarters ({st['from_period']} to {st['to_period']})" if st
                             else "Default: no change" if p == "interest_change"
                             else "Default: illustrative rate from config; the analyst sets the actual rate" if p == "facility_rate"
                             else "Default")
            else:
                shock = cfg[s][p]
                unit = "%" if p == "interest_change" else " pp"
                out[s][p] = f"Default: base case {shock:+g}{unit} (illustrative)"
    return out


# --------------------------------------------------------------------------- model
def _display(value: float | None, unit: str, amount_places: int) -> str:
    if value is None:
        return "n/m"
    d = Decimal(repr(float(value)))
    if unit == "multiple":
        return _fmt(d, 2) + "x"
    if unit == "percent":
        return _fmt(d, 2) + "%"
    return _fmt(d, amount_places)


def facility_amount(ds: dict, deal: dict, fx_rate: float | None) -> dict:
    a = deal["intake"]["DI-AMOUNT"]
    deal_cur = CURRENCY_ALIASES.get(a["currency"].upper(), a["currency"].upper())
    comp_cur, scale = ds.get("currency"), ds.get("currency_scale")
    out = {"deal_amount": a["display"], "deal_currency": deal_cur, "company_currency": comp_cur,
           "unit_label": ds.get("currency_unit"), "value": None, "fx_rate": None, "warning": None}
    if not comp_cur or not scale:
        out["warning"] = "The database does not state a currency unit, so the requested facility cannot be added to the forecast."
        return out
    if deal_cur == comp_cur:
        rate = 1.0
    elif fx_rate:
        rate = float(fx_rate)
    else:
        out["warning"] = (f"The facility is in {deal_cur} but the database is in {comp_cur}. Enter an exchange rate "
                          f"({comp_cur} per 1 {deal_cur}) to include the facility; until then the forecast excludes it.")
        return out
    out["fx_rate"] = rate
    out["value"] = float(Decimal(a["amount"]) * Decimal(repr(rate)) / Decimal(scale))
    return out


def compute(ds: dict, deal: dict, assumptions: dict, cfg: dict) -> dict:
    places = ds.get("amount_decimals", 0)
    first = {k: _latest(ds, k) for k in REQUIRED}
    start = ds["periods"][-1]["label"]
    H = assumptions["horizon_quarters"]
    periods = next_periods(start, H)
    fac = facility_amount(ds, deal, assumptions["facility"]["fx_rate"])
    F = fac["value"] or 0.0
    N = assumptions["facility"]["tenor_quarters"]
    rep = assumptions["facility"]["repayment"]
    nq = cfg["short_term_debt_repayment_quarters"]
    ebitda_hist = [v for _, v in _series(ds, "EBITDA")][-3:]
    rev0, debt0, std0, cash0, int0 = (first[k][1] for k in ("REVENUE", "TOTAL_DEBT", "SHORT_TERM_DEBT", "CASH", "INTEREST_EXPENSE"))

    scenarios = {}
    for s, slabel in SCENARIOS:
        a = assumptions["scenarios"][s]
        g, m, c, di, r = (a[p] / 100 for p in ("revenue_growth", "ebitda_margin", "capex_pct_revenue", "interest_change", "facility_rate"))
        rev, cash, cum_std, bal = rev0, cash0, 0.0, F
        window = list(ebitda_hist)
        rows = {k: [] for k, _, _ in OUTPUT_METRICS}
        for t in range(1, H + 1):
            rev = rev * (1 + g)
            ebitda = rev * m
            capex = rev * c
            cfads = ebitda - capex
            interest = int0 * (1 + di) + bal * r / 4
            std_pay = std0 / nq if t <= nq else 0.0
            fac_pay = (F / N if t <= N else 0.0) if rep == "amortising" else (F if t == N else 0.0)
            fac_pay = min(fac_pay, bal)
            bal -= fac_pay
            principal = std_pay + fac_pay
            service = interest + principal
            cum_std += std_pay
            debt = debt0 - cum_std + bal
            window = (window + [ebitda])[-4:]
            ltm = sum(window) if len(window) == 4 and all(v is not None for v in window) else None
            cash = cash + cfads - service
            vals = {"REVENUE": rev, "EBITDA": ebitda, "CAPEX": capex, "CFADS": cfads, "INTEREST_EXPENSE": interest,
                    "PRINCIPAL": principal, "DEBT_SERVICE": service,
                    "DSCR": cfads / service if service > 0 else None,
                    "INTEREST_COVERAGE": ebitda / interest if interest > 0 else None,
                    "TOTAL_DEBT": debt, "DEBT_EBITDA": debt / ltm if ltm and ltm > 0 else None,
                    "CASH": cash, "FACILITY_BALANCE": bal}
            for k, v in vals.items():
                rows[k].append({"period": periods[t - 1], "value": v, "display": _display(v, METRIC_UNIT[k], places),
                                "evidence_id": f"FC-{s.upper()}-{k}-{periods[t - 1]}", "breach": None})
        scenarios[s] = {"key": s, "label": slabel, "series": rows}

    breaches = _apply_thresholds(scenarios, assumptions["thresholds"], places)
    for s in scenarios.values():
        s["summary"] = _summary(s)
    return {"periods": periods, "start_period": start, "scenarios": scenarios, "breaches": breaches, "facility": fac,
            "start_values": {k: {"period": v[0], "display": _display(v[1], "amount", places) if k != "REVENUE_GROWTH" and k != "EBITDA_MARGIN"
                                 else _display(v[1], "percent", places)} for k, v in first.items()}}


def _apply_thresholds(scenarios: dict, thresholds: dict, places: int) -> list[dict]:
    out = []
    for key, label, unit, metric, kind in THRESHOLDS:
        t = thresholds.get(key)
        if t is None:
            continue
        for s in scenarios.values():
            for pt in s["series"][metric]:
                v = pt["value"]
                if v is None:
                    hit = kind == "max" and metric == "DEBT_EBITDA"  # n/m: EBITDA over the last 4 quarters is zero or negative
                else:
                    hit = v < t if kind == "min" else v > t
                if hit:
                    pt["breach"] = {"threshold": key, "label": label, "threshold_display": _display(t, unit, places)}
                    out.append({"scenario": s["key"], "metric_key": metric, "metric_label": METRIC_LABEL[metric], "period": pt["period"],
                                "display": pt["display"], "evidence_id": pt["evidence_id"], "threshold": key, "threshold_label": label,
                                "threshold_display": _display(t, unit, places), "threshold_id": f"FT-{key.upper()}"})
    return out


def _summary(s: dict) -> dict:
    def pick(metric, fn, nm_worst=False):
        pts = s["series"][metric]
        if nm_worst and any(p["value"] is None for p in pts):
            p = next(p for p in pts if p["value"] is None)
        else:
            vals = [p for p in pts if p["value"] is not None]
            if not vals:
                return None
            p = fn(vals, key=lambda x: x["value"])
        return {"period": p["period"], "display": p["display"], "evidence_id": p["evidence_id"]}
    shortfall = [p["period"] for p, d in zip(s["series"]["CFADS"], s["series"]["DEBT_SERVICE"]) if p["value"] < d["value"]]
    return {"min_dscr": pick("DSCR", min), "min_interest_coverage": pick("INTEREST_COVERAGE", min),
            "max_debt_ebitda": pick("DEBT_EBITDA", max, nm_worst=True), "min_cash": pick("CASH", min),
            "final_cash": {"period": s["series"]["CASH"][-1]["period"], "display": s["series"]["CASH"][-1]["display"],
                           "evidence_id": s["series"]["CASH"][-1]["evidence_id"]},
            "shortfall_quarters": shortfall}


# --------------------------------------------------------------------------- evidence
def build_evidence(ds: dict, result: dict, assumptions: dict, sources: dict) -> dict:
    places = ds.get("amount_decimals", 0)
    unit_label = ds.get("currency_unit")
    ev = {}
    for s in result["scenarios"].values():
        for k, pts in s["series"].items():
            for pt in pts:
                ev[pt["evidence_id"]] = {"evidence_id": pt["evidence_id"], "type": "forecast", "scenario": s["key"], "scenario_label": s["label"],
                                         "metric_key": k, "metric_label": METRIC_LABEL[k], "period": pt["period"], "display": pt["display"],
                                         "value": None if pt["value"] is None else repr(pt["value"]), "unit": METRIC_UNIT[k],
                                         "unit_label": unit_label if METRIC_UNIT[k] == "amount" else None}
    for s, slabel in SCENARIOS:
        for p, label in PARAMS:
            i = f"FA-{s.upper()}-{p.upper()}"
            ev[i] = {"evidence_id": i, "type": "forecast_assumption", "scenario": s, "scenario_label": slabel, "param": p, "label": label,
                     "display": _display(assumptions["scenarios"][s][p], "percent", 2), "source": sources[s][p]}
    fac = result["facility"]
    f = assumptions["facility"]
    common = [
        ("FA-FACILITY_AMOUNT", "Requested facility in database units",
         (f"{_display(fac['value'], 'amount', places)} {unit_label}" if fac["value"] is not None else "Not included: " + (fac["warning"] or "")),
         f"Deal intake DI-AMOUNT ({fac['deal_amount']})" + (f" at {fac['fx_rate']:g} {fac['company_currency']} per {fac['deal_currency']}" if fac["fx_rate"] not in (None, 1.0) else "")),
        ("FA-FACILITY_REPAYMENT", "Facility repayment", REPAYMENT_LABEL[f["repayment"]], "Default read from DI-REPAYMENT; analyst may change"),
        ("FA-FACILITY_TENOR", "Facility tenor", f"{f['tenor_quarters']} quarters", "Default read from DI-TENOR; analyst may change"),
        ("FA-HORIZON", "Forecast horizon", f"{assumptions['horizon_quarters']} quarters", "Analyst setting"),
    ]
    for i, label, display, source in common:
        ev[i] = {"evidence_id": i, "type": "forecast_assumption", "scenario": None, "param": i[3:].lower(), "label": label,
                 "display": display, "source": source}
    for key, label, unit, _, _ in THRESHOLDS:
        t = assumptions["thresholds"].get(key)
        if t is not None:
            i = f"FT-{key.upper()}"
            ev[i] = {"evidence_id": i, "type": "forecast_threshold", "threshold": key, "label": label,
                     "display": _display(t, unit, places), "source": "Entered by the analyst"}
    return ev


# --------------------------------------------------------------------------- deal entry points
def for_deal(repo, deal: dict, settings, dataset: dict | None = None, assumptions_override: dict | None = None) -> dict:
    """Full forecast state for a deal: saved (or default) assumptions, results and evidence."""
    ds = dataset if dataset is not None else repo.read(deal["deal_id"], "financial/dataset.json")
    cfg = settings.forecast
    missing = missing_inputs(ds)
    if missing:
        return {"available": False, "evidence": {},
                "message": "The forecast needs these values from the financial database: " + ", ".join(missing)
                           + ". Reconnect the financial database in Section 2 if the deal was created before the workbook was installed."}
    defaults = default_assumptions(ds, deal, cfg)
    saved = repo.read(deal["deal_id"], "forecast/assumptions.json")
    if assumptions_override is not None:
        assumptions = validate_assumptions(assumptions_override, defaults, cfg)
        status = {"state": "preview"}
    elif saved:
        assumptions = validate_assumptions(saved, defaults, cfg)
        status = {"state": "saved", "saved_by": saved.get("saved_by"), "saved_at": saved.get("saved_at")}
    else:
        assumptions = defaults
        status = {"state": "default"}
    stats = history_stats(ds)
    sources = assumption_sources(assumptions, defaults, stats, cfg)
    result = compute(ds, deal, assumptions, cfg)
    warnings = []
    if result["facility"]["warning"]:
        warnings.append(result["facility"]["warning"])
    if assumptions["facility"]["tenor_quarters"] > assumptions["horizon_quarters"]:
        warnings.append(f"The facility tenor ({assumptions['facility']['tenor_quarters']} quarters) is longer than the forecast horizon "
                        f"({assumptions['horizon_quarters']} quarters), so repayments after the horizon"
                        + (" (including the bullet repayment)" if assumptions["facility"]["repayment"] == "bullet" else "") + " are not shown.")
    history = {}
    for k, src in HISTORY_COMPARABLE.items():
        m = next((m for m in ds["metrics"] if m["key"] == src), None)
        if m:
            history[k] = [{"period": e["period"], "value": None if e["value"] is None else float(e["value"]), "display": e["display"],
                           "evidence_id": e["evidence_id"]} for e in m["entries"]]
    return {"available": True, "status": status, "company": ds.get("company"), "currency_unit": ds.get("currency_unit"),
            "assumptions": assumptions, "defaults": defaults, "sources": sources, "history_stats": stats,
            "params": [{"key": p, "label": l, "limits": PARAM_LIMITS[p]} for p, l in PARAMS],
            "thresholds_def": [{"key": k, "label": l, "unit": u, "metric": m, "kind": kind} for k, l, u, m, kind in THRESHOLDS],
            "metrics_def": [{"key": k, "label": l, "unit": u} for k, l, u in OUTPUT_METRICS],
            "periods": result["periods"], "start_period": result["start_period"], "start_values": result["start_values"],
            "scenarios": result["scenarios"], "breaches": result["breaches"], "facility": result["facility"],
            "history": history, "history_periods": [p["label"] for p in ds["periods"]],
            "warnings": warnings, "notes": NOTES, "max_horizon_quarters": cfg["max_horizon_quarters"],
            "evidence": build_evidence(ds, result, assumptions, sources)}


def _key_periods(s: dict, periods: list[str]) -> list[str]:
    """Quarters sent to the AI: first, last, and every quarter a summary figure refers to (lowest DSCR,
    first shortfall, ...). The dashboard still shows every quarter; the AI only quotes what it receives."""
    sm = s["summary"]
    keep = {periods[0], periods[-1]}
    for k in ("min_dscr", "min_interest_coverage", "max_debt_ebitda", "min_cash", "final_cash"):
        if sm.get(k):
            keep.add(sm[k]["period"])
    if sm["shortfall_quarters"]:
        keep.add(sm["shortfall_quarters"][0])
    return [p for p in periods if p in keep]


def _first_breaches(breaches: list[dict]) -> list[dict]:
    """First breach per scenario and threshold, with how many forecast quarters breach it."""
    out, seen = [], {}
    for b in breaches:
        key = (b["scenario"], b["threshold"])
        if key in seen:
            seen[key]["quarters_breached"] += 1
            continue
        rec = {k: b[k] for k in ("scenario", "metric_label", "period", "display", "evidence_id", "threshold_label",
                                 "threshold_display", "threshold_id")}
        rec["quarters_breached"] = 1
        seen[key] = rec
        out.append(rec)
    return out


def ai_payload(fc: dict) -> dict | None:
    """Compact forecast input for the AI sections: only backend values with their Evidence IDs."""
    if not fc or not fc.get("available"):
        return None
    ev = fc["evidence"]
    st = fc["status"]
    status = (f"Assumptions saved by the analyst ({st.get('saved_by')}, {st.get('saved_at')})" if st["state"] == "saved"
              else "Historical-average defaults; not yet reviewed by the analyst")
    return {
        "status": status,
        "currency_unit": fc["currency_unit"],
        "start_period": fc["start_period"],
        "periods": fc["periods"],
        "assumptions": [{"evidence_id": i, "scenario": e["scenario"], "label": e["label"], "display": e["display"], "source": e["source"]}
                        for i, e in ev.items() if e["type"] == "forecast_assumption"],
        "analyst_thresholds": [{"evidence_id": i, "label": e["label"], "display": e["display"]} for i, e in ev.items() if e["type"] == "forecast_threshold"],
        "scenarios": [{"scenario": s["key"], "label": s["label"], "key_quarters": _key_periods(s, fc["periods"]),
                       "metrics": [{"metric_key": k, "label": METRIC_LABEL[k],
                                    "values": [{"evidence_id": p["evidence_id"], "display": p["display"]} for p in s["series"][k]
                                               if p["period"] in _key_periods(s, fc["periods"])]}
                                   for k in AI_METRICS],
                       "summary": s["summary"]} for s in fc["scenarios"].values()],
        "threshold_breaches": _first_breaches(fc["breaches"]),
        "warnings": fc["warnings"],
        "model_notes": fc["notes"],
    }
