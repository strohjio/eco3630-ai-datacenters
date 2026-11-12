"""Phase 3: turn the Zillow downloads into data/processed/zhvi.csv and zori.csv.

    python scripts/pull_zillow.py

Before running, save the ZIP-level files from https://www.zillow.com/research/data/
into data/raw/ (full files, or the shrunk/split versions; see src/zillow.py).
Then it reports how well the treated ZIPs are covered.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src import config, zillow  # noqa: E402
from src.io_utils import save_long  # noqa: E402

# How much history matching needs before the earliest strict treatment month.
NEEDED_FROM = pd.Timestamp("2021-01-01")


def main() -> int:
    treated_file = config.PROCESSED / "treated_zip_strict.csv"
    treated = (pd.read_csv(treated_file, dtype={"geo_id": str}) if treated_file.exists()
               else None)
    for variable in ("zhvi", "zori"):
        try:
            files = zillow.find_raw_files(variable)
        except FileNotFoundError as e:
            print(f"\n{variable.upper()}: skipped. {e}")
            continue
        long = zillow.load(variable)
        out = save_long(long, variable)
        print(f"\n{variable.upper()}: read {len(files)} file(s), {long.geo_id.nunique():,} ZIPs, "
              f"{long.month.min():%Y-%m} to {long.month.max():%Y-%m} -> {out.name}")
        if treated is not None:
            cov = zillow.coverage(long, treated.geo_id)
            missing = cov[cov.n_months.isna()]
            short = cov[cov.first_month > NEEDED_FROM]
            print(f"  strict treated ZIPs with data: {len(cov) - len(missing)} of {len(cov)}")
            for r in missing.itertuples():
                print(f"    no {variable.upper()} series: {r.geo_id}")
            for r in short.itertuples():
                print(f"    starts late ({r.first_month:%Y-%m}): {r.geo_id}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
