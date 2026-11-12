"""EIA electricity files -> the shared long format.

Three EIA downloads feed this module (save them in data/raw/eia/):

* sales_revenue.xlsx          EIA-861M, every state, every month since 2010:
                              revenue, sales, customers and price by sector.
* sales_ult_cust_<year>.xlsx  EIA-861M, the same numbers for each utility,
                              one file per year (2019 on).
* f861_2025/Service_Territory_2025.xlsx
                              EIA-861 annual: which utilities serve which
                              counties (unzipped from f8612025.zip).

Price is always revenue / sales:  $1,000s x 100,000 / MWh x 1,000 = cents/kWh,
which simplifies to  revenue_thousand_dollars * 100 / sales_mwh.

Why utilities, not just counties: a utility charges the same tariff across
its whole service area, so a host county and a control county served by the
same utility show the same price by construction. The sharpest electricity
test compares the utility that serves a data center with other utilities in
the same state. The county table is still useful for the cost index.
"""
import re
from pathlib import Path

import pandas as pd

from src import config

EIA_DIR = config.RAW / "eia"
SECTORS = ["residential", "commercial", "industrial", "transportation", "total"]

# Column order inside the 861M files after the ID columns (checked 2019-2026).
STATE_MEASURES = ["revenue", "sales", "customers", "price"]   # 4 per sector
UTILITY_MEASURES = ["revenue", "sales", "customers"]          # 3 per sector
STATE_ID_COLS = ["year", "month", "state", "data_status"]
UTILITY_ID_COLS = ["year", "month", "utility_id", "utility_name", "state",
                   "ownership", "data_status"]

# Rows that are not real utilities: EIA's state-level estimate for small
# utilities it does not survey monthly, and rooftop-solar estimates.
NOT_A_UTILITY = {"Behind the Meter"}

# What gets saved to the long tables (variable name -> (sector, measure)).
KEEP = {
    "elec_price_res": ("residential", "price"),
    "elec_price_com": ("commercial", "price"),
    "elec_price_ind": ("industrial", "price"),
    "elec_sales_res_mwh": ("residential", "sales"),
    "elec_sales_com_mwh": ("commercial", "sales"),
    "elec_sales_ind_mwh": ("industrial", "sales"),
    "elec_customers_res": ("residential", "customers"),
}


def _flat_columns(id_cols, measures):
    return id_cols + [f"{s}_{m}" for s in SECTORS for m in measures]


def _numbers(df, cols):
    """EIA writes '.' or blanks for missing; make every value column numeric.

    errors="coerce" turns those (and any other text) into NaN.
    """
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _month(df):
    return pd.to_datetime(dict(year=df.year.astype(int), month=df.month.astype(int), day=1))


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Download {what} from "
            "https://www.eia.gov/electricity/data/eia861m/ (monthly) or "
            "https://www.eia.gov/electricity/data/eia861/ (annual) into data/raw/eia/.")
    return path


def _add_prices(df):
    """Price = revenue * 100 / sales, in cents/kWh (blank when sales are 0)."""
    for s in SECTORS:
        sales = df[f"{s}_sales"].where(df[f"{s}_sales"] > 0)
        price = df[f"{s}_revenue"] * 100 / sales
        df[f"{s}_price"] = price.where(price > 0)   # a 0 price is a filing gap
    return df


def _to_long(wide, geo_col, geo_type):
    parts = []
    for var, (sector, measure) in KEEP.items():
        parts.append(pd.DataFrame({
            "geo_id": wide[geo_col].astype(str), "geo_type": geo_type,
            "month": wide.month, "variable": var, "value": wide[f"{sector}_{measure}"]}))
    return pd.concat(parts, ignore_index=True).dropna(subset=["value"])


# ---------------------------------------------------------------- states
def read_state_monthly(path: Path | None = None) -> pd.DataFrame:
    """Every state and month, wide: revenue/sales/customers/price per sector.

    Price is recomputed from revenue and sales (EIA's own Price column rounds
    to two decimals) so state and utility prices are built the same way.
    """
    path = _require(path or EIA_DIR / "sales_revenue.xlsx", "sales_revenue.xlsx")
    df = pd.read_excel(path, sheet_name="Monthly-States", header=None, skiprows=3)
    df = df.iloc[:, :len(_flat_columns(STATE_ID_COLS, STATE_MEASURES))]
    df.columns = _flat_columns(STATE_ID_COLS, STATE_MEASURES)
    df = df[pd.to_numeric(df.year, errors="coerce").notna()].copy()   # drop footnotes
    df = _numbers(df, [c for c in df.columns if c not in STATE_ID_COLS])
    df["month"] = _month(df)
    df = df[df.state.str.len() == 2]
    return _add_prices(df).reset_index(drop=True)


