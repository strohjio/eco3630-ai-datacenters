"""Step 2 of the delinquency question: do rising costs go with more late mortgages?

The difference-in-differences asks whether AI raised costs. This step asks
the second half of the chain, across every county the CFPB publishes in the
project's states (not just hosts):

    late_90[c,t] = gamma * cost_index[c, t-lag] + unemployment + county FE
                   + state-by-month FE + error

cost_index = average of two standardized cost changes, each a 12-month %
change (capped at the 1st and 99th percentiles, because small utilities'
monthly prices swing wildly): the county's typical home value (median of its ZIPs' Zillow values)
and its residential electricity price (EIA, customer-weighted). Standardized
means "in standard deviations", so gamma reads as: a county whose costs grew
1 SD faster than usual had gamma percentage points more mortgages 90+ days
late `lag` months later.

This is an association, not a causal effect: costs and late payments can
share causes the controls miss. Multiplying gamma by how much AI moved costs
gives a rough "how much of a delinquency effect could come through costs"
number, which is how the report should use it.
"""
import numpy as np
import pandas as pd

from src import regress as rg
from src.geo import load_zip_centroids
from src.io_utils import read_long


def county_home_values() -> pd.DataFrame:
    """County x month median Zillow home value (median of the county's ZIPs)."""
    z = read_long("zhvi")
    z = z[(z.geo_type == "zip") & (z.variable == "zhvi")]
    cent = load_zip_centroids()[["zip", "county_fips"]].drop_duplicates("zip")
    z = z.merge(cent, left_on="geo_id", right_on="zip")
    return z.groupby(["county_fips", "month"], as_index=False).value.median().rename(
        columns={"value": "home_value"})


def build_panel(states: set[str], lag: int = 12) -> pd.DataFrame:
    """County x month panel of delinquency, cost index and unemployment."""
    d = read_long("delinq")
    d = d[d.variable == "delinq_90"].rename(columns={"geo_id": "county_fips", "value": "late_90"})
    d = d[d.county_fips.str[:2].isin(states)][["county_fips", "month", "late_90"]]
    hv = county_home_values()
    el = read_long("elec_county").rename(columns={"geo_id": "county_fips", "value": "elec_price"})
    el = el[["county_fips", "month", "elec_price"]]
    p = d.merge(hv, on=["county_fips", "month"], how="left").merge(el, on=["county_fips", "month"], how="left")
    p = p.sort_values(["county_fips", "month"])
    for col in ("home_value", "elec_price"):
        g = p.groupby("county_fips")[col]
        p[f"{col}_g12"] = 100 * g.pct_change(12, fill_method=None)
        lo, hi = p[f"{col}_g12"].quantile([0.01, 0.99])          # small utilities' price
        p[f"{col}_g12"] = p[f"{col}_g12"].clip(lo, hi)            # swings: cap at 1st/99th pct
        p[f"z_{col}"] = (p[f"{col}_g12"] - p[f"{col}_g12"].mean()) / p[f"{col}_g12"].std()
    p["cost_index"] = p[["z_home_value", "z_elec_price"]].mean(axis=1, skipna=False)
    for col in ("cost_index", "z_home_value", "z_elec_price"):
        p[f"{col}_lag"] = p.groupby("county_fips")[col].shift(lag)
    un = read_long("controls_county")
    un = un[un.variable == "unemp_rate"].assign(year=lambda x: x.month.dt.year)
    un = un.rename(columns={"geo_id": "county_fips", "value": "unemp_rate"})[["county_fips", "year", "unemp_rate"]]
    p = p.assign(year=p.month.dt.year).merge(un, on=["county_fips", "year"], how="left")
    p["state_month"] = p.county_fips.str[:2] + "_" + p.month.dt.strftime("%Y-%m")
    # names the shared estimator expects
    p["geo_id"], p["match_id"], p["treated"] = p.county_fips, p.county_fips, 0
    return p


def cost_regressions(p: pd.DataFrame) -> pd.DataFrame:
    """gamma for the combined index and for each cost alone, clustered by county."""
    rows = []
    for x, label in (("cost_index_lag", "cost index (home values + electricity)"),
                     ("z_home_value_lag", "home value growth only"),
                     ("z_elec_price_lag", "electricity price growth only")):
        q = p.dropna(subset=[x, "late_90", "unemp_rate"])
        r = rg.did(q.assign(treat_post=q[x]), "late_90", ["geo_id", "state_month"],
                   cluster="geo_id", controls=["unemp_rate"], outcome="Mortgages 90+ days late (pct. points)",
                   spec=f"per 1 SD faster {label}, 12 months earlier")
        rows.append(r.row() | {"n_counties": q.county_fips.nunique(),
                               "months": f"{q.month.min():%Y-%m} to {q.month.max():%Y-%m}"})
    out = pd.DataFrame(rows).drop(columns=["n_hosts", "perm_p"])
    return out


def implied_effect(gamma: float, ai_cost_effect_pct: float, sd_pct: float) -> float:
    """Rough delinquency change that could run through costs.

    ai_cost_effect_pct: how much faster costs grew in hosts (%, from the DiD);
    sd_pct: one standard deviation of 12-month cost growth (%).
    """
    return gamma * ai_cost_effect_pct / sd_pct if sd_pct else np.nan
