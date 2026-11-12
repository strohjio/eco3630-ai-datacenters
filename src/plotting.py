"""One look for every chart in the project.

Use these colors and `apply_style()` in every notebook so the slides look
like one team made them. AI sites are always blue, controls always orange.
The pair passes colorblind-safety checks (protanopia/deuteranopia/tritanopia).
"""
from pathlib import Path

import matplotlib as mpl

from src import config

COLORS = {
    "ai": "#2a78d6",          # AI data center places (treated)
    "control": "#eb6834",     # matched control places
    "neutral": "#9a9890",     # everything else (other sites, reference lines)
    "backdrop": "#dedcd5",    # map backdrop, gridlines
    "text": "#0b0b0b",
    "text_secondary": "#52514e",
    "surface": "#fcfcfb",
}


def apply_style() -> None:
    """Quiet axes, readable type, no chart junk."""
    mpl.rcParams.update({
        "figure.facecolor": COLORS["surface"],
        "axes.facecolor": COLORS["surface"],
        "savefig.facecolor": COLORS["surface"],
        "font.size": 10.5,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.labelcolor": COLORS["text_secondary"],
        "axes.edgecolor": COLORS["backdrop"],
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": COLORS["backdrop"],
        "grid.linewidth": 0.6,
        "xtick.color": COLORS["text_secondary"],
        "ytick.color": COLORS["text_secondary"],
        "legend.frameon": False,
        "lines.linewidth": 2,
    })


def save(fig, name: str) -> Path:
    """Save a figure to figures/<name>.png at 200 dpi."""
    out = config.FIGURES / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200, bbox_inches="tight")
    return out