def state_long(wide: pd.DataFrame) -> pd.DataFrame:
    """State table -> shared long format (geo_type 'state', geo_id 'OH')."""
    return _to_long(wide, "state", "state")


# ---------------------------------------------------------------- utilities
def utility_files(raw_dir: Path = EIA_DIR) -> list[Path]:
    files = sorted(raw_dir.glob("sales_ult_cust_*.xlsx"))
    if not files:
        _require(raw_dir / "sales_ult_cust_2025.xlsx", "the sales_ult_cust_<year>.xlsx files")
    return files


def read_utility_monthly(paths: list[Path] | None = None) -> pd.DataFrame:
    """Every utility, state and month, wide. Drops non-utility rows.

    A utility working in two states has one row per state; utility_key
    ('15470_OH') keeps them apart.
    """
    cols = _flat_columns(UTILITY_ID_COLS, UTILITY_MEASURES)
    frames = []
    for p in paths or utility_files():
        df = pd.read_excel(p, sheet_name=0, header=None, skiprows=3)
        df = df.iloc[:, :len(cols)]
        df.columns = cols
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df[pd.to_numeric(df.year, errors="coerce").notna()].copy()
    df["utility_id"] = pd.to_numeric(df.utility_id, errors="coerce")
    adjustment = df.utility_name.astype(str).str.contains("Adjustment", case=False)
    real_state = df.state.astype(str).str.fullmatch(r"[A-Z]{2}") & (df.state != "US")
    df = df[df.utility_id.gt(0) & df.utility_id.ne(88888) & real_state
            & ~adjustment & ~df.ownership.isin(NOT_A_UTILITY)].copy()   # 88888 = national rooftop-solar estimate
    df = _numbers(df, [c for c in cols if c not in UTILITY_ID_COLS])
    df["utility_id"] = df.utility_id.astype(int).astype(str)
    df["month"] = _month(df)
    df["utility_key"] = df.utility_id + "_" + df.state
    dups = df.duplicated(["utility_key", "month"])
    if dups.any():   # same utility filed twice in a month: add the pieces
        num = [c for c in cols if c not in UTILITY_ID_COLS]
        first = df.groupby(["utility_key", "month"], as_index=False).first()
        sums = df.groupby(["utility_key", "month"], as_index=False)[num].sum(min_count=1)
        df = first.drop(columns=num).merge(sums, on=["utility_key", "month"])
    return _add_prices(df).reset_index(drop=True)


def utility_long(wide: pd.DataFrame) -> pd.DataFrame:
    """Utility table -> shared long format (geo_type 'utility', geo_id '15470_OH')."""
    return _to_long(wide, "utility_key", "utility")


# ---------------------------------------------------------------- service territory
def read_service_territory(path: Path | None = None) -> pd.DataFrame:
    """Utility -> county list with 5-digit county FIPS.

    EIA lists county names, not codes; addfips turns names into codes.
    Names it cannot match are returned with county_fips blank so the
    caller can report them.
    """
    import addfips

    path = _require(path or EIA_DIR / "f861_2025" / "Service_Territory_2025.xlsx",
                    "f8612025.zip (unzip Service_Territory_2025.xlsx)")
    df = pd.read_excel(path, sheet_name="Counties_States", dtype=str)
    df = df.rename(columns={"Utility Number": "utility_id", "Utility Name": "utility_name",
                            "State": "state", "County": "county"})
    af = addfips.AddFIPS()

    def fips(row):
        name = str(row.county)
        # EIA writes "St Clair" and "DeSoto"; Census writes "St. Clair", "De Soto"
        for n in (name, re.sub(r"^St ", "St. ", name), name.replace("DeSoto", "De Soto")):
            try:
                code = af.get_county_fips(n, state=row.state)
            except Exception:   # unknown state code
                code = None
            if code:
                return code
        return None

    df["county_fips"] = df.apply(fips, axis=1)
    df["utility_key"] = df.utility_id.str.strip() + "_" + df.state
    return df[["utility_key", "utility_id", "utility_name", "state", "county",
               "county_fips"]].drop_duplicates()


def county_prices(util: pd.DataFrame, territory: pd.DataFrame,
                  variable: str = "elec_price_res") -> pd.DataFrame:
    """Monthly price for each county: average over the utilities serving it.

    Each utility is weighted by its residential customers in that state, so
    a large utility counts more than a small co-op. This is an approximation:
    EIA does not split a utility's customers by county.

    util: the wide utility table from read_utility_monthly.
    Returns the shared long format (geo_type 'county') with variable name
    `<variable>_cty` so it is never confused with the utility-level series.
    """
    sector, measure = KEEP[variable]
    u = util[["utility_key", "month", f"{sector}_{measure}", "residential_customers"]]
    u = u.rename(columns={f"{sector}_{measure}": "v", "residential_customers": "w"})
    m = territory.dropna(subset=["county_fips"])[["utility_key", "county_fips"]].merge(u)
    m = m.dropna(subset=["v"])
    m["w"] = m.w.fillna(0).clip(lower=0) + 1e-9   # utilities with 0 customers barely count
    out = (m.assign(vw=m.v * m.w).groupby(["county_fips", "month"])
             .agg(vw=("vw", "sum"), w=("w", "sum")).reset_index())
    return pd.DataFrame({"geo_id": out.county_fips, "geo_type": "county", "month": out.month,
                         "variable": f"{variable}_cty", "value": out.vw / out.w})


