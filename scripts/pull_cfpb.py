"""Phase 2b: CFPB mortgage delinquency -> data/processed/delinq.csv, plus county matching.

    python scripts/pull_cfpb.py

Before running, save both county files from
https://www.consumerfinance.gov/data-research/mortgage-performance-trends/
into data/raw/cfpb/ (see src/cfpb.py for the file names).

Writes:
  delinq.csv                  delinq_90 and delinq_30_89, county, monthly, 2008 on
  cfpb_coverage_strict.csv    which host counties the CFPB publishes
  control_county_strict.csv   3 matched comparison counties per covered host county
  match_report_county_strict.csv
  figures/delinq_event_paths_county.png

Matching works like the ZIP step (same state, 15+ miles from every site,
closest 36-month level and trend), but on the 90+ day late rate itself,
and with 3 controls instead of 10: the CFPB covers only ~500 counties, so
most states have just a handful of possible comparison counties.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import cfpb, config  # noqa: E402
from src.figures_matching import event_paths  # noqa: E402
from src.io_utils import save_long  # noqa: E402
from src.matching import balance_table, match_controls  # noqa: E402
from src.panel import build_panel  # noqa: E402
from src.plotting import save  # noqa: E402
from src.treatment import read_treated  # noqa: E402

CONTROLS_PER_COUNTY = 3


def main() -> int:
    try:
        long = cfpb.load()
    except FileNotFoundError as e:
        print(e)
        return 1
    out = save_long(long, "delinq")
    print(f"CFPB: {long.geo_id.nunique()} counties, {long.month.min():%Y-%m} to "
          f"{long.month.max():%Y-%m} -> {out.name}")

    try:
        treated = read_treated("strict", "county")
        cand = pd.read_csv(config.PROCESSED / "control_candidates_county.csv",
                           dtype={"county_fips": str})
    except FileNotFoundError:
        print("Run `python scripts/build_treatment.py` for the coverage and matching step.")
        return 0

    cov = cfpb.coverage(long, treated)
    cov.to_csv(config.PROCESSED / "cfpb_coverage_strict.csv", index=False, date_format="%Y-%m-%d")
    usable = cov[cov.covered & (cov.months_after_ai >= 0)]
    print(f"\nStrict host counties the CFPB publishes: {cov.covered.sum()} of {len(cov)}; "
          f"with at least one month after AI: {len(usable)}")
    for r in cov[~cov.covered].itertuples():
        print(f"  not published (too few mortgages in the CFPB sample): {r.geo_id} {r.state}")
    for r in cov[cov.covered & (cov.months_after_ai < 0)].itertuples():
        print(f"  AI starts after the data ends ({r.treat_month:%Y-%m}): {r.geo_id} {r.state}")

    d90 = long[long.variable == "delinq_90"]
    cand = cand[cand.county_fips.isin(set(d90.geo_id))]
    t = treated[treated.geo_id.isin(usable.geo_id)]
    controls, report = match_controls(t, cand, d90, n=CONTROLS_PER_COUNTY, cand_id="county_fips")
    controls.to_csv(config.PROCESSED / "control_county_strict.csv", index=False)
    report.to_csv(config.PROCESSED / "match_report_county_strict.csv", index=False,
                  date_format="%Y-%m-%d")
    print(f"\nMatched {report.matched.sum()} of {len(report)} counties, "
          f"{CONTROLS_PER_COUNTY} controls each")
    for r in report[~report.matched].itertuples():
        print(f"  not matched: {r.match_id} ({r.state}): {r.reason}")
    if report.matched.any():
        bal = balance_table(report, controls).rename(columns={
            "treated_typical_value": "treated_typical_pct_late",
            "controls_typical_value": "controls_typical_pct_late"})
        print(bal.to_string(index=False))
        matched = t[t.geo_id.isin(report.match_id[report.matched])]
        panel = build_panel(d90, matched, controls)
        fig = event_paths(panel, "90+ days late", len(matched), unit="counties",
                          title="Late mortgages in AI host counties: no early rise vs. matched counties",
                          controls_note=f"{CONTROLS_PER_COUNTY} matched per site",
                          min_sites=max(3, len(matched) - 2), points=True)
        print(f"figure: {save(fig, 'delinq_event_paths_county').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
