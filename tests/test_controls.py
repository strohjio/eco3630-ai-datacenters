"""Tests for the control variables. Run with:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import controls as ct  # noqa: E402
from src.io_utils import check_long_format  # noqa: E402


def _cpi():
    months = pd.date_range("2024-01-01", "2025-12-01", freq="MS")
    v = [100.0] * 12 + [110.0] * 12                    # 10% inflation between the years
    return pd.DataFrame({"geo_id": "US", "geo_type": "nation", "month": months, "variable": "cpi", "value": v})


def test_deflate_monthly_and_yearly_values():
    long = pd.DataFrame({"geo_id": ["01001", "01001"], "geo_type": "county",
                         "month": pd.to_datetime(["2024-06-01", "2024-01-01"]),
                         "variable": "x", "value": [100.0, 100.0]})
    out = ct.deflate(long, _cpi(), base="2025-01-01")
    assert out.value_real.tolist() == pytest.approx([110.0, 110.0])   # 2024 dollars -> 2025 dollars


def test_fred_weekly_series_averaged_by_month(tmp_path):
    (tmp_path / "fred_MORTGAGE30US.csv").write_text(
        "observation_date,MORTGAGE30US\n2026-10-01,7.0\n2026-10-08,7.2\n2026-11-05,7.1\n")
    out = ct.fred("MORTGAGE30US", raw=tmp_path)
    check_long_format(out)
    assert out.set_index("month").value[pd.Timestamp("2026-10-01")] == pytest.approx(7.1)
    assert (out.geo_type == "nation").all()


def test_laus_dash_means_not_collected(tmp_path):
    rows = [["Labor force data by county", "", "", "", "", "", "", "", ""],
            ["LAUS Code", "State FIPS Code", "County FIPS Code", "County Name/State Abbreviation",
             "Period", "Labor Force", "Employed", "Unemployed", "Unemploy-ment Rate (%)"],
            ["CN01001", "01", "001", "Autauga County, AL", "Sep-25", "100", "96", "4", "4.0"],
            ["CN01001", "01", "001", "Autauga County, AL", "Oct-25", "–", "–", "–", "–"]]
    pd.DataFrame(rows).to_excel(tmp_path / "laucntycur14.xlsx", header=False, index=False)
    out = ct.laus_monthly(raw=tmp_path)
    assert len(out) == 1 and out.value.iloc[0] == 4.0      # October 2025 dropped, not zero


def test_balance_counts_each_host_once():
    county = pd.DataFrame({"geo_id": ["H1", "C1", "C2", "C3"], "geo_type": "county",
                           "month": pd.Timestamp("2023-01-01"), "variable": "poverty_rate",
                           "value": [10.0, 20.0, 30.0, 12.0]})
    hosts = pd.DataFrame({"geo_id": ["H1"]})
    ctrl = pd.DataFrame({"geo_id": ["C1", "C2"], "match_id": ["H1", "H1"]})
    b = ct.balance(county, hosts, ctrl)
    assert b.loc["poverty_rate", "comparison_counties"] == 25.0
    assert b.loc["poverty_rate", "difference"] == -15.0