def host_utilities(treated_counties: pd.DataFrame, territory: pd.DataFrame,
                   util: pd.DataFrame) -> pd.DataFrame:
    """For each treated county, the utilities serving it, largest first.

    The largest (by residential customers in the latest month) is the best
    guess for the data center's utility, but check it by hand: big sites
    often sign with a specific utility or co-op. The site panel's notes and
    the utility's own announcements say which.
    """
    latest = (util.sort_values("month").groupby("utility_key").tail(1)
                  [["utility_key", "utility_name", "residential_customers"]])
    t = treated_counties[["geo_id", "state", "treat_month"]].rename(columns={"geo_id": "county_fips"})
    m = t.merge(territory[["utility_key", "county_fips"]], on="county_fips", how="left")
    m = m.merge(latest, on="utility_key", how="left")
    m["in_monthly_survey"] = m.utility_name.notna()
    m = m.sort_values(["county_fips", "residential_customers"], ascending=[True, False])
    m["rank"] = m.groupby("county_fips").cumcount() + 1
    return m.reset_index(drop=True)


# ---------------------------------------------------------------- utility design
CHOICE_FILE = config.DATA / "host_utility_choice.csv"
MIN_CONTROL_CUSTOMERS = 1_000   # skip tiny utilities: their prices jump around


def default_choice(hosts: pd.DataFrame, treated_counties: pd.DataFrame) -> pd.DataFrame:
    """First draft of data/host_utility_choice.csv: largest surveyed utility per county.

    Edit the CSV by hand once you know a site's real utility (set
    verified=True and write the source in basis). The pull script never
    overwrites an existing file.
    """
    top = hosts[hosts.in_monthly_survey].sort_values("rank").groupby("county_fips").head(1)
    names = treated_counties[["geo_id", "state", "site_names"]].rename(columns={"geo_id": "county_fips"})
    out = names.merge(top[["county_fips", "utility_key", "utility_name"]],
                      on="county_fips", how="left")
    out["basis"] = out.utility_key.map(
        lambda k: "auto: largest residential utility in the county" if isinstance(k, str)
        else "none in EIA monthly survey (Texas retail choice or small utilities only)")
    out["verified"] = False
    return out[["county_fips", "state", "site_names", "utility_key", "utility_name",
                "basis", "verified"]]


def read_choice(path: Path = CHOICE_FILE) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"county_fips": str, "utility_key": str})


def treated_utilities(choice: pd.DataFrame, treated_counties: pd.DataFrame) -> pd.DataFrame:
    """One row per host utility, dated by its earliest AI site.

    Two host counties can share a utility (both Ohio sites use Ohio Power);
    like shared ZIPs, the utility counts once, from the earlier month.
    """
    c = choice.dropna(subset=["utility_key"]).merge(
        treated_counties[["geo_id", "treat_month"]].rename(columns={"geo_id": "county_fips"}))
    return (c.sort_values("treat_month").groupby("utility_key", as_index=False)
              .agg(state=("state", "first"), treat_month=("treat_month", "first"),
                   utility_name=("utility_name", "first"),
                   host_counties=("county_fips", lambda s: ";".join(s))))\
             .rename(columns={"utility_key": "geo_id"})


def utility_controls(util: pd.DataFrame, treated_utils: pd.DataFrame,
                     exclude: set[str] = frozenset(),
                     min_customers: int = MIN_CONTROL_CUSTOMERS) -> pd.DataFrame:
    """Every other surveyed utility in the same state is a control.

    Utilities with fewer than `min_customers` residential customers, and any
    utility in `exclude` (hosts of other sites), are left out. With only a
    few utilities per state there is nothing to match on, so all of them are
    kept; the regression's fixed effects do the rest.
    """
    size = util.groupby("utility_key").residential_customers.median()
    big = set(size[size >= min_customers].index)
    pool = util[["utility_key", "state"]].drop_duplicates()
    pool = pool[pool.utility_key.isin(big) & ~pool.utility_key.isin(set(treated_utils.geo_id) | set(exclude))]
    out = treated_utils[["geo_id", "state"]].rename(columns={"geo_id": "match_id"}).merge(pool, on="state")
    return out.rename(columns={"utility_key": "geo_id"})[["geo_id", "match_id", "state"]]
