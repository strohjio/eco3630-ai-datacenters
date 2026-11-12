"""Difference-in-differences and event studies, one estimator for every outcome.

Every regression has the same shape:

    y[i,t] = beta * (host_i x after AI_t) + controls + place FE + group-by-time FE + error

* place FE: each ZIP / county / utility gets its own average level.
* group-by-time FE: each host and its own comparison places share a time effect
  (a "match group" x month dummy). So beta compares a host only with its own
  matched comparisons in the same month, never with other states' towns.
* Standard errors are clustered by match group (one cluster per site), because
  a host and its comparisons share local shocks. With only ~10-15 sites these
  clustered SEs are approximate, so `permutation_test` adds a check that needs
  no SE formula at all: pretend a comparison place was the host, re-estimate
  many times, and see how often a fake effect is as big as the real one.

Estimates use linearmodels.AbsorbingLS, which removes the fixed effects
("absorbs" them) instead of creating thousands of dummy columns.
"""
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from linearmodels.iv.absorbing import AbsorbingEffectWarning, AbsorbingLS

# linearmodels warns when a column is fully explained by the fixed effects and
# drops it (drop_absorbed=True). In this project that is expected: e.g. with
# one linear trend per utility, one trend per match group duplicates the group
# x month effects. The estimate of interest is never dropped silently: did()
# raises a KeyError if the treatment column itself is absorbed.
warnings.filterwarnings("ignore", category=AbsorbingEffectWarning)


@dataclass
class DiD:
    """Result of one difference-in-differences regression."""
    outcome: str
    spec: str
    coef: float
    se: float
    pvalue: float
    ci_low: float
    ci_high: float
    n_obs: int
    n_hosts: int
    n_clusters: int
    perm_p: float | None = None

    def row(self) -> dict:
        return self.__dict__.copy()


def _prep(df: pd.DataFrame, y: str, x: list[str], fe: list[str], cluster: str):
    cols = [y, *x, *fe, cluster]
    d = df.dropna(subset=list(dict.fromkeys(cols))).copy()
    absorb = pd.DataFrame({f: d[f].astype(str).astype("category") for f in fe}, index=d.index)
    return d, absorb


def did(df: pd.DataFrame, y: str, fe: list[str], cluster: str = "match_id",
        controls: list[str] = (), treat_col: str = "treat_post", spec: str = "",
        outcome: str = "") -> DiD:
    """beta on host x after AI, with the given fixed effects absorbed."""
    x = [treat_col, *controls]
    d, absorb = _prep(df, y, x, fe, cluster)
    res = AbsorbingLS(d[y], d[x], absorb=absorb, drop_absorbed=True).fit(
        cov_type="clustered", clusters=d[cluster].astype("category").cat.codes)
    b, se = float(res.params[treat_col]), float(res.std_errors[treat_col])
    ci = res.conf_int().loc[treat_col]
    return DiD(outcome or y, spec, b, se, float(res.pvalues[treat_col]), float(ci.iloc[0]),
               float(ci.iloc[1]), int(res.nobs), int(d.loc[d.treated == 1].geo_id.nunique()),
               int(d[cluster].nunique()))


