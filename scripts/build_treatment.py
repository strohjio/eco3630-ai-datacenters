"""Phase 1: build the treatment tables, control candidate pools and figures.

    python scripts/build_treatment.py

Writes to data/processed/:
    treated_zip_strict.csv, treated_county_strict.csv     headline sample
    treated_zip_broad.csv,  treated_county_broad.csv      robustness sample
    control_candidates_zip.csv, control_candidates_county.csv
and to figures/: site_map.png, treatment_timeline.png

Matching controls to treated places is a separate step
(scripts/match_controls.py) because it needs the Zillow data first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src.figures_phase1 import site_map, treatment_timeline  # noqa: E402
from src.geo import candidate_counties, candidate_zips, pool_summary  # noqa: E402
from src.io_utils import load_site_panel  # noqa: E402
from src.plotting import save  # noqa: E402
from src.treatment import (build_treated, save_treated, treated_sites,  # noqa: E402
                           treatment_summary)

# When each data source currently ends; update as new data is released.
DATA_ENDS = {"Zillow (approx.)": "2026-10-01", "CFPB delinquency": "2026-03-01"}


def main() -> None:
    panel = load_site_panel()
    print("\nTreatment tables")
    tables = {}
    for which in ("strict", "broad"):
        for level in ("zip", "county"):
            t = build_treated(panel, which, level)
            tables[which, level] = t
            print(f"  {save_treated(t, which, level).name:32} {len(t):3} places")
    print("\n" + treatment_summary(panel).to_string(index=False))

    # Candidate pools cover every state in the broad sample (a superset of strict).
    print("\nControl candidate pools (same state, 15+ miles from every site, "
          "outside host counties)")
    cz = candidate_zips(panel, tables["broad", "zip"])
    cc = candidate_counties(panel, tables["broad", "county"])
    for name, df in (("control_candidates_zip", cz), ("control_candidates_county", cc)):
        out = config.PROCESSED / f"{name}.csv"
        df.round(4).to_csv(out, index=False)
        print(f"  {out.name:32} {len(df):5} places")
    print("\nZIP candidates per treated ZIP, strict sample:")
    print(pool_summary(tables["strict", "zip"], cz).to_string(index=False))

    print("\nFigures")
    print("  " + save(site_map(panel), "site_map").name)
    sites = treated_sites(panel, "strict")
    print("  " + save(treatment_timeline(sites, DATA_ENDS), "treatment_timeline").name)
    print()


if __name__ == "__main__":
    main()
