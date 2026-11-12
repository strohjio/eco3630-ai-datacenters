"""Phase 3: Zillow home values (ZHVI) and rents (ZORI) in the shared format.

Zillow publishes one wide CSV per measure: a row per ZIP, a column per
month. This module turns it into the project's long format
(geo_id, geo_type, month, variable, value).

It accepts the file in any of the forms a teammate might have in data/raw/:
  * the full download        Zip_zhvi_uc_sfrcondo_..._month.csv
  * the shrunk version       ..._month_study.csv    (scripts/shrink_zillow.py)
  * split pieces             ..._month_study_part1.csv ... (scripts/split_csv.py)
The full download is preferred because it goes back to 2000; the shrunk
version starts in 2015, which covers the strict sample but not the oldest
broad-sample sites.

Values are nominal dollars. Inflation-adjusted columns are added when the
analysis panels are built (Phase 4).
"""
from pathlib import Path

import pandas as pd

from src import config
from src.io_utils import to_month_start

FILE_PREFIX = {"zhvi": "Zip_zhvi_uc_sfrcondo", "zori": "Zip_zori_uc_sfrcondomfr"}
ID_COLUMNS = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
              "State", "City", "Metro", "CountyName"]


def find_raw_files(variable: str, raw_dir: Path = config.RAW) -> list[Path]:
    """The best available raw file(s) for 'zhvi' or 'zori'.

    Order of preference: full download, then the shrunk file, then its
    split pieces. Raises a clear error if none is present.
    """
    prefix = FILE_PREFIX[variable]
    files = sorted(raw_dir.glob(f"{prefix}*.csv"))
    full = [f for f in files if not f.stem.endswith("_study") and "_part" not in f.stem]
    study = [f for f in files if f.stem.endswith("_study")]
    parts = [f for f in files if "_part" in f.stem]
    for found in (full, study, parts):
        if found:
            return found if found is parts else found[:1]
    raise FileNotFoundError(
        f"No Zillow {variable.upper()} file in {raw_dir}. Download the ZIP-level "
        f"file from https://www.zillow.com/research/data/ and save it there.")


def read_wide(paths: list[Path]) -> pd.DataFrame:
    """Read one or more wide Zillow files into one table, ZIPs as 5-digit text."""
    df = pd.concat((pd.read_csv(p, dtype={"RegionName": str}) for p in paths),
                   ignore_index=True)
    df["RegionName"] = df.RegionName.str.zfill(5)
    if df.RegionName.duplicated().any():
        raise ValueError("The same ZIP appears twice; were the pieces mixed up?")
    return df


def to_long(wide: pd.DataFrame, variable: str, start: str | None = None) -> pd.DataFrame:
    """Wide Zillow table -> shared long format, no blanks.

    Keeps every month by default: matching needs the years before each
    site's treatment, which for the oldest sites reach back to 2003.
    """
    months = [c for c in wide.columns if c not in ID_COLUMNS]
    long = wide.melt(id_vars="RegionName", value_vars=months,
                     var_name="month", value_name="value")
    long["month"] = to_month_start(long.month)   # Zillow dates months by their last day
    long = long[long.value.notna()]
    if start is not None:
        long = long[long.month >= start]
    return pd.DataFrame({"geo_id": long.RegionName, "geo_type": "zip",
                         "month": long.month, "variable": variable,
                         "value": long.value.astype(float)}).reset_index(drop=True)


def load(variable: str, start: str | None = None) -> pd.DataFrame:
    """Find, read and reshape one Zillow measure."""
    return to_long(read_wide(find_raw_files(variable)), variable, start)


def coverage(long: pd.DataFrame, geo_ids) -> pd.DataFrame:
    """For each requested ZIP: first and last month with data, and month count."""
    sub = long[long.geo_id.isin(set(geo_ids))]
    out = (sub.groupby("geo_id").month.agg(["min", "max", "count"])
              .rename(columns={"min": "first_month", "max": "last_month",
                               "count": "n_months"}))
    return out.reindex(sorted(set(geo_ids))).reset_index()
