"""Phase 2b: EIA electricity files -> data/processed/elec_*.csv.

    python scripts/pull_eia.py

Before running, put these in data/raw/eia/ (all free, no key needed):
  from https://www.eia.gov/electricity/data/eia861m/
    sales_revenue.xlsx                     "Sales and revenue" (all states)
    sales_ult_cust_2019.xlsx ... _2026.xlsx one per year (older years are
                                            under "Archived data"; rename
                                            retail_sales_2019/2020.xlsx)
  from https://www.eia.gov/electricity/data/eia861/
    f8612025.zip -> unzip Service_Territory_2025.xlsx into data/raw/eia/f861_2025/

Writes:
  elec_state.csv     every state, monthly, 2010 on
  elec_utility.csv   every surveyed utility (geo_type 'utility'), 2019 on
  elec_county.csv    customer-weighted residential price per county
  host_utilities_all.csv   every utility serving each strict host county
  ../host_utility_choice.csv  one utility per host county (EDIT BY HAND; never overwritten)
  figures/elec_event_paths_utility.png  host utility vs. same-state utilities
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, eia  # noqa: E402
from src.figures_matching import event_paths  # noqa: E402
from src.io_utils import save_long  # noqa: E402
from src.panel import build_panel  # noqa: E402
from src.plotting import save  # noqa: E402
from src.treatment import read_treated  # noqa: E402

def main() -> int:
    try:
        state = eia.read_state_monthly()
        util = eia.read_utility_monthly()
        territory = eia.read_service_territory()
    except FileNotFoundError as e:
        print(e)
        return 1

    out = save_long(eia.state_long(state), "elec_state")
    print(f"States: {state.state.nunique()} states, {state.month.min():%Y-%m} to "
          f"{state.month.max():%Y-%m} -> {out.name}")
    out = save_long(eia.utility_long(util), "elec_utility")
    print(f"Utilities: {util.utility_key.nunique()} utility-state pairs in the monthly survey, "
          f"{util.month.min():%Y-%m} to {util.month.max():%Y-%m} -> {out.name}")
    county = eia.county_prices(util, territory)
    out = save_long(county, "elec_county")
    print(f"Counties: {county.geo_id.nunique():,} with a residential price -> {out.name}")
    missed = territory.county_fips.isna().sum()
    if missed:
        print(f"  {missed} service-territory rows had a county name addfips could not match "
              f"(states: {', '.join(sorted(territory[territory.county_fips.isna()].state.unique()))})")

    try:
        treated = read_treated("strict", "county")
    except FileNotFoundError:
        print("Run `python scripts/build_treatment.py` for the host-utility step.")
        return 0
    hosts = eia.host_utilities(treated, territory, util)
    hosts.to_csv(config.PROCESSED / "host_utilities_all.csv", index=False, date_format="%Y-%m-%d")
    if not eia.CHOICE_FILE.exists():
        eia.default_choice(hosts, treated).to_csv(eia.CHOICE_FILE, index=False)
        print(f"\nWrote a first draft of {eia.CHOICE_FILE.name}: check each row by hand.")
    choice = eia.read_choice()
    unverified = (~choice.verified.astype(str).str.lower().eq("true")).sum()
    print(f"\nHost utilities ({unverified} of {len(choice)} rows not yet verified):")
    print(choice[["county_fips", "state", "utility_name", "basis"]].to_string(index=False))

    tu = eia.treated_utilities(choice, treated)
    ctrl = eia.utility_controls(util, tu)
    price = util[["utility_key", "month", "residential_price"]].rename(
        columns={"utility_key": "geo_id", "residential_price": "value"}).dropna()
    panel = build_panel(price, tu, ctrl)
    n_ctrl = ctrl.groupby("match_id").size()
    print(f"\n{len(tu)} host utilities, {int(n_ctrl.median())} same-state comparison "
          f"utilities each (median)")
    # Host utilities were already raising prices faster before AI arrived, so
    # the title reports that instead of the post-AI gap (see README).
    fig = event_paths(panel, "Residential price", len(tu), unit="utilities",
                      controls_note="same state", min_sites=min(10, len(tu) - 2),
                      title="Host-utility electricity prices were already rising faster before AI arrived")
    print(f"figure: {save(fig, 'elec_event_paths_utility').name}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
