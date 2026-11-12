"""Tests for the EIA and CFPB steps. Run with:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import cfpb, eia  # noqa: E402
from src.io_utils import check_long_format  # noqa: E402


# ---------------------------------------------------------------- EIA files
def _sector_values(rev, sales, cust, price=None):
    """One sector's numbers, in EIA's column order."""
    return [rev, sales, cust] + ([price] if price is not None else [])


def _write_xlsx(path, rows, sheet):
    """EIA layout: three header rows, then data. Header text is not read."""
    header = [["x"] * len(rows[0])] * 3
    pd.DataFrame(header + rows).to_excel(path, sheet_name=sheet, header=False, index=False)


def test_state_reader_recomputes_price_and_drops_footnotes(tmp_path):
    row = [2025, 3, "OH", "Final"]
    for _ in eia.SECTORS:
        row += _sector_values(1000.0, 8000.0, 50, 99.0)   # EIA price column ignored
    footnote = ["Customer counts started in 2007."] + [None] * (len(row) - 1)
    _write_xlsx(tmp_path / "sales_revenue.xlsx", [row, footnote], "Monthly-States")
    df = eia.read_state_monthly(tmp_path / "sales_revenue.xlsx")
    assert len(df) == 1
    assert df.residential_price.iloc[0] == pytest.approx(12.5)   # 1000*100/8000
    assert df.month.iloc[0] == pd.Timestamp("2025-03-01")
    long = eia.state_long(df)
    check_long_format(long)
    assert set(long.geo_id) == {"OH"}


def test_utility_reader_drops_non_utilities_and_dots(tmp_path):
    def row(uid, name, owner, rev):
        r = [2024, 6, uid, name, "IN", owner, "Final"]
        for _ in eia.SECTORS:
            r += _sector_values(rev, 1000.0, 10)
        return r
    rows = [row(0, "State Adjustment 2024", None, 5.0),
            row(88888, "Behind the Meter", "Behind the Meter", 5.0),
            row(9324, "Indiana Michigan Power Co", "Investor Owned", 150.0),
            row(13756, "Northern Indiana Pub Serv Co", "Investor Owned", ".")]
    _write_xlsx(tmp_path / "sales_ult_cust_2024.xlsx", rows, "States")
    u = eia.read_utility_monthly([tmp_path / "sales_ult_cust_2024.xlsx"])
    assert set(u.utility_key) == {"9324_IN", "13756_IN"}
    assert u.set_index("utility_key").residential_price["9324_IN"] == pytest.approx(15.0)
    assert u.set_index("utility_key").residential_price.isna()["13756_IN"]   # '.' -> blank
    check_long_format(eia.utility_long(u))


def test_missing_file_message_points_to_eia(tmp_path):
    with pytest.raises(FileNotFoundError, match="eia.gov"):
        eia.read_state_monthly(tmp_path / "nope.xlsx")


# ---------------------------------------------------------------- utility design
def _util():
    m = pd.Timestamp("2025-01-01")
    return pd.DataFrame({
        "utility_key": ["A_OH", "B_OH", "C_OH", "D_IN"], "state": ["OH", "OH", "OH", "IN"],
        "month": m, "residential_price": [10.0, 20.0, 30.0, 12.0],
        "residential_customers": [3000, 1000, 50, 5000]})


def test_county_price_is_customer_weighted():
    terr = pd.DataFrame({"utility_key": ["A_OH", "B_OH"], "county_fips": ["39089", "39089"]})
    out = eia.county_prices(_util(), terr)
    assert out.value.iloc[0] == pytest.approx((10 * 3000 + 20 * 1000) / 4000)
    assert out.variable.iloc[0] == "elec_price_res_cty"
    check_long_format(out)


def test_shared_host_utility_counts_once_from_earlier_month():
    choice = pd.DataFrame({"county_fips": ["39045", "39089"], "state": ["OH", "OH"],
                           "utility_key": ["A_OH", "A_OH"], "utility_name": ["Ohio Power"] * 2})
    treated = pd.DataFrame({"geo_id": ["39045", "39089"],
                            "treat_month": pd.to_datetime(["2024-01-01", "2025-09-01"])})
    tu = eia.treated_utilities(choice, treated)
    assert len(tu) == 1 and tu.treat_month.iloc[0] == pd.Timestamp("2024-01-01")


def test_controls_same_state_skip_hosts_and_tiny_utilities():
    tu = pd.DataFrame({"geo_id": ["A_OH"], "state": ["OH"]})
    ctrl = eia.utility_controls(_util(), tu)
    assert list(ctrl.geo_id) == ["B_OH"]      # C_OH too small, D_IN other state
    assert (ctrl.match_id == "A_OH").all()


# ---------------------------------------------------------------- CFPB
def test_cfpb_reader_strips_quotes_and_drops_national(tmp_path):
    p = tmp_path / "CountyMortgagesPercent-90-plusDaysLate-thru-2026-03.csv"
    p.write_text("RegionType,State,Name,FIPSCode,2026-02,2026-03\n"
                 "National,,United States,-----,0.5,0.6\n"
                 "County,AL,Baldwin County,'01003',0.4,NA\n")
    long = cfpb.read_county(p, "delinq_90")
    check_long_format(long)
    assert list(long.geo_id) == ["01003"]          # leading zero kept, NA dropped
    assert long.value.iloc[0] == 0.4
    assert cfpb.find_file("delinq_90", tmp_path) == p


def test_cfpb_coverage_counts_months_after_ai():
    long = pd.DataFrame({"geo_id": "01003", "geo_type": "county", "variable": "delinq_90",
                         "month": pd.date_range("2025-01-01", "2026-03-01", freq="MS"), "value": 1.0})
    treated = pd.DataFrame({"geo_id": ["01003", "99999"], "state": ["AL", "AL"],
                            "treat_month": pd.to_datetime(["2025-12-01", "2025-12-01"])})
    cov = cfpb.coverage(long, treated).set_index("geo_id")
    assert cov.loc["01003", "months_after_ai"] == 3
    assert not cov.loc["99999", "covered"]
