"""Split a large CSV into smaller pieces, each with the header row.

Standard library only. Usage (from the repo root):
    python scripts/split_csv.py <path-to-csv> [number_of_parts]   (default 4)

Writes <name>_part1.csv ... <name>_partN.csv next to the original.
Rejoin with pandas: pd.concat(pd.read_csv(p) for p in sorted(parts)).
"""
import csv
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 1
    src = Path(sys.argv[1]).expanduser()
    parts = int(sys.argv[2]) if len(sys.argv) == 3 else 4
    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    size = -(-len(rows) // parts)  # ceiling division
    for k in range(parts):
        chunk = rows[k * size:(k + 1) * size]
        out = src.with_name(f"{src.stem}_part{k + 1}.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(chunk)
        print(f"{out.name}: {len(chunk):,} rows, {out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
