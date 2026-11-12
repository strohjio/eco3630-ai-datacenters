"""Hand-collected property tax rates and water bills -> the shared long format.

Two files in data/ hold every collected value with its source link:

  property_tax_rates.csv   one row per place, tax year and levy component
  water_bills.csv          one row per place and rate change (effective date)

How the values were built is documented row by row (unit_note, rate_note,
date_basis). The rules that matter for the analysis:

* Property tax: `rate_per_100` is the tax per $100 of the value the state
  taxes. States tax different shares of market value (Georgia 40%, Ohio 35%,
  Arizona 10%...), so compare each place with ITSELF over time, never levels
  across states. One row per place and year is marked `primary`; it is the
  series used in the analysis. When a place has two primary rows in a year
  (Fort Wayne: the site's school district is not confirmed), they are averaged.
* Water: `monthly_bill` is a residential bill at `usage_gal` gallons a month,
  computed from the official rate schedule. Rows with `derived=True` were
  backed out from a later bill and the published percentage increases.
  Abilene's rows combine water and sewer (`water_only=False`).
"""
import pandas as pd

from src import config
from src.io_utils import LONG_COLUMNS, clean_fips

TAX_FILE = config.DATA / "property_tax_rates.csv"
WATER_FILE = config.DATA / "water_bills.csv"


def read_tax(path=TAX_FILE) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"county_fips": str, "site_id": str})
    df["county_fips"] = clean_fips(df.county_fips)
    df["primary"] = df["primary"].astype(str).str.lower().eq("true")
    return df


def read_water(path=WATER_FILE) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"site_id": str}, parse_dates=["effective_date"])
    for col in ("derived", "water_only"):
        df[col] = df[col].astype(str).str.lower().eq("true")
    return df


def check(tax: pd.DataFrame, water: pd.DataFrame) -> list[str]:
    """Problems that would quietly break the analysis. Empty list = clean."""
    problems = []
    for name, df, cols in (("tax", tax, ["site_id", "rate_per_100", "source_url"]),
                           ("water", water, ["site_id", "monthly_bill", "source_url"])):
        for c in cols:
            if df[c].isna().any():
                problems.append(f"{name}: {df[c].isna().sum()} rows missing {c}")
    # ND taxes only 4.5% of a home's value, so ~23 per $100 of taxable value is real
    bad = tax[(tax.rate_per_100 <= 0) | (tax.rate_per_100 > 30)]
    if len(bad):
        problems.append(f"tax: {len(bad)} rates outside 0-30 per $100 (unit mix-up?)")
    if (water.monthly_bill <= 0).any() or (water.monthly_bill > 300).any():
        problems.append("water: bill outside $0-300 a month")
    dup = water.duplicated(["site_id", "effective_date"])
    if dup.any():
        problems.append(f"water: {dup.sum()} duplicate site/date rows")
    return problems


def tax_series(tax: pd.DataFrame) -> pd.DataFrame:
    """Primary rate per site and tax year (two primary districts are averaged)."""
    p = tax[tax.primary]
    return (p.groupby(["site_id", "place", "state", "county_fips", "tax_year"], as_index=False)
              .rate_per_100.mean())


def _months(start, end):
    return pd.date_range(start, end, freq="MS")


def tax_long(tax: pd.DataFrame) -> pd.DataFrame:
    """Shared long format, county level: each tax year's rate on all 12 months.

    Sites that share a county (the two Memphis sites, the two New Albany sites)
    carry the same series, so the county keeps one copy.
    """
    s = tax_series(tax).drop_duplicates(["county_fips", "tax_year"])
    rows = [pd.DataFrame({"geo_id": r.county_fips, "month": _months(f"{r.tax_year}-01-01",
                                                                     f"{r.tax_year}-12-01"),
                          "value": r.rate_per_100})
            for r in s.itertuples()]
    out = pd.concat(rows, ignore_index=True)
    out["geo_type"], out["variable"] = "county", "proptax_rate_per100"
    return out[LONG_COLUMNS]


def water_long(water: pd.DataFrame, panel: pd.DataFrame, end="2026-10-01",
               water_only: bool = True) -> pd.DataFrame:
    """Shared long format, county level: a step series of the monthly bill.

    Each bill holds from its effective month until the next change; the last
    one is carried to `end`. Nothing is filled before the first known bill.
    panel: the site panel (for each site's county).
    """
    w = water[water.water_only] if water_only else water
    fips = panel.set_index("site_id").county_fips
    rows = []
    for site, g in w.sort_values("effective_date").groupby("site_id"):
        starts = g.effective_date.dt.to_period("M").dt.to_timestamp().tolist()
        stops = [s - pd.offsets.MonthBegin(1) for s in starts[1:]] + [pd.Timestamp(end)]
        for a, b, v in zip(starts, stops, g.monthly_bill):
            if b >= a:
                rows.append(pd.DataFrame({"geo_id": fips[site], "month": _months(a, b), "value": v}))
    out = pd.concat(rows, ignore_index=True).drop_duplicates(["geo_id", "month"])
    out["geo_type"], out["variable"] = "county", "water_bill_5k" if water_only else "water_sewer_bill"
    return out[LONG_COLUMNS]


def coverage(tax: pd.DataFrame, water: pd.DataFrame, treated: pd.DataFrame) -> pd.DataFrame:
    """Per strict site: years of tax data and water bills before/after AI."""
    ts = tax_series(tax)
    out = treated[["site_id", "site_name", "state", "treat_month"]].copy()
    ty = ts.groupby("site_id").tax_year.agg(["min", "max"])
    out["tax_years"] = out.site_id.map(lambda s: f"{ty.loc[s,'min']}-{ty.loc[s,'max']}" if s in ty.index else "none")
    out["tax_years_after_ai"] = out.apply(
        lambda r: int((ts[(ts.site_id == r.site_id)].tax_year >= r.treat_month.year).sum()), axis=1)
    w = water[water.water_only]
    out["water_changes"] = out.site_id.map(w.groupby("site_id").size()).fillna(0).astype(int)
    out["water_first"] = out.site_id.map(w.groupby("site_id").effective_date.min().dt.strftime("%Y-%m"))
    out["water_last"] = out.site_id.map(w.groupby("site_id").effective_date.max().dt.strftime("%Y-%m"))
    return out
