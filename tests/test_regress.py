"""The estimator must recover a known effect from fake data. Run with:  pytest -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import regress as rg  # noqa: E402

FE = ["geo_id", "mt"]


def fake_panel(effect=5.0, n_groups=12, n_ctrl=6, seed=0, pre_trend=0.0):
    """Hosts get `effect` added from their AI month on; everyone shares group shocks."""
    rng = np.random.default_rng(seed)
    months = pd.date_range("2021-01-01", "2025-12-01", freq="MS")
    rows = []
    for g in range(n_groups):
        start = months[24 + rng.integers(0, 18)]
        shock = rng.normal(0, 2, len(months)).cumsum()            # shared by the group
        for u in range(n_ctrl + 1):
            treated = int(u == 0)
            level = rng.normal(100, 10)
            et = ((months.year - start.year) * 12 + months.month - start.month).values
            post = (et >= 0).astype(int)
            y = (level + shock + rng.normal(0, 0.5, len(months)) + effect * treated * post
                 + pre_trend * treated * np.minimum(et, 0) / 12)
            rows.append(pd.DataFrame({"geo_id": f"g{g}u{u}", "match_id": f"g{g}", "month": months,
                                      "treated": treated, "post": post, "event_time": et, "y": y}))
    p = pd.concat(rows, ignore_index=True)
    p["treat_post"] = p.treated * p.post
    p["mt"] = p.match_id + "_" + p.month.dt.strftime("%Y-%m")
    return p


def test_did_recovers_known_effect():
    r = rg.did(fake_panel(effect=5.0), "y", FE)
    assert r.coef == pytest.approx(5.0, abs=0.3)
    assert r.ci_low < 5.0 < r.ci_high and r.pvalue < 0.01
    assert r.n_hosts == 12 and r.n_clusters == 12


def test_did_finds_nothing_when_there_is_nothing():
    r = rg.did(fake_panel(effect=0.0), "y", FE)
    assert abs(r.coef) < 0.5 and r.pvalue > 0.01


def test_event_study_flat_before_and_jumps_after():
    es = rg.event_study(fake_panel(effect=5.0), "y", FE, bin_width=3, window=(-24, 12))
    assert es.loc[es.start == -3, "coef"].iloc[0] == 0.0                # reference bin
    assert es[es.start < -3].coef.abs().max() < 1.0
    assert es[es.start >= 0].coef.mean() == pytest.approx(5.0, abs=0.6)
    assert rg.pretrend_test(es) <= 0.2


def test_event_study_shows_a_pre_trend_when_one_exists():
    es = rg.event_study(fake_panel(effect=0.0, pre_trend=4.0), "y", FE, bin_width=3, window=(-24, 12))
    assert es[es.start == -24].coef.iloc[0] < -5                        # hosts were lower earlier


def test_placebo_rejects_real_effect_and_accepts_none():
    p_real, draws, _, groups = rg.permutation_test(fake_panel(effect=5.0), "y", FE, 5.0, reps=40)
    assert p_real < 0.05 and groups == 12 and len(draws) == 40
    p_none, *_ = rg.permutation_test(fake_panel(effect=0.0, seed=1), "y", FE, 0.0, reps=40)
    assert p_none > 0.5


def test_leave_one_out_one_row_per_site():
    loo = rg.leave_one_out(fake_panel(effect=5.0, n_groups=5), "y", FE)
    assert len(loo) == 5 and loo.coef.between(4, 6).all()
