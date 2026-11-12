"""Tests for the hand-collected property tax and water data. Run with:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import water_tax as wt  # noqa: E402
from src.io_utils import check_long_format  # noqa: E402


def _tax():
    return pd.DataFrame({
        "site_id": ["A", "A", "A", "B", "B"], "place": ["X", "X", "X", "Y", "Y"],
        "state": ["IN"] * 3 + ["TN"] * 2, "county_fips": ["18003"] * 3 + ["47157"] * 2,
        "tax_year": [2024, 2024, 2025, 2024, 2024],
        "component": ["total_district"] * 3 + ["city", "total_district"],
        "district": ["d1", "d2", "d1", "city", "all"], "primary": [True, True, True, False, True],
        "rate_per_100": [2.0, 3.0, 2.2, 3.0, 6.0], "source_url": "x"})


def _water():
    return pd.DataFrame({
        "site_id": ["A", "A"], "effective_date": pd.to_datetime(["2024-03-15", "2025-01-01"]),
        "monthly_bill": [20.0, 25.0], "water_only": [True, True], "derived": [False, False],
        "source_url": "x"})


def test_two_primary_districts_are_averaged():
    s = wt.tax_series(_tax()).set_index(["site_id", "tax_year"]).rate_per_100
    assert s[("A", 2024)] == 2.5                      # (2.0 + 3.0) / 2
    assert s[("B", 2024)] == 6.0                      # non-primary city row ignored


def test_tax_long_fills_each_tax_year_with_twelve_months():
    long = wt.tax_long(_tax())
    check_long_format(long)
    a = long[long.geo_id == "18003"]
    assert len(a) == 24 and set(a.month.dt.month) == set(range(1, 13))


def test_water_step_series_starts_at_effective_month_and_steps():
    panel = pd.DataFrame({"site_id": ["A"], "county_fips": ["18003"]})
    long = wt.water_long(_water(), panel, end="2025-03-01")
    check_long_format(long)
    v = long.set_index("month").value
    assert v.index.min() == pd.Timestamp("2024-03-01")         # nothing filled before
    assert v[pd.Timestamp("2024-12-01")] == 20.0
    assert v[pd.Timestamp("2025-01-01")] == 25.0               # new rate from its month
    assert v.index.max() == pd.Timestamp("2025-03-01")


def test_check_flags_unit_mixups_and_duplicates():
    t = _tax(); t.loc[0, "rate_per_100"] = 45.0                # mills left undivided
    w = pd.concat([_water(), _water().iloc[:1]])
    problems = wt.check(t, w)
    assert any("outside 0-30" in p for p in problems)
    assert any("duplicate" in p for p in problems)


def test_real_files_are_clean():
    assert wt.check(wt.read_tax(), wt.read_water()) == []


# ---------------------------------------------------------------- tax bill
def _bill_inputs():
    ctrl = pd.DataFrame({
        "site_id": "S", "match_id": "11111", "role": ["treated"] * 3 + ["control"] * 3,
        "zip": ["11111"] * 3 + ["22222"] * 3, "state": "TX", "tax_year": [2023, 2024, 2025] * 2,
        "rate_per_100": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]})
    months = pd.date_range("2023-01-01", "2025-12-01", freq="MS")
    zhvi = pd.concat([pd.DataFrame({"geo_id": z, "geo_type": "zip", "month": months, "variable": "zhvi",
                                    "value": [v0 * g ** (m.year - 2023) for m in months]})
                      for z, v0, g in (("11111", 100_000, 1.10), ("22222", 100_000, 1.00))])
    treated = pd.DataFrame({"geo_id": ["11111"], "treat_month": [pd.Timestamp("2025-03-01")]})
    return ctrl, zhvi, treated


def test_tax_bill_is_rate_times_value_and_dated():
    from src import tax_bill as tb
    p = tb.build(*_bill_inputs())
    r = p[(p.zip == "11111") & (p.tax_year == 2023)].iloc[0]
    assert r.tax_index == 2000.0                       # 2% of $100,000
    assert set(p.event_year) == {-2, -1, 0}


def test_tax_bill_gap_is_log_value_growth_when_rates_equal():
    import numpy as np
    from src import tax_bill as tb
    m = tb.event_means(tb.build(*_bill_inputs())).set_index("event_year")
    assert abs(m.loc[0, "gap"] - 100 * np.log(1.10)) < 1e-9   # host values grew 10%, controls 0%
