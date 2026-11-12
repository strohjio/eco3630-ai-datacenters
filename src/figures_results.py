"""Event-study charts with 95% confidence intervals."""
import matplotlib.pyplot as plt
import pandas as pd

from src.plotting import COLORS, apply_style


def event_study_plot(es: pd.DataFrame, title: str, ylabel: str, xlabel: str,
                     note: str = "", min_hosts: int = 1):
    """Point estimates and 95% CIs by period; the reference period is 0 by design."""
    apply_style()
    es = es[es.hosts >= min_hosts]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axhline(0, color=COLORS["neutral"], lw=0.8)
    ax.axvline(-0.5, color=COLORS["text_secondary"], lw=1, ls=(0, (4, 3)))
    x = es.start
    ax.fill_between(x, es.ci_low, es.ci_high, color=COLORS["ai"], alpha=0.15, lw=0,
                    label="95% confidence interval")
    ax.plot(x, es.coef, color=COLORS["ai"], marker="o", ms=4, lw=1.8,
            label="AI host minus comparison places")
    ref = es[es.se == 0]
    ax.scatter(ref.start, ref.coef, s=40, facecolor="white", edgecolor=COLORS["ai"], zorder=3,
               label="Reference period (set to 0)")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", fontsize=9)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12.5, fontweight="bold")
    if note:
        fig.text(0.01, -0.04, note, fontsize=8.5, color=COLORS["text_secondary"])
    return fig
