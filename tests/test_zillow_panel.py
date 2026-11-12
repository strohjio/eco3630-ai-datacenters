"""Tests for the Zillow step and the analysis panel. Run with:  pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import zillow  # noqa: E402
from src.panel import build_panel, event_means  # noqa: E402


def _wide():
    return pd.DataFrame({
        "RegionID": [1, 2], "SizeRank": [1, 2], "RegionName": ["501", "20147"],
        "RegionType": "zip", "StateName": ["NY", "VA"], "State": ["NY", "VA"],
        "City": ["Holtsville", "Ashburn"], "Metro": ["", ""], "CountyName": ["", ""],
        "2018-12-31": [100.0, np.nan], "2019-01-31": [101.0, 500.0], "2019-02-28": [102.0, 505.0],
    })


def test_to_long_shape_and_types():
    long = zillow.to_long(_wide().assign(RegionName=lambda d: d.RegionName.str.zfill(5)), "zhvi")
    assert list(long.columns) == ["geo_id", "geo_type", "month", "variable", "value"]
    assert set(long.geo_id) == {"00501", "20147"}            # leading zero kept
    assert (long.month.dt.day == 1).all()                   # month-end -> month start
    assert len(long) == 5                                   # blank cell dropped


def test_to_long_start_filter():
    long = zillow.to_long(_wide(), "zhvi", start="2019-01-01")
    assert long.month.min() == pd.Timestamp("2019-01-01")


def _write(tmp, name, df):
    df.to_csv(tmp / name, index=False)


def test_find_prefers_full_then_study_then_parts(tmp_path):
    w = _wide()
    _write(tmp_path, "Zip_zhvi_uc_sfrcondo_x_month_study_part1.csv", w.iloc[:1])
    _write(tmp_path, "Zip_zhvi_uc_sfrcondo_x_month_study_part2.csv", w.iloc[1:])
    found = zillow.find_raw_files("zhvi", tmp_path)
    assert len(found) == 2 and all("_part" in f.stem for f in found)
    assert len(zillow.read_wide(found)) == 2                 # pieces rejoin
    _write(tmp_path, "Zip_zhvi_uc_sfrcondo_x_month_study.csv", w)
    assert zillow.find_raw_files("zhvi", tmp_path)[0].stem.endswith("_study")
    _write(tmp_path, "Zip_zhvi_uc_sfrcondo_x_month.csv", w)
    assert zillow.find_raw_files("zhvi", tmp_path)[0].stem.endswith("_month")


def test_find_missing_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="zillow.com/research/data"):
        zillow.find_raw_files("zori", tmp_path)


def test_read_wide_rejects_duplicate_pieces(tmp_path):
    _write(tmp_path, "a.csv", _wide())
    with pytest.raises(ValueError, match="twice"):
        zillow.read_wide([tmp_path / "a.csv", tmp_path / "a.csv"])


# ---------------------------------------------------------------- panel
def _panel_inputs():
    months = pd.date_range("2023-01-01", "2025-12-01", freq="MS")
    rows = []
    for geo, growth in (("T1", 0.010), ("C1", 0.005), ("C2", 0.005)):
        rows.append(pd.DataFrame({"geo_id": geo, "month": months,
                                  "value": 100 * (1 + growth) ** np.arange(len(months))}))
    outcome = pd.concat(rows, ignore_index=True)
    treated = pd.DataFrame({"geo_id": ["T1"], "treat_month": [pd.Timestamp("2025-01-01")]})
    controls = pd.DataFrame({"geo_id": ["C1", "C2"], "match_id": ["T1", "T1"]})
    return outcome, treated, controls


def test_panel_controls_borrow_treatment_date():
    p = build_panel(*_panel_inputs())
    jan25 = p[p.month == "2025-01-01"]
    assert (jan25.event_time == 0).all() and len(jan25) == 3
    assert set(p.treated) == {0, 1}


def test_panel_since_treat_is_zero_at_month_minus_one():
    p = build_panel(*_panel_inputs())
    assert (p.loc[p.event_time == -1, "since_treat"].abs() < 1e-12).all()


def test_event_means_gap_matches_growth_difference():
    p = build_panel(*_panel_inputs())
    m = event_means(p).set_index("event_time")
    expected = (1.010 ** 12 - 1) - (1.005 ** 12 - 1)   # 12 months after month -1
    assert m.loc[11, "gap"] == pytest.approx(expected, rel=1e-9)
