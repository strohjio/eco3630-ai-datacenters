"""Phase 4: the analysis panel, one row per place per month.

Joins an outcome (shared long format) to the treated places and their
matched controls, and adds what every plot and regression needs:

  event_time   months since the site's treatment month (-1 = month before)
  post         1 from the treatment month on
  log_value    natural log of the outcome
  since_treat  change since month -1 (0 at month -1, for every place)
  since_treat_pts  the same change in units of the outcome (for rates
               like % of mortgages late, where points read better)
  yoy          change versus the same month a year earlier

Each control borrows the treatment month of the treated place it was
matched to, so treated and control rows line up on the same clock.
"""
import numpy as np
import pandas as pd

from src import config


def build_panel(outcome: pd.DataFrame, treated: pd.DataFrame,
                controls: pd.DataFrame, window=config.EVENT_WINDOW) -> pd.DataFrame:
    """outcome:  geo_id, month, value         (one variable, long format)
    treated:  geo_id, treat_month           (from build_treated / read_treated)
    controls: geo_id, match_id              (from match_controls)
    """
    t = treated[["geo_id", "treat_month"]].assign(match_id=treated.geo_id, treated=1)
    c = (controls[["geo_id", "match_id"]]
         .merge(treated[["geo_id", "treat_month"]].rename(columns={"geo_id": "match_id"}),
                on="match_id")
         .assign(treated=0))
    groups = pd.concat([t, c], ignore_index=True)

    df = (outcome[["geo_id", "month", "value"]]
          .merge(groups, on="geo_id")
          .sort_values(["match_id", "geo_id", "month"]))
    df["event_time"] = ((df.month.dt.year - df.treat_month.dt.year) * 12
                        + (df.month.dt.month - df.treat_month.dt.month))
    df["post"] = (df.event_time >= 0).astype(int)
    df["log_value"] = np.log(df.value.where(df.value > 0))   # 0 has no log

    g = df.groupby(["match_id", "geo_id"]).value
    df["yoy"] = g.pct_change(12, fill_method=None)
    base = (df[df.event_time == -1].set_index(["match_id", "geo_id"]).value.rename("base"))
    df = df.join(base, on=["match_id", "geo_id"])
    df["since_treat"] = df.value / df.base - 1
    df["since_treat_pts"] = df.value - df.base

    lo, hi = window
    return df[df.event_time.between(lo, hi)].drop(columns="base").reset_index(drop=True)


def event_means(panel: pd.DataFrame, col: str = "since_treat") -> pd.DataFrame:
    """Average of `col` by event time for treated and control places.

    Controls are first averaged within each match group, so each treated
    site and its own controls carry equal weight.
    """
    per_group = (panel.groupby(["match_id", "treated", "event_time"])[col].mean()
                 .reset_index())
    out = (per_group.groupby(["event_time", "treated"])[col]
           .agg(["mean", "count"]).unstack("treated"))
    out.columns = [f"{stat}_{'treated' if t else 'control'}" for stat, t in out.columns]
    out["gap"] = out.mean_treated - out.mean_control
    return out.reset_index()
