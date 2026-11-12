"""Control variables -> the shared long format.

County-level (geo_type 'county'), yearly values stored at January of the year:
  pop                 Census population estimates (PEP), July 1 of each year, 2010-2024
  pop_growth_pct      % change in population from the year before
  med_hh_income       Census SAIPE median household income, 2019-2024 (nominal $)
  poverty_rate        Census SAIPE % of people in poverty, 2019-2024
  unemp_rate          BLS LAUS annual unemployment rate, 2018-2025
                      (2025 is an 11-month average: October 2025 was never
                      collected because of the 2025 federal funding lapse)
  labor_force         BLS LAUS annual labor force, 2018-2025
County-level, monthly:
  unemp_rate_m        BLS LAUS monthly rate, not seasonally adjusted, last 14 months
National (geo_type 'nation', geo_id 'US'), monthly:
  cpi                 FRED CPIAUCSL (1982-84 = 100), seasonally adjusted
  mortgage30          FRED MORTGAGE30US, 30-year fixed rate, monthly average of weekly

Why the Census API isn't used: it now requires a key. These are the same
Census and BLS numbers from their published files, which need none.
Raw files live in data/raw/controls/ (see scripts/pull_controls.py).
"""
import re

import pandas as pd

from src import config
from src.io_utils import LONG_COLUMNS

RAW = config.RAW / "controls"


def _long(df, geo_type, variable, value_col="value"):
    out = df[["geo_id", "month", value_col]].rename(columns={value_col: "value"})
    out["geo_type"], out["variable"] = geo_type, variable
    out = out.dropna(subset=["value"])
    return out[LONG_COLUMNS]


def _jan(years):
    return pd.to_datetime(pd.Series(years).astype(int).astype(str) + "-01-01").values


# ---------------------------------------------------------------- population
def population(raw=RAW) -> pd.DataFrame:
    frames = []
    for f, years in (("co-est2019-alldata.csv", range(2010, 2020)),
                     ("co-est2024-alldata.csv", range(2020, 2025))):
        d = pd.read_csv(raw / f, encoding="latin1", dtype={"STATE": str, "COUNTY": str})
        d = d[d.SUMLEV == 50].copy()
        d["geo_id"] = d.STATE.str.zfill(2) + d.COUNTY.str.zfill(3)
        for y in years:
            frames.append(pd.DataFrame({"geo_id": d.geo_id, "year": y, "value": d[f"POPESTIMATE{y}"]}))
    p = pd.concat(frames, ignore_index=True).sort_values(["geo_id", "year"])
    p["growth"] = 100 * p.groupby("geo_id").value.pct_change(fill_method=None)
    p["month"] = _jan(p.year)
    return pd.concat([_long(p, "county", "pop"),
                      _long(p, "county", "pop_growth_pct", "growth")], ignore_index=True)


# ---------------------------------------------------------------- SAIPE
def saipe(raw=RAW) -> pd.DataFrame:
    """Median household income and poverty rate by county."""
    frames = []
    for f in sorted(raw.glob("saipe_est*all.xls")):
        y = 2000 + int(re.search(r"est(\d\d)all", f.name).group(1))
        d = pd.read_excel(f, header=None, dtype=str)
        hi = next(i for i in range(10) if "State FIPS Code" in [str(v).strip() for v in d.iloc[i]])
        d.columns = [str(c).strip() for c in d.iloc[hi]]
        d = d.iloc[hi + 1:]
        d = d[d["County FIPS Code"].fillna("0").astype(int) > 0]        # drop state/US rows
        geo = d["State FIPS Code"].str.zfill(2) + d["County FIPS Code"].str.zfill(3)
        inc = [c for c in d.columns if c.startswith("Median Household Income")][0]
        pov = [c for c in d.columns if c.startswith("Poverty Percent, All Ages")][0]
        frames.append(pd.DataFrame({"geo_id": geo, "year": y,
                                    "med_hh_income": pd.to_numeric(d[inc], errors="coerce"),
                                    "poverty_rate": pd.to_numeric(d[pov], errors="coerce")}))
    s = pd.concat(frames, ignore_index=True)
    s["month"] = _jan(s.year)
    return pd.concat([_long(s, "county", "med_hh_income", "med_hh_income"),
                      _long(s, "county", "poverty_rate", "poverty_rate")], ignore_index=True)


