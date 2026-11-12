"""Check every processed dataset before the regressions.

    python scripts/audit_data.py

For each table in data/processed/ it checks: the shared long format, duplicate
rows, missing or impossible values (each variable has a plausible range), the
date range, gaps inside each host place's monthly series, and how many host
places the table covers. Writes data/processed/audit_report.csv and prints
anything that needs attention. Exit code 1 if a hard error is found.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config, water_tax  # noqa: E402
from src.io_utils import check_long_format, processed_file, read_long  # noqa: E402
from src.treatment import read_treated  # noqa: E402

# Plausible range for each variable: values outside are flagged.
RANGES = {
    "zhvi": (10_000, 10_000_000), "zori": (200, 20_000),
    "elec_price_res": (2, 80), "elec_price_com": (2, 80), "elec_price_ind": (1, 80),
    "elec_price_res_cty": (2, 80), "elec_sales_res_mwh": (0, 5e8), "elec_sales_com_mwh": (0, 5e8),
    "elec_sales_ind_mwh": (0, 5e8), "elec_customers_res": (0, 2e7),
    "delinq_90": (0, 30), "delinq_30_89": (0, 30),
    "proptax_rate_per100": (0.01, 30), "water_bill_5k": (5, 300),
    "pop": (1, 2e7), "pop_growth_pct": (-30, 30), "med_hh_income": (10_000, 300_000),
    "poverty_rate": (0, 70), "unemp_rate": (0, 40), "unemp_rate_m": (0, 40),
    "labor_force": (1, 1e7), "cpi": (10, 1000), "mortgage30": (1, 25),
}
MONTHLY = {"zhvi", "zori", "delinq_90", "delinq_30_89", "elec_price_res", "unemp_rate_m",
           "water_bill_5k", "cpi", "mortgage30"}
# Which host places each table should cover: (treated level, how to read geo ids)
HOSTS = {"zhvi": "zip", "zori": "zip", "delinq": "county", "proptax": "county",
         "water": "county", "controls_county": "county", "elec_county": "county"}


def internal_gaps(s: pd.Series) -> int:
    """Missing months between a series' first and last month."""
    m = pd.DatetimeIndex(s.sort_values().unique())
    if len(m) < 2:
        return 0
    return len(pd.date_range(m[0], m[-1], freq="MS")) - len(m)


def audit_table(name: str, hosts: dict) -> list[dict]:
    df = read_long(name)
    rows, problems = [], []
    try:
        check_long_format(df)
    except ValueError as e:
        problems.append(f"FORMAT: {e}")
    dup = df.duplicated(["geo_id", "geo_type", "month", "variable"]).sum()
    if dup:
        problems.append(f"ERROR: {dup} duplicate rows")
    for var, g in df.groupby("variable"):
        v = g.value
        bad_num = (~np.isfinite(v)).sum()
        lo, hi = RANGES.get(var, (-np.inf, np.inf))
        out = ((v < lo) | (v > hi)).sum()
        r = dict(table=name, variable=var, rows=len(g), places=g.geo_id.nunique(),
                 first=g.month.min().date(), last=g.month.max().date(),
                 not_finite=int(bad_num), out_of_range=int(out),
                 min=round(float(v.min()), 3), max=round(float(v.max()), 3))
        level = HOSTS.get(name)
        if level:
            ids = hosts[level]
            have = set(g.geo_id)
            r["host_places_covered"] = f"{len(ids & have)}/{len(ids)}"
            if var in MONTHLY:
                gaps = g[g.geo_id.isin(ids)].groupby("geo_id").month.apply(internal_gaps)
                r["host_series_with_gaps"] = int((gaps > 0).sum())
        if bad_num:
            problems.append(f"ERROR: {var}: {bad_num} non-numeric/infinite values")
        if out:
            problems.append(f"CHECK: {var}: {out} values outside {lo}-{hi}")
        rows.append(r)
    for p in problems:
        rows.append(dict(table=name, variable="!", note=p))
    return rows


def main() -> int:
    hosts = {"zip": set(read_treated("strict", "zip").geo_id),
             "county": set(read_treated("strict", "county").geo_id)}
    tables = ["zhvi", "zori", "elec_state", "elec_utility", "elec_county", "delinq",
              "proptax", "water", "controls_county", "controls_nation"]
    rows = []
    for t in tables:
        if processed_file(t).exists():
            rows += audit_table(t, hosts)
        else:
            rows.append(dict(table=t, variable="!", note="MISSING: run its pull script"))
    # hand-collected sources
    issues = water_tax.check(water_tax.read_tax(), water_tax.read_water())
    rows += [dict(table="hand_collected", variable="!", note=f"ERROR: {i}") for i in issues]
    panel = pd.read_csv(config.PROCESSED / "proptax_bill_panel.csv", dtype={"zip": str})
    dup = panel.duplicated(["site_id", "zip", "tax_year"]).sum()
    rows.append(dict(table="proptax_bill_panel", variable="log_tax_index", rows=len(panel),
                     places=panel.zip.nunique(), not_finite=int((~np.isfinite(panel.log_tax_index)).sum()),
                     note=f"ERROR: {dup} duplicate town-years" if dup else ""))

    rep = pd.DataFrame(rows)
    rep.to_csv(config.PROCESSED / "audit_report.csv", index=False)
    pd.set_option("display.width", 200)
    show = rep[rep.variable != "!"].drop(columns=[c for c in ("note",) if c in rep])
    print(show.astype(object).where(show.notna(), "").to_string(index=False))
    notes = rep[rep.variable == "!"]
    print("\nNeeds attention:" if len(notes) else "\nNo problems found.")
    for r in notes.itertuples():
        print(f"  [{r.table}] {r.note}")
    return 1 if notes.note.str.startswith(("ERROR", "FORMAT", "MISSING")).any() else 0


if __name__ == "__main__":
    sys.exit(main())
