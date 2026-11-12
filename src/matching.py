"""Phase 1: pick matched controls for each treated place.

For every treated ZIP (or county), look at the 36 months before its
treatment month and describe each place by two numbers:

* level: its average log value (how expensive it is), and
* growth: its yearly trend (how fast prices were rising).

The controls are the same-state candidates closest to the treated place on
both numbers. Matching on growth matters most: the whole design assumes
treated and control places were moving together before treatment.

This step needs the outcome data (Zillow ZHVI in the shared long format),
so it runs after the Zillow pull.
"""
import numpy as np
import pandas as pd

from src import config

PRE_MONTHS = 36
MIN_PRE_MONTHS = 24   # a treated place needs at least this much history


def pre_period_features(long: pd.DataFrame, geo_ids, treat_month,
                        months: int = PRE_MONTHS) -> pd.DataFrame:
    """Level and yearly growth of log value over the window before treat_month.

    Returns one row per geo_id with n_months, level, growth. `long` is a
    shared-format table already filtered to a single variable.
    """
    start = treat_month - pd.DateOffset(months=months)
    w = long[long.geo_id.isin(geo_ids)
             & (long.month >= start) & (long.month < treat_month)].dropna(subset=["value"])
    # time in years, counted in whole months (monthly data is evenly spaced)
    w = w[w.value > 0].assign(
        log_v=lambda d: np.log(d.value),
        t=lambda d: ((d.month.dt.year - start.year) * 12
                     + (d.month.dt.month - start.month)) / 12)

    def fit(g):
        slope = np.polyfit(g.t, g.log_v, 1)[0] if len(g) >= 2 else np.nan
        return pd.Series({"n_months": len(g), "level": g.log_v.mean(), "growth": slope})

    if w.empty:
        return pd.DataFrame(columns=["geo_id", "n_months", "level", "growth"])
    return w.groupby("geo_id")[["t", "log_v"]].apply(fit).reset_index()


def match_controls(treated: pd.DataFrame, candidates: pd.DataFrame,
                   long: pd.DataFrame, n: int = config.CONTROLS_PER_SITE,
                   cand_id: str = "zip") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pick the n closest same-state candidates for each treated place.

    treated:    geo_id, state, treat_month   (from build_treated)
    candidates: <cand_id>, state             (from candidate_zips / _counties)
    long:       geo_id, month, value         (one variable, e.g. ZHVI)

    Returns (controls, report):
      controls - geo_id, match_id, state, rank, distance, level, growth
      report   - one row per treated place: its features, how many
                 candidates had full data, and whether it was matched.
    A control may serve more than one treated place; match_id keeps the
    pairs separate.
    """
    controls, report = [], []
    for t in treated.itertuples():
        pool = candidates.loc[candidates.state == t.state, cand_id]
        feats = pre_period_features(long, set(pool) | {t.geo_id}, t.treat_month)
        me = feats[feats.geo_id == t.geo_id]
        cand = feats[(feats.geo_id != t.geo_id) & (feats.n_months >= PRE_MONTHS)]
        row = {"match_id": t.geo_id, "state": t.state,
               "treat_month": t.treat_month, "candidates_with_data": len(cand)}

        if me.empty or me.n_months.iloc[0] < MIN_PRE_MONTHS:
            report.append({**row, "matched": False,
                           "reason": "treated place has under 24 months of history"})
            continue
        if len(cand) < n:
            report.append({**row, "matched": False,
                           "reason": f"only {len(cand)} candidates with full history"})
            continue

        # put level and growth on the same scale before measuring distance
        mu, sd = cand[["level", "growth"]].mean(), cand[["level", "growth"]].std()
        z_c = (cand[["level", "growth"]] - mu) / sd
        z_t = (me[["level", "growth"]].iloc[0] - mu) / sd
        dist = np.sqrt(((z_c - z_t) ** 2).sum(axis=1))
        best = cand.assign(distance=dist).nsmallest(n, "distance")

        controls.append(best.assign(match_id=t.geo_id, state=t.state,
                                    rank=range(1, len(best) + 1)))
        report.append({**row, "matched": True, "reason": "",
                       "level": me.level.iloc[0], "growth": me.growth.iloc[0]})

    cols = ["geo_id", "match_id", "state", "rank", "distance", "level", "growth"]
    controls = (pd.concat(controls, ignore_index=True)[cols] if controls
                else pd.DataFrame(columns=cols))
    return controls, pd.DataFrame(report)


def balance_table(report: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    """Treated vs. matched-control averages before treatment.

    Good matches show small differences, especially in growth. Growth is
    shown as % per year; level as the typical value in dollars.
    """
    t = report[report.matched]
    c = controls.groupby("match_id")[["level", "growth"]].mean()
    t = t.set_index("match_id")[["level", "growth"]]
    out = pd.DataFrame({
        "treated_typical_value": np.exp(t.level),
        "controls_typical_value": np.exp(c.level.reindex(t.index)),
        "treated_growth_pct_yr": 100 * (np.exp(t.growth) - 1),
        "controls_growth_pct_yr": 100 * (np.exp(c.growth.reindex(t.index)) - 1),
    })
    out["growth_gap_pts"] = out.treated_growth_pct_yr - out.controls_growth_pct_yr
    return out.round(1).reset_index()
