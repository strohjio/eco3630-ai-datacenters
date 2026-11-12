"""Run the whole project, in order, with one command.

    python scripts/run_all.py              # results only: audit + regressions (~3 min)
    python scripts/run_all.py --full       # rebuild every table from data/raw/ first (~6 min)
    python scripts/run_all.py --quick      # results only, 50 placebo draws (~1 min)

Every step is a separate script and can also be run on its own (see the
pipeline table in README.md). The repo already includes every processed
table, so the results-only run needs nothing else.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BUILD = [  # rebuild order: each step uses the ones before it
    "build_treatment.py",     # 1. treated places + comparison pools
    "pull_zillow.py",         # 2a. home values, rents
    "match_controls.py",      # 3. matched comparison ZIPs (needs Zillow)
    "pull_eia.py",            # 2b. electricity
    "pull_cfpb.py",           # 2c. mortgage delinquency
    "build_tax_controls.py",  # 2d. tax comparison towns (slowest: reads state PDFs)
    "build_water_tax.py",     # 2e. property tax + water
    "pull_controls.py",       # 2f. Census / BLS / FRED controls
]
RESULTS = ["audit_data.py", "run_regressions.py"]


def run(script: str, extra: list[str]) -> float:
    print(f"\n{'=' * 70}\n>>> python scripts/{script} {' '.join(extra)}\n{'=' * 70}", flush=True)
    t0 = time.time()
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *extra], cwd=ROOT)
    if done.returncode:
        sys.exit(f"\n{script} stopped with an error (above). Fix it, then re-run that script "
                 f"on its own: python scripts/{script}")
    return time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="rebuild every table from data/raw/ first")
    ap.add_argument("--quick", action="store_true", help="50 placebo draws instead of 300")
    a = ap.parse_args()
    steps = ["check_setup.py", *(BUILD if a.full else []), *RESULTS]
    times = {s: run(s, ["--quick"] if a.quick and s == "run_regressions.py" else []) for s in steps}
    print("\nDone. Times:")
    for s, t in times.items():
        print(f"  {s:24} {t:6.0f} s")
    print("\nResults: data/processed/results_did.csv, results_mediation.csv\n"
          "Charts:  figures/es_*.png (event studies) and the other figures/*.png")


if __name__ == "__main__":
    main()
