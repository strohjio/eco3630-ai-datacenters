"""CFPB Mortgage Performance Trends -> the shared long format.

Source: https://www.consumerfinance.gov/data-research/mortgage-performance-trends/
Download the two county files ("Download the data" -> County) into data/raw/cfpb/:

    CountyMortgagesPercent-90-plusDaysLate-thru-<YYYY-MM>.csv
    CountyMortgagesPercent-30-89DaysLate-thru-<YYYY-MM>.csv

Each value is the percent of a county's mortgages that are 90+ (or 30-89)
days late in that month. The CFPB only publishes counties with enough
mortgages in its sample (about 500), so smaller rural host counties are
missing. That limits the delinquency test; see coverage().
"""
from pathlib import Path

import pandas as pd

from src import config
from src.io_utils import clean_fips

CFPB_DIR = config.RAW / "cfpb"
FILES = {"delinq_90": "CountyMortgagesPercent-90-plusDaysLate-thru-*.csv",
         "delinq_30_89": "CountyMortgagesPercent-30-89DaysLate-thru-*.csv"}


def find_file(variable: str, raw_dir: Path = CFPB_DIR) -> Path:
    """Newest file for a variable (the name ends with the last month covered)."""
    files = sorted(raw_dir.glob(FILES[variable]))
    if not files:
        raise FileNotFoundError(
            f"No {FILES[variable]} in {raw_dir}. Download the county file from "
            "https://www.consumerfinance.gov/data-research/mortgage-performance-trends/")
    return files[-1]


def read_county(path: Path, variable: str) -> pd.DataFrame:
    """One CFPB county file (wide, one column per month) -> long format.

    The national row is dropped. FIPS codes arrive wrapped in quotes
    ('01003') to protect the leading zero; those are stripped.
    """
    wide = pd.read_csv(path, dtype=str)
    wide = wide[wide.RegionType == "County"].copy()
    wide["geo_id"] = clean_fips(wide.FIPSCode.str.strip("'\" "))
    months = [c for c in wide.columns if c[:4].isdigit()]
    long = wide.melt(id_vars="geo_id", value_vars=months, var_name="month", value_name="value")
    long["value"] = pd.to_numeric(long.value, errors="coerce")
    long["month"] = pd.to_datetime(long.month, format="%Y-%m")
    long = long.dropna(subset=["value"])
    long.insert(1, "geo_type", "county")
    long.insert(3, "variable", variable)
    return long.reset_index(drop=True)


def load() -> pd.DataFrame:
    """Both delinquency measures, stacked, in the shared long format."""
    return pd.concat([read_county(find_file(v), v) for v in FILES], ignore_index=True)


def coverage(long: pd.DataFrame, treated: pd.DataFrame) -> pd.DataFrame:
    """For each treated county: is it covered, and how many months after AI?

    treated: geo_id, treat_month (from build_treated, level 'county').
    """
    d = long[long.variable == "delinq_90"]
    last = d.month.max()
    have = d.groupby("geo_id").month.agg(["min", "max"]).rename(
        columns={"min": "first_month", "max": "last_month"})
    out = treated[["geo_id", "state", "treat_month"]].merge(
        have, left_on="geo_id", right_index=True, how="left")
    out["covered"] = out.first_month.notna()
    months_after = ((last.year - out.treat_month.dt.year) * 12
                    + (last.month - out.treat_month.dt.month))
    out["months_after_ai"] = months_after.where(out.covered).clip(lower=-1)
    return out
