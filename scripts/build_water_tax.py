"""Hand-collected property tax and water data -> data/processed/, plus a chart.

    python scripts/build_water_tax.py

Reads data/property_tax_rates.csv and data/water_bills.csv (every value has
its official source in the source_url column; the raw downloads are in
data/raw/tax/ and data/raw/water/). Writes:
  proptax.csv          county, monthly: primary tax rate per $100 (step by tax year)
  water.csv            county, monthly: water bill at 5,000 gal (step by rate change)
  water_tax_coverage_strict.csv   what each strict site has, before and after AI
  figures/proptax_event_index.png
  proptax_bill_panel.csv   host + comparison towns, yearly: rate, home value, est. bill
  figures/proptax_bill_event.png
Run scripts/build_tax_controls.py first if data/property_tax_controls.csv is missing
(it needs the raw state files in data/raw/tax/).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config, tax_bill as tb, water_tax as wt  # noqa: E402
from src.figures_water_tax import tax_bill_event, tax_event_index  # noqa: E402
from src.io_utils import load_site_panel, processed_file, read_long, sample, save_long  # noqa: E402
from src.treatment import read_treated  # noqa: E402
from src.plotting import save  # noqa: E402


def main() -> int:
    tax, water = wt.read_tax(), wt.read_water()
    problems = wt.check(tax, water)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        return 1
    panel = load_site_panel()
    strict = sample(panel, "strict")
    print(f"tax rows {len(tax)}, water rows {len(water)} -> "
          f"{save_long(wt.tax_long(tax), 'proptax').name}, "
          f"{save_long(wt.water_long(water, panel), 'water').name}")
    cov = wt.coverage(tax, water, strict)
    cov.to_csv(config.PROCESSED / "water_tax_coverage_strict.csv", index=False, date_format="%Y-%m")
    pd.set_option("display.width", 160)
    print(cov.drop(columns="site_name").to_string(index=False))
    print(f"\nfigure: {save(tax_event_index(tax, strict), 'proptax_event_index').name}")

    if not (tb.CONTROLS_FILE.exists() and processed_file("zhvi").exists()):
        print("Skipping the tax-bill panel: needs data/property_tax_controls.csv and zhvi.csv.")
        return 0
    panel = tb.build(tb.read_controls(), read_long("zhvi"), read_treated("strict", "zip"))
    panel.to_csv(config.PROCESSED / "proptax_bill_panel.csv", index=False)
    print(f"\nTax-bill panel: {panel.site_id.nunique()} sites, {panel.zip.nunique()} towns, "
          f"{len(panel)} town-years -> proptax_bill_panel.csv")
    print(tb.event_means(panel).round(2).to_string(index=False))
    print(f"figure: {save(tax_bill_event(panel), 'proptax_bill_event').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
