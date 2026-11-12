"""Tests for Phase 1: treatment tables, control pools, and matching.
Run all tests with:  pytest -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.geo import candidate_counties, candidate_zips, miles  # noqa: E402
from src.io_utils import load_site_panel, sample  # noqa: E402
from src.matching import balance_table, match_controls, pre_period_features  # noqa: E402
from src.treatment import build_treated, treated_sites  # noqa: E402


@pytest.fixture(scope="module")
def panel():
    return load_site_panel()


# ---------------------------------------------------------------- treatment
def test_strict_zip_table_collapses_shared_zip(panel):
    t = build_treated(panel, "strict", "zip")
    assert t.geo_id.is_unique
    memphis = t[t.geo_id == "38109"].iloc[0]
    assert memphis.n_sites == 2                           # Colossus 1 + 2
    assert memphis.treat_month == pd.Timestamp("2024-09-01")  # the earlier one


def test_zip_level_uses_facility_address_zips_only(panel):
    t = build_treated(panel, "strict", "zip")
    s = sample(panel, "strict")
    allowed = set(s.loc[s.zip_basis == "facility address", "zip"])
    assert set(t.geo_id) <= allowed


def test_county_table_has_fips_ids(panel):
    t = build_treated(panel, "strict", "county")
    assert t.geo_id.str.fullmatch(r"\d{5}").all() and t.geo_id.is_unique


def test_broad_sample_every_site_has_a_date(panel):
    s = treated_sites(panel, "broad")
    assert s.treat_month.notna().all()
    assert (s.treat_month.dt.day == 1).all()


def test_strict_dates_unchanged_in_broad(panel):
    strict = treated_sites(panel, "strict").set_index("site_id").treat_month
    broad = treated_sites(panel, "broad").set_index("site_id").treat_month
    assert (broad.loc[strict.index] == strict).all()


# ---------------------------------------------------------------- geography
def test_miles_known_distance():
    # New York City to Philadelphia is about 80 miles
    assert 75 < miles(40.7128, -74.0060, 39.9526, -75.1652) < 85


def test_candidates_respect_the_rules(panel):
    treated = build_treated(panel, "strict", "zip")
    c = candidate_zips(panel, treated)
    assert (c.miles_to_nearest_site >= 15).all()
    assert not c.county_fips.isin(set(panel.county_fips)).any()
    assert set(c.state) <= set(treated.state)
    assert not c.zip.isin(treated.geo_id).any()
    assert c.groupby("state").size().min() >= 10      # enough to pick 10 controls


def test_candidate_counties_exclude_hosts(panel):
    treated = build_treated(panel, "strict", "county")
    c = candidate_counties(panel, treated)
    assert not c.county_fips.isin(set(panel.county_fips)).any()


# ---------------------------------------------------------------- matching
def _fake_zhvi(growth_by_zip, months, start_level=200_000):
    t = np.arange(len(months)) / 12
    rows = [pd.DataFrame({"geo_id": z, "month": months,
                          "value": start_level * np.exp(g * t)})
            for z, g in growth_by_zip.items()]
    return pd.concat(rows, ignore_index=True)


def test_pre_period_features_recovers_growth():
    months = pd.date_range("2021-01-01", "2025-12-01", freq="MS")
    long = _fake_zhvi({"11111": 0.05}, months)
    f = pre_period_features(long, {"11111"}, pd.Timestamp("2025-01-01"))
    assert f.n_months.iloc[0] == 36
    assert f.growth.iloc[0] == pytest.approx(0.05, abs=1e-6)


def test_match_picks_controls_with_closest_growth():
    months = pd.date_range("2020-01-01", "2026-06-01", freq="MS")
    growth = {"00001": 0.06}                                     # treated
    growth |= {f"1{i:04d}": 0.02 + 0.002 * i for i in range(30)}  # 2% to 7.8%
    long = _fake_zhvi(growth, months)
    treated = pd.DataFrame({"geo_id": ["00001"], "state": ["XX"],
                            "treat_month": [pd.Timestamp("2025-01-01")]})
    cand = pd.DataFrame({"zip": [z for z in growth if z != "00001"], "state": "XX"})

    controls, report = match_controls(treated, cand, long, n=5)
    assert report.matched.all() and len(controls) == 5
    assert (controls.growth - 0.06).abs().max() < 0.0061  # the five nearest to 6%
    bal = balance_table(report, controls)
    assert abs(bal.growth_gap_pts.iloc[0]) < 0.3


def test_match_reports_short_history():
    months = pd.date_range("2024-06-01", "2026-06-01", freq="MS")
    long = _fake_zhvi({"00001": 0.05, "10000": 0.05}, months)
    treated = pd.DataFrame({"geo_id": ["00001"], "state": ["XX"],
                            "treat_month": [pd.Timestamp("2025-01-01")]})
    cand = pd.DataFrame({"zip": ["10000"], "state": ["XX"]})
    controls, report = match_controls(treated, cand, long, n=1)
    assert not report.matched.iloc[0]
    assert "24 months" in report.reason.iloc[0]
