"""CSV_Loader, values, anomaly flags and comparisons (Req 8-12, 29.1-29.4)."""
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.financial import (CANONICAL_KEYS, LoadError, build_comparisons, build_dashboard, change_display, direction,
                           format_value, load_csv, map_label, parse_cell, parse_period_header, raw_change)
from app.settings import DEFAULT_LARGE_SWING, DEFAULT_STABLE_BAND, resolve_stable_bands, resolve_thresholds
from conftest import ROOT

INTEL = ROOT / "intel_quarterly_ratios.csv"


def load(path=INTEL, confirm=True):
    return load_csv(path, "Intel Corporation", confirm, DEFAULT_LARGE_SWING, DEFAULT_STABLE_BAND)


def test_golden_intel_csv():
    res = load()
    ds = res["dataset"]
    assert [p["label"] for p in ds["periods"]] == ["Q3-2025", "Q4-2025", "Q1-2026", "Q2-2026"]
    assert [m["key"] for m in ds["metrics"]] == CANONICAL_KEYS
    assert all(m["recognised"] for m in ds["metrics"])
    assert sum(len(m["entries"]) for m in ds["metrics"]) == 40 == len(res["evidence"])
    assert len(ds["comparisons"]) == 30
    by = {m["key"]: {e["period"]: e for e in m["entries"]} for m in ds["metrics"]}
    assert by["DSCR"]["Q2-2026"]["display"] == "0.64x" and by["DSCR"]["Q2-2026"]["evidence_id"] == "CSV-DSCR-Q2-2026"
    assert by["INTEREST_COVERAGE"]["Q2-2026"]["display"] == "5.6x"
    assert by["OPERATING_CASH_FLOW"]["Q3-2025"]["display"] == "2546"
    assert by["DSO"]["Q1-2026"]["unit"] == "days"
    # anomaly flags (Req 29.4)
    assert "zero value" in by["EBITDA_MARGIN"]["Q1-2026"]["flags"] and "zero value" in by["DSCR"]["Q1-2026"]["flags"]
    assert by["EBITDA_MARGIN"]["Q1-2026"]["value"] == "0.00"  # zero is used as the real value
    assert "negative value" in by["INTEREST_COVERAGE"]["Q1-2026"]["flags"]
    assert "negative value" not in by["REVENUE_GROWTH"]["Q4-2025"]["flags"]
    assert all("unit not stated" in e["flags"] for k in ("OPERATING_CASH_FLOW", "WORKING_CAPITAL") for e in by[k].values())
    assert "large swing" in by["DSCR"]["Q4-2025"]["flags"] and "large swing" not in by["DSCR"]["Q2-2026"]["flags"]
    assert all(not d["assessable"] for d in ds["divergence"])
    assert "Database has no borrower identifier" in ds["information_gaps"]


def test_needs_confirmation_and_decline():
    assert load(confirm=None)["status"] == "needs_confirmation"
    with pytest.raises(LoadError):
        load(confirm=False)


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
    dash = build_dashboard(load()["dataset"])
    assert [p["key"] for p in dash["panels"]] == ["profitability", "leverage", "liquidity", "cash_flow", "debt_servicing"]
    prof = dash["panels"][0]
    assert "Revenue" in prof["not_available"] and prof["metrics"][0]["latest"]["display"] == "25.40%"


def test_threshold_fallback():
    vals, defaulted = resolve_thresholds({"percent": -1, "multiple": "x", "days": 0, "amount": 40})
    assert vals == {"percent": 10.0, "multiple": 2.0, "days": 5.0, "amount": 40.0} and defaulted == ["percent", "multiple", "days"]
    bands, d2 = resolve_stable_bands({"percent": 0, "multiple": -1})
    assert bands["percent"] == 0 and "multiple" in d2
