"""Figures for checking matches and previewing the main result."""
import matplotlib.pyplot as plt
import pandas as pd

from src.panel import event_means
from src.plotting import COLORS, apply_style

MIN_SITES = 10   # only plot months that at least this many treated sites reach


def event_paths(panel: pd.DataFrame, label: str, n_sites: int, title: str | None = None,
                unit: str = "ZIPs", controls_note: str = "10 per site",
                min_sites: int = MIN_SITES, points: bool = False):
    """Treated vs matched-control average change since the month before AI.

    Months reached by fewer than min_sites treated sites are left off: an
    average of three or four sites swings on which sites happen to be in it.
    With no title given, the title states the gap at the last plotted month.
    unit names the places ('ZIPs', 'counties', 'utilities'). points=True
    plots the change in the outcome's own units (for rates) instead of %.
    """
    apply_style()
    m = event_means(panel, "since_treat_pts" if points else "since_treat")
    k, sym = (1, " pts") if points else (100, "%")
    keep = m.count_treated >= min_sites
    m = m[keep]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.axhline(0, color=COLORS["neutral"], lw=0.8)
    ax.axvline(-0.5, color=COLORS["text_secondary"], lw=1, ls=(0, (4, 3)))
    ax.plot(m.event_time, k * m.mean_control, color=COLORS["control"],
            label=f"Comparison {unit} ({controls_note})")
    ax.plot(m.event_time, k * m.mean_treated, color=COLORS["ai"],
            label=f"AI data center {unit} ({n_sites})")
    last = m.iloc[-1]
    for col, color in (("mean_treated", COLORS["ai"]), ("mean_control", COLORS["control"])):
        ax.annotate(f"{k * last[col]:+.{2 if points else 1}f}{sym}", (last.event_time, k * last[col]),
                    xytext=(6, 0), textcoords="offset points", va="center",
                    fontsize=9.5, color=COLORS["text"], fontweight="bold")
    ax.text(0.2, ax.get_ylim()[1], "AI operations begin", fontsize=9,
            color=COLORS["text_secondary"], va="top")
    ax.set_xlabel("Months since AI operations began")
    ax.set_ylabel(f"{label}\nchange since the month before "
                  + ("(pct. points)" if points else "(%)"))
    ax.set_xlim(m.event_time.min() - 1, m.event_time.max() + 4)
    ax.legend(loc="upper left", fontsize=9.5)
    cut = int(m.event_time.max())
    if title is None:
        gap = k * last.gap
        title = (f"{label} in AI data center {unit} rose {abs(gap):.{2 if points else 1}f} points "
                 f"{'more' if gap > 0 else 'less'} than comparison {unit} in the first {cut} months")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.01, -0.03,
             f"Averages give each site and its own controls equal weight. Months after +{cut} are "
             f"left off: fewer than {min_sites} sites have reached them yet.\n"
             "Preliminary: no confidence bands or regression yet.",
             fontsize=8.5, color=COLORS["text_secondary"])
    return fig
