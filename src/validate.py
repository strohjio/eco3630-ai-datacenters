"""Checks that the site panel is internally consistent.

Run this after anyone edits ai_data_center_site_panel.csv by hand:
    python scripts/check_setup.py
A mistake caught here (a 4-digit ZIP, a typo in a status) is a mistake that
doesn't silently break a join three weeks later.
"""
import re

import pandas as pd

REQUIRED = [
    "site_id", "site_name", "operator", "operator_parent", "ai_tier",
    "ai_evidence_level", "status", "sample_strict_ai", "sample_broad_ai",
    "campus_group", "announce_year", "operational_year", "anchor_year",
    "anchor_type", "ai_era_start_year", "treat_month", "treat_month_basis",
    "announce_month", "street_address", "city", "county", "state",
    "county_fips", "zip", "zip_basis", "zip_county_check", "zip_lat", "zip_lon",
    "scale", "scale_mw", "ai_evidence", "ai_evidence_url", "primary_source_url",
    "year_source_url", "address_source_url", "split_from", "verification", "notes",
]

ALLOWED = {
    "ai_tier": {"AI-purpose-built", "Hyperscale-AI-documented",
                "Colocation-AI-tenancy-unconfirmed", "Unclear"},
    "ai_evidence_level": {"purpose-built", "facility", "region/state", "fleet", "none"},
    "status": {"Operating", "Under construction", "Announced/Permitted",
               "Proposed", "Cancelled/Withdrawn"},
    "zip_basis": {"facility address", "town-level (no facility address published)",
                  "none", "not yet verified"},
    "anchor_type": {"opening", "announcement", "none"},
    "sample_strict_ai": {"True", "False"},
    "sample_broad_ai": {"True", "False"},
}


def _year_ok(v: str) -> bool:
    return v == "" or (v.isdigit() and 2000 <= int(v) <= 2035)


def _month_ok(v: str) -> bool:
    return v == "" or re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", v) is not None


def validate_site_panel(df: pd.DataFrame, raise_on_error: bool = False) -> list:
    """Return a list of problems (empty list = clean).

    `df` must be read with dtype=str and keep_default_na=False, i.e. exactly
    as stored in the CSV. With raise_on_error=True, any problem raises.
    """
    problems = []
    add = problems.append

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        add(f"missing columns: {missing}")
        if raise_on_error:
            raise ValueError("Site panel problems:\n  - " + "\n  - ".join(problems))
        return problems

    # IDs
    if df.site_id.duplicated().any():
        add(f"duplicate site_id: {df.site_id[df.site_id.duplicated()].tolist()}")
    if not df.site_id.str.fullmatch(r"DC\d{3}").all():
        add("site_id must look like DC001")

    # categories
    for col, ok in ALLOWED.items():
        bad = sorted(set(df[col]) - ok)
        if bad:
            add(f"{col} has unexpected values {bad}")

    # geography
    if not df.state.str.fullmatch(r"[A-Z]{2}").all():
        add(f"bad state codes: {df.state[~df.state.str.fullmatch(r'[A-Z]{2}')].tolist()}")
    bad_fips = df[~df.county_fips.str.fullmatch(r"\d{5}")]
    if len(bad_fips):
        add(f"county_fips must be 5 digits: {bad_fips.site_id.tolist()}")
    zip_ok = df.zip.str.fullmatch(r"\d{5}") | df.zip.isin(["none", "not yet verified"])
    if not zip_ok.all():
        add(f"bad ZIPs: {df.loc[~zip_ok, ['site_id', 'zip']].values.tolist()}")
    no_zip = ~df.zip.str.fullmatch(r"\d{5}")
    if (no_zip & ~df.zip_basis.isin(["none", "not yet verified"])).any():
        add("rows without a ZIP must have zip_basis 'none' or 'not yet verified'")

    # dates
    for col in ("announce_year", "operational_year", "anchor_year", "ai_era_start_year"):
        bad = df.loc[~df[col].map(_year_ok), "site_id"].tolist()
        if bad:
            add(f"{col} not a year 2000-2035: {bad}")
    for col in ("treat_month", "announce_month"):
        bad = df.loc[~df[col].map(_month_ok), "site_id"].tolist()
        if bad:
            add(f"{col} must be YYYY-MM: {bad}")
    if ((df.status == "Operating") & (df.operational_year == "")
            & (df.verification.str.startswith("re-verified"))).any():
        add("verified Operating rows should have an operational_year")

    # samples
    strict, broad = df.sample_strict_ai == "True", df.sample_broad_ai == "True"
    if (strict & ~broad).any():
        add("every strict-sample site must also be in the broad sample")
    for name, mask in (("strict", strict), ("broad", broad)):
        rows = df[mask]
        if (rows.status != "Operating").any():
            add(f"{name} sample includes non-operating sites")
        if (rows.operational_year == "").any():
            add(f"{name} sample includes sites with no operational_year")
        if (~rows.zip.str.fullmatch(r"\d{5}")).any():
            add(f"{name} sample includes sites with no ZIP")
    if (strict & (df.treat_month == "")).any():
        add(f"strict sites missing treat_month: {df.site_id[strict & (df.treat_month == '')].tolist()}")
    has_t = df.treat_month != ""
    if (df.loc[has_t, "treat_month"].str[:4] != df.loc[has_t, "ai_era_start_year"]).any():
        add("treat_month year must match ai_era_start_year")

    # campus groups need at least two members
    sizes = df.loc[df.campus_group != "", "campus_group"].value_counts()
    if (sizes < 2).any():
        add(f"campus groups with a single site: {sizes[sizes < 2].index.tolist()}")

    if problems and raise_on_error:
        raise ValueError("Site panel problems:\n  - " + "\n  - ".join(problems))
    return problems
