"""Phase 1: turn the site panel into treatment tables.

A treatment table has one row per treated place (a ZIP or a county) and the
month treatment began. Every later step joins against these tables, so the
rules for building them live in one place:

* ZIP level uses only ZIPs taken from a facility's published address. A
  town-level ZIP may sit miles from the building, so it stays out of
  ZIP-level housing work (it still counts at the county level).
* Two sites in one place (xAI Colossus 1 and 2 share a ZIP) become one
  treated place, dated by the EARLIER site, because that is when the place
  first changed.
* Each table carries two dates: `treat_month` (AI start, the main design)
  and `announce_month` (for the announcement-effect test).
"""
import pandas as pd

from src import config
from src.io_utils import sample

LEVELS = {"zip": "zip", "county": "county_fips"}


def _broad_treat_month(df: pd.DataFrame) -> pd.Series:
    """Treatment month for the broad sample.

    Strict sites already have an exact AI start month. The other broad sites
    only have a company-wide link to AI, so the best available date is the
    year the facility opened; July of that year is used as the midpoint.
    """
    fallback = pd.to_datetime(df.operational_year.astype("string") + "-07-01",
                              errors="coerce")
    return df.treat_month.fillna(fallback)


def treated_sites(panel: pd.DataFrame, which: str = "strict") -> pd.DataFrame:
    """The sites in a sample, each with its treatment month and its basis."""
    s = sample(panel, which)
    if which == "broad":
        exact = s.treat_month.notna()
        s["treat_month_basis"] = s.treat_month_basis.where(
            exact, "opening year only; July assumed")
        s["treat_month"] = _broad_treat_month(s)
    if s.treat_month.isna().any():
        missing = s.loc[s.treat_month.isna(), "site_id"].tolist()
        raise ValueError(f"Sites with no treatment month: {missing}")
    return s


def build_treated(panel: pd.DataFrame, which: str = "strict",
                  level: str = "zip") -> pd.DataFrame:
    """One row per treated ZIP or county.

    Columns: geo_id, geo_type, state, treat_month, announce_month,
    n_sites, site_ids, site_names, operators.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {list(LEVELS)}")
    s = treated_sites(panel, which)
    if level == "zip":
        s = s[s.zip_basis == "facility address"]

    key = LEVELS[level]
    out = (s.sort_values("treat_month")
             .groupby(key, as_index=False)
             .agg(state=("state", "first"),
                  treat_month=("treat_month", "min"),
                  announce_month=("announce_month", "min"),
                  n_sites=("site_id", "count"),
                  site_ids=("site_id", ", ".join),
                  site_names=("site_name", " | ".join),
                  operators=("operator_parent", lambda x: ", ".join(sorted(set(x))))))
    out = out.rename(columns={key: "geo_id"})
    out.insert(1, "geo_type", level)
    return out.sort_values(["state", "geo_id"]).reset_index(drop=True)


def treatment_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """How many treated places each sample/level combination produces."""
    rows = []
    for which in ("strict", "broad"):
        sites = treated_sites(panel, which)
        for level in LEVELS:
            t = build_treated(panel, which, level)
            rows.append({"sample": which, "level": level, "sites": len(sites),
                         "treated_places": len(t), "states": t.state.nunique(),
                         "first_treatment": t.treat_month.min().strftime("%Y-%m"),
                         "last_treatment": t.treat_month.max().strftime("%Y-%m")})
    return pd.DataFrame(rows)


def save_treated(df: pd.DataFrame, which: str, level: str):
    """Save to data/processed/treated_<level>_<which>.csv."""
    out = config.PROCESSED / f"treated_{level}_{which}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, date_format="%Y-%m-%d")
    return out


def read_treated(which: str = "strict", level: str = "zip") -> pd.DataFrame:
    """Read a saved treatment table with IDs as text and months as dates."""
    return pd.read_csv(config.PROCESSED / f"treated_{level}_{which}.csv",
                       dtype={"geo_id": str}, parse_dates=["treat_month", "announce_month"])
