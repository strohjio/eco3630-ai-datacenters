"""Tests for the site panel validator. Run all tests with:  pytest -q"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src.validate import validate_site_panel  # noqa: E402


def _panel():
    return pd.read_csv(config.SITE_PANEL, dtype=str, keep_default_na=False)


def test_committed_panel_is_clean():
    assert validate_site_panel(_panel()) == []


def test_catches_four_digit_zip():
    p = _panel()
    p.loc[0, "zip"] = "2014"
    assert any("bad ZIPs" in x for x in validate_site_panel(p))


def test_catches_status_typo():
    p = _panel()
    p.loc[0, "status"] = "operating"
    assert any("status" in x for x in validate_site_panel(p))


def test_catches_duplicate_site_id():
    p = _panel()
    p.loc[1, "site_id"] = p.loc[0, "site_id"]
    assert any("duplicate site_id" in x for x in validate_site_panel(p))


def test_catches_strict_site_without_treat_month():
    p = _panel()
    i = p.index[p.sample_strict_ai == "True"][0]
    p.loc[i, "treat_month"] = ""
    assert any("missing treat_month" in x for x in validate_site_panel(p))


def test_catches_bad_month_format():
    p = _panel()
    i = p.index[p.treat_month != ""][0]
    p.loc[i, "treat_month"] = "2025-13"
    assert any("YYYY-MM" in x for x in validate_site_panel(p))
