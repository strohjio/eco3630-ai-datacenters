"""Tests for the shared helpers. Run all tests with:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import io_utils  # noqa: E402


def test_clean_zip_restores_leading_zeros():
    s = pd.Series(["501", "2116", "20147", "none", "not yet verified"])
    assert io_utils.clean_zip(s).tolist() == ["00501", "02116", "20147", "none", "not yet verified"]


def test_clean_fips_restores_leading_zeros():
    assert io_utils.clean_fips(pd.Series(["1001", "51107"])).tolist() == ["01001", "51107"]


def test_to_month_start():
    out = io_utils.to_month_start(pd.Series(["2025-03-17", "2025-12", None]))
    assert out.iloc[0] == pd.Timestamp("2025-03-01")
    assert out.iloc[1] == pd.Timestamp("2025-12-01")
    assert pd.isna(out.iloc[2])


def _long():
    return pd.DataFrame({
        "geo_id": ["20147", "20147"], "geo_type": ["zip", "zip"],
        "month": pd.to_datetime(["2025-01-01", "2025-02-01"]),
        "variable": ["zhvi", "zhvi"], "value": [650000.0, 652000.0],
    })


def test_long_format_accepts_good_table():
    io_utils.check_long_format(_long())


@pytest.mark.parametrize("breakit, msg", [
    (lambda d: d.drop(columns="variable"), "Missing columns"),
    (lambda d: d.assign(geo_type="town"), "geo_type"),
    (lambda d: d.assign(month=pd.to_datetime(["2025-01-15", "2025-02-01"])), "first-of-month"),
    (lambda d: pd.concat([d, d]), "duplicate"),
])
def test_long_format_rejects_bad_tables(breakit, msg):
    with pytest.raises(ValueError, match=msg):
        io_utils.check_long_format(breakit(_long()))


def test_save_and_read_long_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(io_utils.config, "PROCESSED", tmp_path)
    df = _long().assign(geo_id=["00501", "00501"])
    io_utils.save_long(df, "test_table")
    back = io_utils.read_long("test_table")
    assert back.geo_id.tolist() == ["00501", "00501"]  # leading zero survives
    assert back.month.tolist() == df.month.tolist()


def test_load_site_panel_types():
    p = io_utils.load_site_panel()
    assert p.zip.map(type).eq(str).all()
    assert p.county_fips.str.fullmatch(r"\d{5}").all()
    assert p.sample_strict_ai.dtype == bool
    assert str(p.operational_year.dtype) == "Int64"
    strict = io_utils.sample(p, "strict")
    assert strict.treat_month.notna().all()
    assert (strict.treat_month.dt.day == 1).all()
