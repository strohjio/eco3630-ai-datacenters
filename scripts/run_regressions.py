"""Phase 4: the regressions. Run after every pull/build script.

    python scripts/run_regressions.py            # all outcomes, 300 placebo draws
    python scripts/run_regressions.py --quick    # 50 placebo draws

Writes:
  data/processed/results_did.csv        every difference-in-differences estimate
  data/processed/results_event_*.csv    event-study estimates by period
  figures/es_*.png                      event-study charts with 95% intervals

Outcomes are in percent (100 x log) except mortgage delinquency, which is in
percentage points. Read `coef` as "how much more the AI host changed than its
matched comparison places after AI arrived".
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config, eia, mediation as md, regress as rg  # noqa: E402
from src.figures_results import event_study_plot  # noqa: E402
from src.io_utils import load_site_panel, read_long, sample  # noqa: E402
from src.panel import build_panel  # noqa: E402
from src.plotting import save  # noqa: E402
from src.treatment import read_treated  # noqa: E402

P = config.PROCESSED


# ---------------------------------------------------------------- helpers
def county_controls() -> pd.DataFrame:
    """County x year: unemployment rate and log median income (for 'with controls')."""
    c = read_long("controls_county")
    w = (c[c.variable.isin(["unemp_rate", "med_hh_income"])]
         .assign(year=lambda d: d.month.dt.year)
         .pivot_table(index=["geo_id", "year"], columns="variable", values="value").reset_index())
    w["log_income"] = np.log(w.med_hh_income)
    return w.rename(columns={"geo_id": "county_fips"})[["county_fips", "year", "unemp_rate", "log_income"]]


def add_controls(panel: pd.DataFrame, county_of: dict) -> pd.DataFrame:
    """Merge county-year controls; income only through 2024, so carry 2024 to later years."""
    cc = county_controls()
    p = panel.assign(county_fips=panel.geo_id.map(county_of), year=panel.month.dt.year)
    last = cc.dropna(subset=["log_income"]).year.max()
    p["cyear"] = p.year.clip(upper=last)
    inc = cc[["county_fips", "year", "log_income"]].rename(columns={"year": "cyear"})
    un = cc[["county_fips", "year", "unemp_rate"]]
    return p.merge(inc, on=["county_fips", "cyear"], how="left").merge(un, on=["county_fips", "year"], how="left")


def finish(panel: pd.DataFrame, scale: float = 100.0) -> pd.DataFrame:
    p = panel.copy()
    p["y"] = scale * p.log_value if scale else p.value
    p["treat_post"] = p.treated * p.post
    p["mt"] = p.match_id.astype(str) + "_" + p.month.dt.strftime("%Y-%m")
    return p


def matched_hosts(which: str) -> pd.DataFrame:
    t = read_treated(which, "zip")
    rep = pd.read_csv(P / f"match_report_{which}.csv", dtype={"match_id": str})
    return t[t.geo_id.isin(rep.match_id[rep.matched])]


def zip_to_county() -> dict:
    cand = pd.read_csv(P / "control_candidates_zip.csv", dtype=str).drop_duplicates("zip")
    m = dict(zip(cand.zip, cand.county_fips))
    panel = load_site_panel()
    m.update(dict(zip(panel.zip.dropna(), panel.county_fips[panel.zip.notna()])))
    return m


# ---------------------------------------------------------------- outcomes
def zillow_panel(var: str, which: str) -> pd.DataFrame:
    long = read_long(var)
    long = long[(long.geo_type == "zip") & (long.variable == var)]
    ctrl = pd.read_csv(P / f"control_zip_{which}.csv", dtype=str)
    p = build_panel(long, matched_hosts(which), ctrl)
    return finish(add_controls(p, zip_to_county()))


def electricity_panel(timing: str = "treat_month") -> pd.DataFrame:
    util = eia.read_utility_monthly()
    treated = read_treated("strict", "county")
    if timing == "announce_month":
        sites = sample(load_site_panel(), "strict")
        ann = sites.groupby("county_fips").announce_month.min()
        treated = treated.assign(treat_month=treated.geo_id.map(ann).fillna(treated.treat_month))
    tu = eia.treated_utilities(eia.read_choice(), treated)
    ctrl = eia.utility_controls(util, tu)
    price = util[["utility_key", "month", "residential_price"]].rename(
        columns={"utility_key": "geo_id", "residential_price": "value"}).dropna()
    p = finish(build_panel(price, tu, ctrl))
    t = (p.month.dt.year - 2019) * 12 + p.month.dt.month
    for u in p.geo_id.unique():                     # one linear trend per utility
        p[f"trend_{u}"] = np.where(p.geo_id == u, t / 12, 0.0)
    return p


def delinquency_panel() -> pd.DataFrame:
    d = read_long("delinq")
    d = d[d.variable == "delinq_90"]
    ctrl = pd.read_csv(P / "control_county_strict.csv", dtype=str)
    rep = pd.read_csv(P / "match_report_county_strict.csv", dtype=str)
    t = read_treated("strict", "county")
    t = t[t.geo_id.isin(rep.match_id[rep.matched.str.lower() == "true"])]
    p = build_panel(d, t, ctrl)
    p = add_controls(p, {g: g for g in p.geo_id.unique()})
    return finish(p, scale=0)


def tax_panel() -> pd.DataFrame:
    p = pd.read_csv(P / "proptax_bill_panel.csv", dtype={"zip": str, "match_id": str})
    p = p.rename(columns={"zip": "geo_id"})
    p["y"] = 100 * p.log_tax_index
    p["treat_post"] = p.treated * p.post
    p["mt"] = p.match_id + "_" + p.tax_year.astype(str)
    p["event_time"] = p.event_year
    return p


# ---------------------------------------------------------------- run
SPECS = [  # name, outcome label, panel builder, fixed effects, controls, event-study settings
    ("zhvi_strict", "Home values (%)", lambda: zillow_panel("zhvi", "strict"), [], dict(bin_width=3, window=(-36, 24))),
    ("zhvi_broad", "Home values (%), broad sample", lambda: zillow_panel("zhvi", "broad"), [], dict(bin_width=3, window=(-36, 24))),
    ("zori_strict", "Rents (%)", lambda: zillow_panel("zori", "strict"), [], dict(bin_width=3, window=(-36, 24))),
    ("elec_strict", "Residential electricity price (%)", lambda: electricity_panel(), [], dict(bin_width=3, window=(-36, 18))),
    ("delinq_strict", "Mortgages 90+ days late (pct. points)", delinquency_panel, [], dict(bin_width=3, window=(-36, 24))),
    ("tax_strict", "Estimated property tax bill (%)", tax_panel, [], dict(bin_width=1, window=(-4, 2))),
]
FE = ["geo_id", "mt"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    reps = 50 if ap.parse_args().quick else 300
    rows, panels = [], {}
    for name, label, build, _, es_kw in SPECS:
        p = build()
        panels[name] = p
        r = rg.did(p, "y", FE, outcome=label, spec="main")
        r.perm_p, _, real_sub, n_groups = rg.permutation_test(p, "y", FE, r.coef, reps=reps)
        loo = rg.leave_one_out(p, "y", FE)
        lo, hi = loo.loc[loo.coef.idxmin()], loo.loc[loo.coef.idxmax()]
        swing = loo.loc[(loo.coef - r.coef).abs().idxmax()]
        rows.append(r.row() | {"model": name, "perm_groups": n_groups, "perm_coef": real_sub,
                               "loo_min": lo.coef, "loo_max": hi.coef,
                               "most_influential_site": swing.dropped, "coef_without_it": swing.coef})
        if {"unemp_rate", "log_income"} <= set(p.columns):
            rc = rg.did(p, "y", FE, controls=["unemp_rate", "log_income"], outcome=label,
                        spec="+ county unemployment, income")
            rows.append(rc.row() | {"model": name})
        es = rg.event_study(p, "y", FE, **es_kw)
        es.to_csv(P / f"results_event_{name}.csv", index=False, float_format="%.8g")
        rows[-1 if "unemp_rate" not in p else -2]["pre_bins_off_zero"] = rg.pretrend_test(es)
        print(f"{name:14s} beta={r.coef:+.3f} (se {r.se:.3f}, p={r.pvalue:.3f}) hosts={r.n_hosts} "
              f"obs={r.n_obs:,} | placebo p={r.perm_p:.3f} on {n_groups} groups (beta there {real_sub:+.3f}) "
              f"| drop {swing.dropped} -> {swing.coef:+.3f}")

    # electricity robustness: utility trends; announcement timing
    p = panels["elec_strict"]
    trends = [c for c in p.columns if c.startswith("trend_")]
    rt = rg.did(p, "y", FE, controls=trends, outcome="Residential electricity price (%)",
                spec="+ each utility's own linear trend")
    rows.append(rt.row() | {"model": "elec_strict"})
    pa = electricity_panel("announce_month")
    ra = rg.did(pa, "y", FE, outcome="Residential electricity price (%)", spec="timed at announcement")
    ra.perm_p, _, real_sub, n_groups = rg.permutation_test(pa, "y", FE, ra.coef, reps=reps)
    loo = rg.leave_one_out(pa, "y", FE)
    swing = loo.loc[(loo.coef - ra.coef).abs().idxmax()]
    rows.append(ra.row() | {"model": "elec_strict", "perm_groups": n_groups, "perm_coef": real_sub,
                            "loo_min": loo.coef.min(), "loo_max": loo.coef.max(),
                            "most_influential_site": swing.dropped, "coef_without_it": swing.coef})
    es = rg.event_study(pa, "y", FE, bin_width=3, window=(-36, 24))
    es.to_csv(P / "results_event_elec_announce.csv", index=False, float_format="%.8g")
    print(f"elec + trends  beta={rt.coef:+.3f} (se {rt.se:.3f}); at announcement beta={ra.coef:+.3f} "
          f"(se {ra.se:.3f}, placebo p={ra.perm_p:.3f}, leave-one-out {loo.coef.min():+.2f} to {loo.coef.max():+.2f}, "
          f"drop {swing.dropped} -> {swing.coef:+.2f})")

    res = pd.DataFrame(rows)
    res.to_csv(P / "results_did.csv", index=False, float_format="%.8g")

    # step 2: costs -> late mortgages, all CFPB counties in the project's states
    states = set(load_site_panel().county_fips.str[:2])
    mp = md.build_panel(states)
    med = md.cost_regressions(mp)
    hv = res[(res.model == "zhvi_strict") & (res.spec == "main")].coef.iloc[0]
    sd = mp.home_value_g12.std()
    only_home = med.spec.str.contains("home value growth only")
    g = med[only_home].coef.iloc[0]
    med["note"] = ""
    med.loc[only_home, "note"] = (
        f"implied effect of AI via home values: {g:+.4f} x {hv:+.2f}% / {sd:.2f}% SD = "
        f"{md.implied_effect(g, hv, sd):+.4f} pct. points")
    med.to_csv(P / "results_mediation.csv", index=False, float_format="%.8g")
    print("\nCosts -> late mortgages (12-month lag):")
    print(med[["spec", "coef", "se", "pvalue", "n_obs", "n_counties"]].round(4).to_string(index=False))
    plots(panels)
    print("\nSaved: data/processed/results_did.csv, results_mediation.csv, results_event_*.csv; figures/es_*.png")
    return 0


PLOT = {
    "zhvi_strict": ("Home values: AI host ZIPs vs. matched ZIPs", "Gap in home values (%)", "Months since AI operations began"),
    "zori_strict": ("Rents: AI host ZIPs vs. matched ZIPs", "Gap in rents (%)", "Months since AI operations began"),
    "elec_strict": ("Electricity: host utilities vs. same-state utilities", "Gap in residential price (%)", "Months since AI operations began"),
    "elec_announce": ("Electricity, timed at the data center's announcement", "Gap in residential price (%)", "Months since the data center was announced"),
    "delinq_strict": ("Late mortgages: host counties vs. matched counties", "Gap in share 90+ days late (pct. points)", "Months since AI operations began"),
    "tax_strict": ("Property tax bills: host towns vs. comparison towns", "Gap in estimated tax bill (%)", "Tax years since AI operations began"),
}


def plots(panels):
    for name, (title, ylab, xlab) in PLOT.items():
        es = pd.read_csv(P / f"results_event_{name}.csv")
        unit = "months" if "Months" in xlab else "years"
        event = "the announcement" if name == "elec_announce" else "AI"
        note = (f"Each point compares hosts with their own matched places in the same {unit[:-1]}, relative to "
                f"the {'3 months' if unit == 'months' else 'year'} before {event}.\nPoints reached by "
                "fewer than 4 hosts are left off. Standard errors clustered by site.")
        fig = event_study_plot(es, title, ylab, xlab, note, min_hosts=4)
        save(fig, f"es_{name}")


if __name__ == "__main__":
    sys.exit(main())
