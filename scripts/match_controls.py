"""Phase 1, step 2: pick 10 matched control ZIPs for every treated ZIP.

    python scripts/match_controls.py

Needs two things first:
  1. python scripts/build_treatment.py   (treatment tables + candidate pools)
  2. the Zillow home value pull, saved as data/processed/zhvi.csv in the
     shared long format (geo_type 'zip', variable 'zhvi')

Writes to data/processed/:
  control_zip_strict.csv, control_zip_broad.csv   geo_id, match_id, rank, ...
  match_report_strict.csv, match_report_broad.csv one row per treated ZIP
and prints a balance table: treated vs. controls before treatment. Small
growth gaps mean the controls are a fair comparison. Also saves
figures/zhvi_event_paths_<sample>.png: both groups' average path before
and after AI arrived. Before month 0 the lines should move together.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.io_utils import processed_file, read_long  # noqa: E402
from src.figures_matching import event_paths  # noqa: E402
from src.matching import balance_table, match_controls  # noqa: E402
from src.panel import build_panel  # noqa: E402
from src.plotting import save  # noqa: E402
from src.treatment import read_treated  # noqa: E402


def main() -> int:
    needed = [config.PROCESSED / "treated_zip_strict.csv",
              config.PROCESSED / "control_candidates_zip.csv"]
    if not all(p.exists() for p in needed):
        print("Run `python scripts/build_treatment.py` first.")
        return 1
    if not processed_file("zhvi").exists():
        print("data/processed/zhvi.csv.gz not found yet.\n"
              "Matching uses each ZIP's home value history, so it runs after the "
              "Zillow pull (Phase 3). Re-run this script once zhvi.csv.gz exists.")
        return 1

    zhvi = read_long("zhvi")
    zhvi = zhvi[(zhvi.geo_type == "zip") & (zhvi.variable == "zhvi")]
    cand = pd.read_csv(config.PROCESSED / "control_candidates_zip.csv",
                       dtype={"zip": str, "county_fips": str})

    for which in ("strict", "broad"):
        treated = read_treated(which, "zip")
        controls, report = match_controls(treated, cand, zhvi)
        controls.to_csv(config.PROCESSED / f"control_zip_{which}.csv", index=False)
        report.to_csv(config.PROCESSED / f"match_report_{which}.csv", index=False,
                      date_format="%Y-%m-%d")
        ok = report.matched.sum()
        print(f"\n{which.upper()} sample: matched {ok} of {len(report)} treated ZIPs, "
              f"{len(controls)} control rows")
        for r in report[~report.matched].itertuples():
            print(f"  not matched: {r.match_id} ({r.state}): {r.reason}")
        if ok:
            bal = balance_table(report, controls)
            print(bal.to_string(index=False))
            print(f"  average growth gap: {bal.growth_gap_pts.mean():+.2f} points/yr "
                  f"(closer to 0 is better)")
            matched = treated[treated.geo_id.isin(report.match_id[report.matched])]
            panel = build_panel(zhvi, matched, controls)
            fig = event_paths(panel, "Home values", len(matched))
            print(f"  figure: {save(fig, f'zhvi_event_paths_{which}').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