# ---------------------------------------------------------------- BLS LAUS
def _laus_frame(path, header_word):
    d = pd.read_excel(path, header=None, dtype=str)
    hi = next(i for i in range(10) if header_word in [str(v).strip() for v in d.iloc[i]])
    d.columns = [str(c).strip().replace("-", "").replace("\n", " ") for c in d.iloc[hi]]
    d = d.iloc[hi + 1:]
    d = d[d["State FIPS Code"].fillna("").str.match(r"^\d+$")]
    d["geo_id"] = d["State FIPS Code"].str.zfill(2) + d["County FIPS Code"].str.zfill(3)
    rate = [c for c in d.columns if c.startswith("Unemploy")][-1]
    d["rate"] = pd.to_numeric(d[rate], errors="coerce")     # '–' (not collected) -> blank
    d["lf"] = pd.to_numeric(d["Labor Force"], errors="coerce")
    return d


def laus_annual(raw=RAW) -> pd.DataFrame:
    frames = []
    for f in sorted(raw.glob("laucnty[0-9][0-9].xlsx")):
        d = _laus_frame(f, "Year")
        frames.append(d.assign(month=_jan(d.Year.str.strip())))
    d = pd.concat(frames, ignore_index=True)
    return pd.concat([_long(d, "county", "unemp_rate", "rate"),
                      _long(d, "county", "labor_force", "lf")], ignore_index=True)


def laus_monthly(raw=RAW) -> pd.DataFrame:
    d = _laus_frame(raw / "laucntycur14.xlsx", "Period")
    d["month"] = pd.to_datetime(d.Period.str.replace(r"\s*p$", "", regex=True), format="%b-%y")
    return _long(d, "county", "unemp_rate_m", "rate")


# ---------------------------------------------------------------- FRED
def fred(series: str, raw=RAW) -> pd.DataFrame:
    """National monthly series (weekly series averaged by month)."""
    d = pd.read_csv(raw / f"fred_{series}.csv")
    d.columns = ["date", "value"]
    d["value"] = pd.to_numeric(d.value, errors="coerce")
    d["month"] = pd.to_datetime(d.date).dt.to_period("M").dt.to_timestamp()
    d = d.groupby("month", as_index=False).value.mean().assign(geo_id="US")
    name = {"CPIAUCSL": "cpi", "MORTGAGE30US": "mortgage30"}[series]
    return _long(d, "nation", name)


def load_all(raw=RAW) -> dict[str, pd.DataFrame]:
    county = pd.concat([population(raw), saipe(raw), laus_annual(raw), laus_monthly(raw)],
                       ignore_index=True)
    nation = pd.concat([fred("CPIAUCSL", raw), fred("MORTGAGE30US", raw)], ignore_index=True)
    return {"county": county, "nation": nation}


# ---------------------------------------------------------------- real dollars
def deflate(long: pd.DataFrame, cpi: pd.DataFrame, base: str = "2025-01-01") -> pd.DataFrame:
    """Add `value_real`: value in `base`-month dollars (team rule 4).

    Monthly values use that month's CPI; yearly values stored at January use
    that year's average CPI.
    """
    c = cpi.set_index("month").value
    yearly = c.groupby(c.index.year).mean()
    out = long.copy()
    by_month = out.month.map(c)
    by_year = out.month.dt.year.map(yearly)
    out["value_real"] = out.value * c[pd.Timestamp(base)] / by_month.fillna(by_year)
    return out


def balance(county: pd.DataFrame, treated: pd.DataFrame, controls: pd.DataFrame,
            year: int = 2023) -> pd.DataFrame:
    """Host vs comparison counties on the controls, in one pre-AI year.

    treated: host counties (geo_id); controls: comparison counties with a
    match_id pointing at their host county. Each host's comparisons are
    averaged first, so every host counts once.
    """
    wide = (county[county.month == pd.Timestamp(f"{year}-01-01")]
            .pivot_table(index="geo_id", columns="variable", values="value"))
    cols = [c for c in ("pop", "pop_growth_pct", "med_hh_income", "poverty_rate", "unemp_rate")
            if c in wide.columns]
    h = wide.reindex(treated.geo_id)[cols]
    c = controls.join(wide[cols], on="geo_id").groupby("match_id")[cols].mean()
    out = pd.DataFrame({"host_counties": h.mean(), "comparison_counties": c.mean()})
    out["difference"] = out.host_counties - out.comparison_counties
    return out.round(2)
