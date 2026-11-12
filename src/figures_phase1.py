"""Phase 1 figures: where the sites are, and when AI arrived."""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from src.geo import load_zip_centroids
from src.plotting import COLORS, apply_style

LOWER48 = dict(lat=(24, 50), lon=(-125, -66.5))


def _strip_paren(text: str) -> str:
    return text.split(" (")[0].strip()


def short_labels(sites: pd.DataFrame) -> pd.Series:
    """'Company · Town, ST'; uses the site name where two sites share a town."""
    base = (sites.operator_parent.map(_strip_paren) + " · "
            + sites.city.map(_strip_paren) + ", " + sites.state)
    dup = base.duplicated(keep=False)
    named = (sites.site_name.map(_strip_paren) + " · "
             + sites.city.map(_strip_paren) + ", " + sites.state)
    return base.where(~dup, named)


def site_map(panel: pd.DataFrame):
    """All panel sites on a US outline drawn from ZIP centers, by sample."""
    apply_style()
    z = load_zip_centroids()
    z = z[z.lat.between(*LOWER48["lat"]) & z.lon.between(*LOWER48["lon"])]

    strict = panel.sample_strict_ai
    broad_only = panel.sample_broad_ai & ~strict
    other = ~panel.sample_broad_ai
    pts = panel.dropna(subset=["zip_lat", "zip_lon"])

    fig, ax = plt.subplots(figsize=(10, 6.2))
    ax.scatter(z.lon, z.lat, s=0.25, c=COLORS["backdrop"], linewidths=0, rasterized=True)
    for mask, kw in (
        (other, dict(s=34, facecolors="none", edgecolors=COLORS["neutral"], linewidths=1.2)),
        (broad_only, dict(s=48, c=COLORS["control"], edgecolors="white", linewidths=1)),
        (strict, dict(s=78, c=COLORS["ai"], edgecolors="white", linewidths=1.2, zorder=5)),
    ):
        p = pts[mask.reindex(pts.index)]
        ax.scatter(p.zip_lon, p.zip_lat, **kw)

    n = {k: int(m.sum()) for k, m in (("strict", strict), ("broad", broad_only), ("other", other))}
    handles = [
        Line2D([], [], ls="", marker="o", ms=9, mfc=COLORS["ai"], mec="white",
               label=f"Strict AI sample ({n['strict']}): built for AI or site-specific AI evidence"),
        Line2D([], [], ls="", marker="o", ms=7.5, mfc=COLORS["control"], mec="white",
               label=f"Broad sample only ({n['broad']}): company-wide AI evidence"),
        Line2D([], [], ls="", marker="o", ms=6.5, mfc="none", mec=COLORS["neutral"],
               label=f"Not in a sample ({n['other']}): proposed, under construction, or undated"),
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=9.5, handletextpad=0.4)
    ax.set_title(f"{len(panel)} data center sites in {panel.state.nunique()} states; "
                 f"{n['strict']} form the strict AI sample")
    ax.set_xlim(*LOWER48["lon"]); ax.set_ylim(*LOWER48["lat"])
    ax.set_aspect(1 / np.cos(np.radians(38)))
    ax.axis("off")
    missing = panel.zip_lat.isna().sum()
    fig.text(0.125, 0.06, f"Dots sit at ZIP centers, not exact facilities. {missing} sites with "
             "no confirmed ZIP are not shown. Background: US ZIP code centers.",
             fontsize=8.5, color=COLORS["text_secondary"])
    return fig


def treatment_timeline(sites: pd.DataFrame, data_ends: dict):
    """Each strict site's announcement and AI start month, with data cut-offs.

    data_ends: {"Zillow (approx.)": "2026-10-01", "CFPB delinquency": "2026-03-01"}
    """
    apply_style()
    s = sites.sort_values("treat_month").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 0.36 * len(s) + 1.6))
    y = np.arange(len(s))[::-1]

    for yi, r in zip(y, s.itertuples()):
        if pd.notna(r.announce_month) and r.announce_month < r.treat_month:
            ax.plot([r.announce_month, r.treat_month], [yi, yi],
                    color=COLORS["neutral"], lw=1.5, zorder=1)
    has_a = s.announce_month.notna()
    ax.scatter(s.announce_month[has_a], y[has_a.to_numpy()], s=46, facecolors="white",
               edgecolors=COLORS["neutral"], linewidths=1.5, zorder=3, label="Announced")
    ax.scatter(s.treat_month, y, s=58, c=COLORS["ai"], edgecolors="white",
               linewidths=1, zorder=4, label="AI operations began (treatment month)")

    # data cut-offs: labels alternate sides of their line so they never collide
    for i, (label, end) in enumerate(sorted(data_ends.items(), key=lambda kv: kv[1])):
        end = pd.Timestamp(end)
        ax.axvline(end, color=COLORS["text_secondary"], lw=1, ls=(0, (4, 3)), zorder=0)
        right = i % 2 == 1
        ax.text(end, len(s) - 0.1, f"{' ' if right else ''}{label}\n"
                f"{' ' if right else ''}ends {end:%b %Y}{'' if right else ' '}",
                fontsize=8.5, color=COLORS["text_secondary"], va="bottom",
                ha="left" if right else "right")

    ax.set_yticks(y, short_labels(s), fontsize=9.5)
    ax.grid(axis="y", visible=False)
    ax.set_ylim(-0.8, len(s) + 1.1)
    fig.suptitle("Most AI sites switched on in 2025, leaving months, not years, of after-data",
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    ax.legend(loc="lower left", fontsize=9, bbox_to_anchor=(0, -0.02 - 2.2 / len(s)), ncol=2)
    return fig
