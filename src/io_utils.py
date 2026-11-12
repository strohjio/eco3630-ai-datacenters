"""Shared helpers for reading and writing data the same way everywhere.

The four team rules live here as code:
  1. IDs are text (ZIPs and FIPS codes keep their leading zeros).
  2. Dates are month starts (2025-03-01).
  3. Every processed dataset uses one long format (LONG_COLUMNS).
  4. Dollar values get an inflation-adjusted column (added in later phases).
"""
from pathlib import Path

import pandas as pd

from src import config

# Columns that must always be read as text. Pass to every pd.read_csv call.
ID_DTYPES = {
    "site_id": str, "zip": str, "county_fips": str,
    "geo_id": str, "match_id": str, "state": str,
}

# The shared output shape for every processed dataset.
LONG_COLUMNS = ["geo_id", "geo_type", "month", "variable", "value"]
GEO_TYPES = {"zip", "county", "state", "utility", "nation"}   # utility: "<EIA id>_<state>"

YEAR_COLUMNS = ["announce_year", "operational_year", "anchor_year", "ai_era_start_year"]
MONTH_COLUMNS = ["treat_month", "announce_month"]
BOOL_COLUMNS = ["sample_strict_ai", "sample_broad_ai"]


# ---------------------------------------------------------------- ID cleaning
def clean_zip(s: pd.Series) -> pd.Series:
    """Return 5-digit ZIP strings. 501 -> '00501'. Non-numeric values pass through."""
    s = s.astype("string").str.strip()
    digits = s.str.fullmatch(r"\d{1,5}")
    return s.where(~digits.fillna(False), s.str.zfill(5))


def clean_fips(s: pd.Series) -> pd.Series:
    """Return 5-digit county FIPS strings. 1001 -> '01001'."""
    s = s.astype("string").str.strip()
    digits = s.str.fullmatch(r"\d{1,5}")
    return s.where(~digits.fillna(False), s.str.zfill(5))


# ---------------------------------------------------------------- dates
def to_month_start(s: pd.Series) -> pd.Series:
    """Convert dates or 'YYYY-MM' strings to the first day of their month.

    format="mixed" lets one column hold both '2025-03-17' and '2025-12';
    without it pandas guesses one format and silently blanks the other.
    """
    dates = pd.to_datetime(s, errors="coerce", format="mixed")
    return dates.dt.to_period("M").dt.to_timestamp()


# ---------------------------------------------------------------- site panel
def load_site_panel(path=None, validate: bool = True) -> pd.DataFrame:
    """Read the site panel with correct types.

    IDs stay text, years become nullable integers, months become month-start
    dates, and the sample flags become True/False. With validate=True the
    panel is checked first and any problem stops the code with a clear list.
    """
    path = path or config.SITE_PANEL
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    if validate:
        from src.validate import validate_site_panel
        validate_site_panel(df, raise_on_error=True)

    for c in YEAR_COLUMNS:
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce").astype("Int64")
    for c in MONTH_COLUMNS:
        df[c] = to_month_start(df[c].replace("", None))
    for c in BOOL_COLUMNS:
        df[c] = df[c].eq("True")
    for c in ("zip_lat", "zip_lon", "scale_mw"):
        df[c] = pd.to_numeric(df[c].replace("", None), errors="coerce")
    return df


def sample(df: pd.DataFrame, which: str = "strict") -> pd.DataFrame:
    """Return the strict or broad AI sample as a copy."""
    col = {"strict": "sample_strict_ai", "broad": "sample_broad_ai"}[which]
    return df[df[col]].copy()


# ---------------------------------------------------------------- long format
def check_long_format(df: pd.DataFrame) -> None:
    """Raise a clear error if a table isn't in the shared long format."""
    missing = [c for c in LONG_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns {missing}. Expected {LONG_COLUMNS}.")
    bad_geo = set(df.geo_type.unique()) - GEO_TYPES
    if bad_geo:
        raise ValueError(f"geo_type must be one of {GEO_TYPES}, found {bad_geo}.")
    if not pd.api.types.is_datetime64_any_dtype(df.month):
        raise ValueError("month must be a datetime column (use to_month_start).")
    if (df.month.dt.day != 1).any():
        raise ValueError("month must hold first-of-month dates (use to_month_start).")
    if not pd.api.types.is_numeric_dtype(df.value):
        raise ValueError("value must be numeric.")
    dups = df.duplicated(["geo_id", "geo_type", "month", "variable"]).sum()
    if dups:
        raise ValueError(f"{dups} duplicate geo/month/variable rows.")


# The biggest tables are saved compressed (.csv.gz) so they fit on GitHub.
# pandas reads and writes .csv.gz exactly like .csv.
COMPRESSED_TABLES = {"zhvi", "zori", "elec_utility", "elec_county"}


def processed_file(name: str) -> Path:
    """Path of a processed table: data/processed/<name>.csv (or .csv.gz for big ones)."""
    ext = ".csv.gz" if name in COMPRESSED_TABLES else ".csv"
    return config.PROCESSED / f"{name}{ext}"


def save_long(df: pd.DataFrame, name: str) -> Path:
    """Check a long-format table, then save it to data/processed/ (see processed_file)."""
    df = df[LONG_COLUMNS].copy()
    check_long_format(df)
    df = df.sort_values(["geo_type", "geo_id", "variable", "month"])
    out = processed_file(name)
    out.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps a re-run byte-identical, so git doesn't see a change
    comp = {"method": "gzip", "mtime": 0} if out.suffix == ".gz" else None
    # 10 significant digits: plenty for prices and rates, and the file comes
    # out the same with every pandas version (full precision differs in the
    # last digit between pandas 2 and 3)
    df.to_csv(out, index=False, date_format="%Y-%m-%d", compression=comp, float_format="%.10g")
    return out


def read_long(name: str) -> pd.DataFrame:
    """Read a processed long-format table with correct types."""
    path = processed_file(name)
    if not path.exists():
        raise FileNotFoundError(f"{path.name} not found in data/processed/. Run the script "
                                f"that builds it (see the pipeline table in README.md).")
    df = pd.read_csv(path, dtype={"geo_id": str},
                     parse_dates=["month"])
    check_long_format(df)
    return df
