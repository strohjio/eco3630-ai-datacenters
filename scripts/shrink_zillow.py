"""Shrink a Zillow ZIP-level CSV to the project's states and study years.

Uses only Python's standard library, so it runs before any packages are
installed. Keeps:
  * rows for ZIPs in the states that appear in the site panel, and
  * monthly columns from 2015 onward (the study window starts in 2019;
    the extra years give room for pre-period matching).

Usage (from the repo root):
    python scripts/shrink_zillow.py <path-to-Zillow-csv>

Writes data/raw/<original name without .csv>_study.csv
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "data" / "ai_data_center_site_panel.csv"
FIRST_MONTH = "2015-01"
ID_COLUMNS = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
              "State", "City", "Metro", "CountyName"]


def panel_states() -> set:
    with open(PANEL, newline="", encoding="utf-8") as f:
        return {row["state"] for row in csv.DictReader(f)}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    src = Path(sys.argv[1]).expanduser()
    if not src.exists():
        print(f"File not found: {src}")
        return 1
    out = ROOT / "data" / "raw" / f"{src.stem}_study.csv"
    states = panel_states()

    with open(src, newline="", encoding="utf-8") as fin:
        reader = csv.reader(fin)
        header = next(reader)
        missing = [c for c in ID_COLUMNS if c not in header]
        if missing:
            print(f"Unexpected file layout; missing columns {missing}")
            return 1
        keep = [i for i, c in enumerate(header)
                if c in ID_COLUMNS or (c[:4].isdigit() and c[:7] >= FIRST_MONTH)]
        state_i = header.index("State")
        rows_in = rows_out = 0
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as fout:
            writer = csv.writer(fout)
            writer.writerow([header[i] for i in keep])
            for row in reader:
                rows_in += 1
                if row[state_i] in states:
                    writer.writerow([row[i] for i in keep])
                    rows_out += 1

    months = [header[i] for i in keep if header[i][:4].isdigit()]
    mb = out.stat().st_size / 1e6
    print(f"Kept {rows_out:,} of {rows_in:,} ZIPs in {len(states)} states, "
          f"{months[0]} to {months[-1]} ({len(months)} months)")
    print(f"Saved {out}  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
