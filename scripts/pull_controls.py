"""Control variables -> data/processed/controls_county.csv, controls_nation.csv.

    python scripts/pull_controls.py

Put these in data/raw/controls/ first (all free, no key):
  Census population estimates, county totals:
    https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/counties/totals/co-est2019-alldata.csv
    https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv
  Census SAIPE income and poverty, one file per year (est19all.xls ... est24all.xls):
    https://www2.census.gov/programs-surveys/saipe/datasets/<year>/<year>-state-and-county/
    save as saipe_est19all.xls, ...
  BLS LAUS county unemployment: https://www.bls.gov/lau/tables.htm
    laucnty18.xlsx ... laucnty25.xlsx (annual) and laucntycur14.xlsx (last 14 months, unzip)
  FRED: https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL  -> fred_CPIAUCSL.csv
        https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US -> fred_MORTGAGE30US.csv

Also prints a balance table: host counties vs their comparison counties on
the controls in 2023 (before almost every AI start). Big gaps there are worth
a sentence in the report, and are why the regressions add these controls.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config, controls as ct  # noqa: E402
from src.io_utils import load_site_panel, sample, save_long  # noqa: E402


def comparison_counties() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Host counties and the counties of their matched control ZIPs."""
    strict = sample(load_site_panel(), "strict")
    host_of_zip = strict.dropna(subset=["zip"]).drop_duplicates("zip").set_index("zip").county_fips
    ctrl = pd.read_csv(config.PROCESSED / "control_zip_strict.csv", dtype=str)
    cand = pd.read_csv(config.PROCESSED / "control_candidates_zip.csv", dtype=str)
    ctrl["geo_id"] = ctrl.geo_id.map(cand.drop_duplicates("zip").set_index("zip").county_fips)
    ctrl["match_id"] = ctrl.match_id.map(host_of_zip)
    ctrl = ctrl.dropna(subset=["geo_id", "match_id"]).drop_duplicates(["geo_id", "match_id"])
    hosts = pd.DataFrame({"geo_id": sorted(ctrl.match_id.unique())})
    return hosts, ctrl[["geo_id", "match_id"]]


def main() -> int:
    try:
        data = ct.load_all()
    except (FileNotFoundError, StopIteration) as e:
        print(f"Missing or unexpected raw file in data/raw/controls/: {e}")
        return 1
    county, nation = data["county"], data["nation"]
    print(f"county controls: {county.geo_id.nunique():,} counties -> "
          f"{save_long(county, 'controls_county').name}")
    print(f"national series: {', '.join(nation.variable.unique())} -> "
          f"{save_long(nation, 'controls_nation').name}")
    print(county.groupby("variable").month.agg(["min", "max"]).astype(str).to_string())

    if (config.PROCESSED / "control_zip_strict.csv").exists():
        hosts, ctrl = comparison_counties()
        bal = ct.balance(county, hosts, ctrl, year=2023)
        bal.to_csv(config.PROCESSED / "controls_balance_2023.csv")
        print(f"\nBalance in 2023: {len(hosts)} host counties vs their comparison counties")
        print(bal.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
