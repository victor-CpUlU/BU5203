"""CSV_Loader, values, anomaly flags and comparisons (Req 8-12, 29.1-29.4)."""
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.financial import (CANONICAL_KEYS, LoadError, build_comparisons, build_dashboard, change_display, direction,
                           format_value, load_csv, load_workbook, map_label, parse_cell, parse_period_header, raw_change)
from app.settings import DEFAULT_LARGE_SWING, DEFAULT_STABLE_BAND, resolve_stable_bands, resolve_thresholds
from conftest import ROOT

WORKBOOK = ROOT / "Semiconductor_Financial_Performance_Indicators_Combined.xlsx"
SMALL_CSV = "Metric,Q1 2026 (Mar 28 2026),Q2 2026 (Jun 27 2026)\nDSCR,0.00x,0.64x\nOperating Cash Flow,1096,7006\n"


def load(path, confirm=True):
    return load_csv(path, "Intel Corporation", confirm, DEFAULT_LARGE_SWING, DEFAULT_STABLE_BAND)


def load_wb(borrower="Intel Corporation"):
    return load_workbook(WORKBOOK, borrower, DEFAULT_LARGE_SWING, DEFAULT_STABLE_BAND)


def test_golden_intel_workbook():
    res = load_wb()
    ds = res["dataset"]
    assert ds["sheet"] == "Intel" and ds["company"] == "Intel Corporation" and ds["currency_unit"] == "USD m"
    assert [p["label"] for p in ds["periods"]] == ["Q3-FY2025", "Q4-FY2025", "Q1-FY2026", "Q2-FY2026"]
    assert [m["key"] for m in ds["metrics"]] == CANONICAL_KEYS
    assert all(m["recognised"] for m in ds["metrics"])
    assert sum(len(m["entries"]) for m in ds["metrics"]) == 4 * len(CANONICAL_KEYS) == len(res["evidence"])
    by = {m["key"]: {e["period"]: e for e in m["entries"]} for m in ds["metrics"]}
    # values follow the workbook's own formulas (Debt/EBITDA LTM matches the earlier Intel database figure)
    assert by["DEBT_EBITDA"]["Q2-FY2026"]["display"] == "4.11x" and by["DEBT_EBITDA"]["Q2-FY2026"]["evidence_id"] == "CSV-DEBT_EBITDA-Q2-FY2026"
    assert by["DSCR"]["Q2-FY2026"]["display"] == "0.90x" and by["DSCR"]["Q2-FY2026"]["cell"] == "Intel!C29"
    assert by["INTEREST_COVERAGE"]["Q2-FY2026"]["display"] == "5.60x"
    assert by["OPERATING_CASH_FLOW"]["Q3-FY2025"]["display"] == "2,546" and by["REVENUE_GROWTH"]["Q2-FY2026"]["display"] == "18.79%"
    assert by["DSO"]["Q1-FY2026"]["unit"] == "days"
    # anomaly flags (Req 29.4)
    assert "zero value" in by["EBITDA_MARGIN"]["Q1-FY2026"]["flags"] and by["EBITDA_MARGIN"]["Q1-FY2026"]["value"] == "0.00"
    assert "negative value" in by["INTEREST_COVERAGE"]["Q1-FY2026"]["flags"]
    assert "negative value" not in by["REVENUE_GROWTH"]["Q1-FY2026"]["flags"]
    assert not any("unit not stated" in e["flags"] for m in by.values() for e in m.values())  # the workbook states USD m
    assert "large swing" in by["DSCR"]["Q4-FY2025"]["flags"] and "large swing" not in by["DSCR"]["Q2-FY2026"]["flags"]
    assert all(d["assessable"] for d in ds["divergence"]) and ds["unavailable_metrics"] == ["Net Profit Margin"]


def test_workbook_borrower_matching():
    assert load_wb("Micron Technology, Inc.")["dataset"]["sheet"] == "Micron"
    assert load_wb("Taiwan Semiconductor Manufacturing Company Limited")["dataset"]["currency_unit"] == "NT$ bn"
    micron = {m["key"]: m for m in load_wb("Micron Technology")["dataset"]["metrics"]}
    assert micron["INTEREST_COVERAGE"]["entries"][-1]["display"] == "n/m"
    with pytest.raises(LoadError, match="No company"):
        load_wb("Acme Semiconductors")


