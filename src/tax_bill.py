"""Estimated property tax bill on the typical home: rate x home value.

A lower tax RATE does not mean a lower BILL when home values are rising, and
rising bills are what residents feel. For every host and comparison town in
data/property_tax_controls.csv:

    tax_index  = rate_per_100 / 100 x ZHVI          (yearly average of the town ZIP's ZHVI)
    approx_bill = tax_index x assessment share       (dollars, rough)

Use `log_tax_index` in the regression. Each state taxes a different share of
market value (ASSESSED_SHARE below), but that share is the same for a host
town and its controls in the same state, so in logs it drops out of the
difference-in-differences. `approx_bill` is only for describing levels:
it ignores homestead exemptions, caps and credits.
"""
import numpy as np
import pandas as pd

from src import config

CONTROLS_FILE = config.DATA / "property_tax_controls.csv"

# Share of market value that is taxed, residential (statutory, rounded).
ASSESSED_SHARE = {
    "IN": 1.00,    # gross assessed value; homestead deductions not applied
    "IA": 0.47,    # residential rollback, recent years (changes yearly)
    "TN": 0.25,
    "TX": 1.00,    # before the homestead exemption
    "OK": 0.11,    # county assessment ratios run 11-13.5%
    "ND": 0.045,   # 50% of value x 9%
    "OR": 0.60,    # assessed value is capped well below market; rough statewide ratio
}


def read_controls(path=CONTROLS_FILE) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"zip": str, "match_id": str})


def yearly_zhvi(zhvi_long: pd.DataFrame, zips) -> pd.DataFrame:
    """Calendar-year average home value per ZIP (needs at least 6 months)."""
    z = zhvi_long[(zhvi_long.geo_type == "zip") & zhvi_long.geo_id.isin(set(zips))]
    z = z.assign(tax_year=z.month.dt.year)
    g = z.groupby(["geo_id", "tax_year"]).value.agg(["mean", "count"]).reset_index()
    g = g[g["count"] >= 6]
    return g.rename(columns={"geo_id": "zip", "mean": "zhvi"})[["zip", "tax_year", "zhvi"]]


def build(controls: pd.DataFrame, zhvi_long: pd.DataFrame, treated: pd.DataFrame) -> pd.DataFrame:
    """One row per site, town and tax year, with event years relative to AI.

    treated: treated_zip_strict (geo_id, treat_month) to date each site.
    """
    v = yearly_zhvi(zhvi_long, controls.zip.unique())
    p = controls.merge(v, on=["zip", "tax_year"], how="inner")
    p["tax_index"] = p.rate_per_100 / 100 * p.zhvi
    p["log_tax_index"] = np.log(p.tax_index)
    p["approx_bill"] = (p.tax_index * p.state.map(ASSESSED_SHARE)).round(0)
    tm = treated.set_index("geo_id").treat_month
    p["treat_year"] = pd.to_datetime(p.match_id.map(tm)).dt.year
    p["event_year"] = p.tax_year - p.treat_year
    p["treated"] = (p.role == "treated").astype(int)
    p["post"] = (p.event_year >= 0).astype(int)
    return p


def event_means(p: pd.DataFrame, col: str = "log_tax_index") -> pd.DataFrame:
    """Treated vs control change since the year before AI, averaged over sites.

    Each site's controls are averaged first, so every site counts once.
    Change is in log points x 100 (about % change).
    """
    base = p[p.event_year == -1].set_index(["site_id", "zip"])[col]
    q = p.join(base.rename("base"), on=["site_id", "zip"]).dropna(subset=["base"])
    q["chg"] = 100 * (q[col] - q.base)
    site = q.groupby(["site_id", "event_year", "treated"]).chg.mean().unstack("treated")
    site.columns = ["control", "treated"]
    out = site.groupby("event_year").agg(control=("control", "mean"), treated=("treated", "mean"),
                                         sites=("treated", "count")).reset_index()
    out["gap"] = out.treated - out.control
    return out