def event_study(df: pd.DataFrame, y: str, fe: list[str], time_col: str = "event_time",
                bin_width: int = 3, window: tuple[int, int] = (-36, 24), ref_bin: int = -1,
                cluster: str = "match_id", controls: list[str] = ()) -> pd.DataFrame:
    """Host-vs-comparison gap in each period around AI, relative to the period before.

    Event time is grouped into bins of `bin_width` (3 = quarters of months; use 1
    for yearly data). Bin -1 (the 3 months before AI) is the reference, set to 0.
    Months outside the window are dropped. Returns one row per bin with the
    estimate and a 95% confidence interval.
    """
    d = df[(df[time_col] >= window[0]) & (df[time_col] <= window[1])].copy()
    d["bin"] = np.floor(d[time_col] / bin_width).astype(int)
    bins = sorted(b for b in d.bin.unique() if b != ref_bin)
    names = []
    for b in bins:
        n = f"bin_{b}".replace("-", "m")
        d[n] = ((d.bin == b) & (d.treated == 1)).astype(float)
        names.append(n)
    x = [*names, *controls]
    dd, absorb = _prep(d, y, x, fe, cluster)
    res = AbsorbingLS(dd[y], dd[x], absorb=absorb, drop_absorbed=True).fit(
        cov_type="clustered", clusters=dd[cluster].astype("category").cat.codes)
    ci = res.conf_int()
    hosts = dd[dd.treated == 1].groupby("bin").match_id.nunique()
    rows = [dict(bin=b, start=b * bin_width, coef=float(res.params[n]), se=float(res.std_errors[n]),
                 ci_low=float(ci.loc[n].iloc[0]), ci_high=float(ci.loc[n].iloc[1]),
                 hosts=int(hosts.get(b, 0)))
            for b, n in zip(bins, names) if n in res.params.index]
    rows.append(dict(bin=ref_bin, start=ref_bin * bin_width, coef=0.0, se=0.0, ci_low=0.0,
                     ci_high=0.0, hosts=int(hosts.get(ref_bin, 0))))
    return pd.DataFrame(rows).sort_values("bin").reset_index(drop=True)


def pretrend_test(es: pd.DataFrame) -> float:
    """Rough check: average of pre-AI bin estimates divided by its spread.

    Returns the share of pre-AI bins whose 95% interval excludes zero. Near 0
    means the groups moved together before AI (what the method needs).
    """
    pre = es[(es.start < 0) & (es.se > 0)]
    if pre.empty:
        return float("nan")
    return float(((pre.ci_low > 0) | (pre.ci_high < 0)).mean())


def permutation_test(df: pd.DataFrame, y: str, fe: list[str], real: float, reps: int = 300,
                     seed: int = 3630, cluster: str = "match_id", controls: list[str] = ()) -> tuple:
    """Placebo hosts: in each match group, a random comparison place plays the host.

    The real host is dropped; its AI date is kept. The p-value is the share of
    placebo estimates at least as large (in absolute value) as the real one.

    Only match groups with at least 2 comparison places are used, for the real
    estimate too: with a single comparison, a placebo host would have nothing
    left to be compared with. `real` is therefore re-estimated on those groups
    (pass it anyway, it is kept only if no group is dropped).
    """
    rng = np.random.default_rng(seed)
    n_ctrl = df[df.treated == 0].groupby("match_id").geo_id.nunique()
    keep = set(n_ctrl[n_ctrl >= 2].index)
    if len(keep) < df.match_id.nunique():
        df = df[df.match_id.isin(keep)]
        real = did(df, y, fe, cluster, controls).coef
    ctrl = df[df.treated == 0]
    groups = {g: s.geo_id.unique() for g, s in ctrl.groupby("match_id")}
    draws = []
    for _ in range(reps):
        fake = {g: rng.choice(ids) for g, ids in groups.items()}
        p = ctrl.copy()
        p["treated"] = (p.geo_id == p.match_id.map(fake)).astype(int)
        p["treat_post"] = p.treated * p.post
        try:
            draws.append(did(p, y, fe, cluster, controls).coef)
        except Exception:      # a placebo draw with no variation left
            continue
    draws = np.array(draws)
    return float((np.abs(draws) >= abs(real)).mean()), draws, real, len(groups)


def leave_one_out(df: pd.DataFrame, y: str, fe: list[str], cluster: str = "match_id",
                  controls: list[str] = ()) -> pd.DataFrame:
    """Re-estimate dropping one site (match group) at a time.

    If one site moves the estimate a lot, the result rests on that site.
    """
    rows = []
    for g in sorted(df.match_id.unique()):
        try:
            r = did(df[df.match_id != g], y, fe, cluster, controls)
            rows.append(dict(dropped=g, coef=r.coef, se=r.se))
        except Exception:
            continue
    return pd.DataFrame(rows)
