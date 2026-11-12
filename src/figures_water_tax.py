"""Charts for the hand-collected property tax and water data."""
import matplotlib.pyplot as plt
import pandas as pd

from src.plotting import COLORS, apply_style
from src.water_tax import tax_series


def tax_event_index(tax: pd.DataFrame, treated: pd.DataFrame):
    """Each host place's tax rate, indexed to 100 in the year before AI.

    Thin lines are places; the thick line is their average in each event year.
    Only places with a rate in the year before AI are shown.
    """
    apply_style()
    s = tax_series(tax).merge(treated[["site_id", "treat_month"]], on="site_id")
    s = s.drop_duplicates(["county_fips", "tax_year"])          # shared counties once
    s["event_year"] = s.tax_year - s.treat_month.dt.year
    base = s[s.event_year == -1].set_index("site_id").rate_per_100
    s = s[s.site_id.isin(base.index)].copy()
    s["index"] = 100 * s.rate_per_100 / s.site_id.map(base)
    s = s[s.event_year >= -5]          # earlier years: too few places to average
    fig, ax = plt.subplots(figsize=(9, 5))
    for site, g in s.groupby("site_id"):
        g = g.sort_values("event_year")
        ax.plot(g.event_year, g["index"], color=COLORS["ai"], alpha=0.25, lw=1)
        last = g.iloc[-1]
        if last.event_year < 0:        # no year after AI yet: nothing to label
            continue
        ax.annotate(last.place.split(" (")[0], (last.event_year, last["index"]), xytext=(4, 0),
                    textcoords="offset points", fontsize=7.5, color=COLORS["text_secondary"], va="center")
    m = s.groupby("event_year")["index"].agg(["mean", "count"]).reset_index()
    m = m[m["count"] >= 3]
    ax.plot(m.event_year, m["mean"], color=COLORS["ai"], lw=2.5, label=f"Average of host places ({s.site_id.nunique()})")
    ax.axhline(100, color=COLORS["neutral"], lw=0.8)
    ax.axvline(-0.5, color=COLORS["text_secondary"], lw=1, ls=(0, (4, 3)))
    ax.set_xlabel("Tax years since AI operations began (0 = the year AI started)")
    ax.set_ylabel("Property tax rate (year before AI = 100)")
    ax.legend(loc="lower left", fontsize=9)
    fig.suptitle("Host-town property tax rates were already falling before AI arrived",
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.01, -0.03, "Each place compared with itself, because states tax different shares of value. "
             "No comparison towns yet. Memphis 2025\nis a reappraisal year "
             "(rates reset when values are updated). Official state and county figures; average where 3+ places have data.",
             fontsize=8.5, color=COLORS["text_secondary"])
    return fig


def tax_bill_event(p: pd.DataFrame, min_sites: int = 4):
    """Estimated tax bill (rate x home value): host towns vs comparison towns.

    p: the panel from src.tax_bill.build. Years reached by fewer than
    `min_sites` sites are left off.
    """
    from src.tax_bill import event_means

    apply_style()
    m = event_means(p)
    m = m[(m.sites >= min_sites)]
    n = p[p.treated == 1].site_id.nunique()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axhline(0, color=COLORS["neutral"], lw=0.8)
    ax.axvline(-0.5, color=COLORS["text_secondary"], lw=1, ls=(0, (4, 3)))
    ax.plot(m.event_year, m.control, color=COLORS["control"], marker="o", ms=4,
            label="Comparison towns (same state, matched on home values)")
    ax.plot(m.event_year, m.treated, color=COLORS["ai"], marker="o", ms=4,
            label=f"AI host towns ({n})")
    last = m.iloc[-1]
    for col in ("treated", "control"):
        ax.annotate(f"{last[col]:+.1f}%", (last.event_year, last[col]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9.5, fontweight="bold",
                    color=COLORS["text"])
    ax.set_xlabel("Tax years since AI operations began (0 = the year AI started)")
    ax.set_ylabel("Estimated tax bill on the typical home\nchange since the year before AI (%)")
    ax.set_xlim(m.event_year.min() - 0.5, m.event_year.max() + 0.8)
    ax.legend(loc="upper left", fontsize=9)
    gap = last.treated - last.control
    fig.suptitle(f"Estimated tax bills in AI host towns rose {gap:.1f} points more than comparison "
                 f"towns by year {int(last.event_year)}",
                 x=0.01, ha="left", fontsize=12.5, fontweight="bold")
    fig.text(0.01, -0.04,
             "Bill = tax rate x Zillow home value. Each site's comparison towns are averaged first, so every "
             "site counts once.\nYears with fewer than "
             f"{min_sites} sites are left off. Preliminary: no confidence bands or regression yet.",
             fontsize=8.5, color=COLORS["text_secondary"])
    return fig
