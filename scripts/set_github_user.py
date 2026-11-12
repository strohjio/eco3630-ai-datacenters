"""Put your GitHub username into the README and notebook links (run once).

    python scripts/set_github_user.py strohjio

Replaces the placeholder YOUR-GITHUB-USERNAME in README.md and the notebooks,
so the "Open in Colab" buttons and the clone link point to your repo.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# the placeholder, plus the example name in case it was typed in literally
PLACEHOLDERS = ["YOUR-GITHUB-USERNAME", "your-github-username"]
FILES = [ROOT / "README.md", *sorted((ROOT / "notebooks").glob("*.ipynb"))]


def main() -> int:
    if (len(sys.argv) != 2 or not sys.argv[1].strip() or "/" in sys.argv[1]
            or sys.argv[1].lower() == "your-github-username"):
        print(__doc__)
        return 1
    user = sys.argv[1].strip().lstrip("@")
    for f in FILES:
        text = f.read_text(encoding="utf-8")
        n = sum(text.count(ph) for ph in PLACEHOLDERS)
        for ph in PLACEHOLDERS:
            text = text.replace(ph, user)
        if n:
            f.write_text(text, encoding="utf-8")
        print(f"  {f.relative_to(ROOT)}: {n} link(s) updated")
    print(f"\nDone. Links now point to https://github.com/{user}/eco3630-ai-datacenters")
    return 0


if __name__ == "__main__":
    sys.exit(main())