def test_needs_confirmation_and_decline(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(SMALL_CSV)
    assert load(p, confirm=None)["status"] == "needs_confirmation"
    with pytest.raises(LoadError):
        load(p, confirm=False)
    ds = load(p)["dataset"]
    assert "Database has no borrower identifier" in ds["information_gaps"]
    assert all("unit not stated" in e["flags"] for m in ds["metrics"] if m["key"] == "OPERATING_CASH_FLOW" for e in m["entries"])


def test_label_mapping_and_header_parsing():
    assert map_label("Operating Cash Flow ") == ("OPERATING_CASH_FLOW", True)
    assert map_label("Debt-Service Coverage Ratio (DSCR)") == ("DSCR", True)
    assert map_label("Some Other Thing") == ("SOME_OTHER_THING", False)
    p = parse_period_header("Q2 2026 (Jun 27 2026)")
    assert p["label"] == "Q2-2026" and p["end_date"] == "2026-06-27"
    with pytest.raises(LoadError):
        parse_period_header("June 2026")


def test_cells():
    assert parse_cell("25.40%", "X")["unit"] == "percent"
    assert parse_cell("5.6x", "X")["unit"] == "multiple"
    assert parse_cell("22.8", "DSO")["unit"] == "days"
    assert parse_cell("7006", "OPERATING_CASH_FLOW")["unit"] == "amount"
    bad = parse_cell("N/A", "DSCR")
    assert bad["value"] is None and bad["display"] == "Not available in database" and bad["flags"] == ["unparseable value"]


def test_unrecognised_metric_and_bad_header(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("Metric,Q1 2026 (Mar 28 2026)\nMystery Ratio,1.0x\nDSCR,\n")
    ds = load(p)["dataset"]
    assert any(m["key"] == "MYSTERY_RATIO" and m["flags"] == ["Unrecognised metric"] for m in ds["metrics"])
    p.write_text("Metric,Quarter two\nCurrent Ratio,1.0x\n")
    with pytest.raises(LoadError, match="Quarter two"):
        load(p)


@given(st.decimals(min_value=Decimal("-999999999.99"), max_value=Decimal("999999999.99"), places=2, allow_nan=False),
       st.sampled_from(["percent", "multiple", "amount"]), st.integers(min_value=0, max_value=2))
def test_format_parse_round_trip(value, unit, decimals):
    text = format_value(value, unit, decimals)
    cell = parse_cell(text, "OPERATING_CASH_FLOW" if unit == "amount" else "X")
    assert cell["unit"] == unit and cell["decimals"] == decimals
    assert format_value(cell["value"], unit, decimals) == text


@given(st.decimals(min_value=-50, max_value=50, places=2), st.decimals(min_value=-50, max_value=50, places=2))
def test_direction_follows_stable_band(a, b):
    ch = raw_change("percent", a, b)
    d = direction(ch, 1.0, b)
    assert d == ("~" if abs(ch) <= 1 else "up" if ch > 0 else "down")


def test_comparisons_only_adjacent_non_null():
    metrics = [{"key": "DSCR", "label": "DSCR", "unit_type": "multiple", "entries": [
        {"period": "Q1-2025", "value": "1.0", "evidence_id": "a"}, {"period": "Q2-2025", "value": None, "evidence_id": "b"},
        {"period": "Q3-2025", "value": "2.0", "evidence_id": "c"}, {"period": "Q4-2025", "value": "2.5", "evidence_id": "d"}]}]
    comps = build_comparisons(metrics, DEFAULT_STABLE_BAND)
    assert [(c["from_period"], c["to_period"]) for c in comps] == [("Q3-2025", "Q4-2025")]
    assert comps[0]["change_display"] == "+0.50x" and comps[0]["direction"] == "up"
    assert change_display("amount", None) == "Not computable"


def test_dashboard_panels():
    dash = build_dashboard(load_wb()["dataset"])
    assert [p["key"] for p in dash["panels"]] == ["profitability", "leverage", "liquidity", "cash_flow", "debt_servicing"]
    prof = dash["panels"][0]
    assert prof["not_available"] == ["Net Profit Margin"] and prof["metrics"][0]["latest"]["display"] == "16,128"


def test_threshold_fallback():
    vals, defaulted = resolve_thresholds({"percent": -1, "multiple": "x", "days": 0, "amount": 40})
    assert vals == {"percent": 10.0, "multiple": 2.0, "days": 5.0, "amount": 40.0} and defaulted == ["percent", "multiple", "days"]
    bands, d2 = resolve_stable_bands({"percent": 0, "multiple": -1})
    assert bands["percent"] == 0 and "multiple" in d2
