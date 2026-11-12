"""Run this first, and again whenever something seems off:

    python scripts/check_setup.py

It checks your Python version, installed packages, folder layout, that the
data files came with your copy of the repo, and that the site panel is clean.
Every line should say OK.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `src` importable

PACKAGES = ["pandas", "numpy", "requests", "matplotlib", "statsmodels",
            "linearmodels", "dotenv", "openpyxl", "xlrd", "pdfplumber", "zipcodes",
            "addfips", "pytest"]

# A few files every step needs; if these are missing the clone is incomplete.
DATA_FILES = ["data/raw/eia/sales_revenue.xlsx", "data/raw/cfpb",
              "data/processed/zhvi.csv.gz", "data/processed/elec_utility.csv.gz",
              "data/processed/delinq.csv", "data/property_tax_controls.csv"]


def line(status: str, msg: str) -> None:
    print(f"  [{status:7}] {msg}")


def main() -> int:
    failures = 0
    print("\nECO 3630 AI data center project: setup check\n")

    print("Python")
    ok = sys.version_info >= (3, 10)
    line("OK" if ok else "FAIL", f"version {sys.version.split()[0]} (need 3.10+)")
    failures += not ok

    print("Packages")
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
            line("OK", f"{name} {getattr(mod, '__version__', '')}")
        except ImportError:
            line("FAIL", f"{name} not installed -> pip install -r requirements.txt")
            failures += 1

    from src import config

    print("Folders")
    for p in (config.RAW, config.PROCESSED, config.FIGURES):
        p.mkdir(parents=True, exist_ok=True)
        line("OK", str(p.relative_to(config.ROOT)))

    print("Data files")
    for rel in DATA_FILES:
        ok = (config.ROOT / rel).exists()
        line("OK" if ok else "FAIL", rel if ok else f"{rel} missing -> re-download the repo "
             "(GitHub 'Download ZIP' or git clone), not single files")
        failures += not ok
    line("OK", "no API keys needed: every source is a saved public file in data/raw/")

    print("Site panel")
    from src.io_utils import load_site_panel, sample
    from src.validate import validate_site_panel
    import pandas as pd

    raw = pd.read_csv(config.SITE_PANEL, dtype=str, keep_default_na=False)
    problems = validate_site_panel(raw)
    if problems:
        for p in problems:
            line("FAIL", p)
        failures += 1
    else:
        panel = load_site_panel()
        line("OK", f"{len(panel)} sites, {panel.state.nunique()} states, no problems found")
        line("OK", f"strict AI sample: {len(sample(panel, 'strict'))} sites; "
                   f"broad: {len(sample(panel, 'broad'))}")
        unverified = (panel.verification != "re-verified Nov 2026").sum()
        if unverified:
            line("NOTE", f"{unverified} rows still marked not re-verified (see 'verification')")

    print("\n" + ("All checks passed.\n" if not failures else f"{failures} problem(s) above.\n"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
