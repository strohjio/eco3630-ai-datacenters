"""Project-wide settings: folder paths, study window, and API keys.

Every script imports paths from here instead of typing them, so the project
runs the same way on every teammate's computer.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"              # untouched downloads (not committed to git)
PROCESSED = DATA / "processed"  # cleaned tables in the shared long format
FIGURES = ROOT / "figures"

SITE_PANEL = DATA / "ai_data_center_site_panel.csv"

# ---------------------------------------------------------------- study window
START_MONTH = "2019-01-01"   # first month any dataset keeps
EVENT_WINDOW = (-36, 24)     # months before / after treatment kept in panels
CONTROL_BUFFER_MILES = 15    # control ZIPs must be this far from every site
CONTROLS_PER_SITE = 10       # matched control ZIPs per treated ZIP

# ---------------------------------------------------------------- API keys
load_dotenv(ROOT / ".env")

API_KEYS = {
    "EIA_API_KEY": "https://www.eia.gov/opendata/register.php",
    "CENSUS_API_KEY": "https://api.census.gov/data/key_signup.html",
    "FRED_API_KEY": "https://fred.stlouisfed.org/docs/api/api_key.html",
}


def get_key(name: str) -> str:
    """Return an API key from the .env file, with a clear message if it's missing."""
    if name not in API_KEYS:
        raise KeyError(f"Unknown key {name!r}. Known keys: {sorted(API_KEYS)}")
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise RuntimeError(
            f"{name} is not set. Get a free key at {API_KEYS[name]} and add "
            f"this line to the .env file in the repo root:\n    {name}=your_key_here"
        )
    return value
