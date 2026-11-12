"""Comparison towns for the property tax test -> data/property_tax_controls.csv.

    python scripts/build_tax_controls.py

For every strict site with matched control ZIPs, this looks up the SAME kind
of rate for the host town and for each control ZIP's town, in the same
official state file, so treated and controls are measured identically:

  IN  certified total rate of the town's tax district (DLGF)
  IA  consolidated rate of the city's districts (median, excluding farm-land
      and TIF districts) (Iowa Dept. of Management)
  TN  county rate + city rate (county only for unincorporated places)
  TX  city rate + county rate (school districts left out: no reliable
      town-to-school-district key)
  OK  total mills of the school district named after the town (OSU tables)
  ND  county average mill rate (State Tax Commissioner, Table 8)
  OR  county average tax rate per $1,000 (DOR, Exhibit 6b)

Not covered (no comparison data with years after AI): AZ (file covers only
Maricopa County; controls are elsewhere), GA (state PDFs after 2023 are
scans), OH (county file only), WI (no year after AI yet), NM (Los Lunas has
no facility ZIP, so no matched controls). Raw files: data/raw/tax/<state>/.

A control town whose name can't be found in the state file is left out and
listed in the printout; nothing is guessed.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import pdfplumber  # noqa: E402
import zipcodes  # noqa: E402

from src import config  # noqa: E402

RAW = config.RAW / "tax"
OUT = config.DATA / "property_tax_controls.csv"
SITE_OF = {"51501": "DC012", "46816": "DC013", "46552": "DC018", "58436": "DC026",
           "74361": "DC040", "97058": "DC042", "38109": "DC050", "76502": "DC053",
           "79601": "DC064"}
HOST = {"51501": ("Council Bluffs", "Pottawattamie"), "46816": ("Fort Wayne", "Allen"),
        "46552": ("New Carlisle", "St. Joseph"), "58436": ("Ellendale", "Dickey"),
        "74361": ("Pryor", "Mayes"), "97058": ("The Dalles", "Wasco"),
        "38109": ("Memphis", "Shelby"), "76502": ("Temple", "Bell"), "79601": ("Abilene", "Taylor")}
SOURCES = {
    "IN": ("Indiana DLGF, Certified Tax Rates by District", "https://www.in.gov/dlgf/reports-and-data/reports"),
    "IA": ("Iowa Dept. of Management, Consolidated Property Tax Rates (dataset 934)",
           "https://catalog.data.gov/dataset/consolidated-property-tax-rates-in-iowa-by-tax-district-and-fiscal-year"),
    "TN": ("Tennessee Comptroller, Property Tax Rates",
           "https://comptroller.tn.gov/office-functions/pa/tax-resources/assessment-information-for-each-county/property-tax-rates.html"),
    "TX": ("Texas Comptroller, Statewide Report of Tax Rates", "https://comptroller.texas.gov/taxes/property-tax/rates/"),
    "OK": ("OSU Extension, Oklahoma Ad Valorem Mill Levies", "https://extension.okstate.edu/"),
    "ND": ("ND State Tax Commissioner, Property Tax Statistical Report, Table 8",
           "https://www.tax.nd.gov/data-reports-and-publications"),
    "OR": ("Oregon DOR, Oregon Property Tax Statistics, Exhibit 6b",
           "https://www.oregon.gov/dor/gov-research/pages/research-property.aspx"),
}


def norm(s: str) -> str:
    s = str(s).upper().replace("SAINT ", "ST ").replace("ST. ", "ST ").replace(".", "")
    return re.sub(r"\s+", " ", s).strip()


def towns() -> pd.DataFrame:
    """Host ZIP + its controls, with town and county names."""
    c = pd.read_csv(config.PROCESSED / "control_zip_strict.csv", dtype=str)
    c = c[c.match_id.isin(SITE_OF)]
    rows = [dict(role="treated", match_id=m, zip=m, state=None, city=h[0], county=h[1])
            for m, h in HOST.items()]
    for r in c.itertuples():
        z = zipcodes.matching(r.geo_id)
        rows.append(dict(role="control", match_id=r.match_id, zip=r.geo_id, state=r.state,
                         city=z[0]["city"] if z else None,
                         county=z[0]["county"].replace(" County", "") if z else None))
    t = pd.DataFrame(rows)
    st = c.drop_duplicates("match_id").set_index("match_id").state
    t["state"] = t.match_id.map(st)
    t["site_id"] = t.match_id.map(SITE_OF)
    return t


# ---------------------------------------------------------------- per state
def indiana(t):
    import addfips
    af = addfips.AddFIPS()
    out = []
    for f in sorted(RAW.glob("IN/IN_20*_rates_by_district.xlsx")):
        y = int(f.name[3:7])
        if y == 2024:            # that file is fund-level: sum funds per district
            d = pd.read_excel(f, dtype=str)
            d.columns = [c.strip().upper() for c in d.columns]
            d["rate"] = pd.to_numeric(d.CERTD_TAX_RATE_PCNT, errors="coerce")
            d = d.groupby(["CNTY_CD", "TAX_DIST_CD", "TAX_DIST_NAME"], as_index=False).rate.sum()
            d.columns = ["co", "dist", "name", "rate"]
        else:
            raw = pd.read_excel(f, header=None, dtype=str)
            hi = next(i for i in range(15) if any("DIST" in str(v).upper() for v in raw.iloc[i]))
            raw.columns = [str(c).strip() for c in raw.iloc[hi]]
            raw = raw.iloc[hi + 1:]
            cols = list(raw.columns)
            co = cols[1] if cols[0].upper().startswith("Y") else cols[0]
            name = [c for c in cols if "NAME" in c.upper() and "DIST" in c.upper()][0]
            dist = [c for c in cols if "DIST" in c.upper() and c != name][0]
            rate = [c for c in cols if "RATE" in c.upper()][0]
            d = pd.DataFrame({"co": raw[co], "dist": raw[dist], "name": raw[name],
                              "rate": pd.to_numeric(raw[rate], errors="coerce")})
        d["co"] = d.co.str.strip().str.zfill(2)
        d["n"] = d.name.map(norm)
        for r in t.itertuples():
            fips = af.get_county_fips(r.county, state="IN")
            co = f"{(int(fips[2:]) + 1) // 2:02d}"
            cand = d[d.co == co]
            if r.city == "Fort Wayne":         # host: the two Adams Twp districts, averaged
                hit = cand[cand.n.str.match(r"FW ADAMS (FWCS|EACS)$")]
            else:
                city = norm(r.city)
                hit = cand[cand.n == city]
                if hit.empty:
                    hit = cand[cand.n.str.startswith(city + " ") | cand.n.str.endswith(" " + city)]
                hit = hit[~hit.n.str.contains("TWP|TOWNSHIP|PTC|FIRE|LIB")] if len(hit) > 1 else hit
            if len(hit):
                out.append(dict(zip=r.zip, tax_year=y, rate_per_100=hit.rate.mean(),
                                matched_as="; ".join(hit.name.str.strip())))
    return pd.DataFrame(out)


def iowa(t):
    d = pd.read_csv(RAW / "IA/IA_consolidated_rates_b.csv", dtype=str)
    d = d[(d.property_type == "U") & ~d.district_name.str.contains(r" AG/|TIF|URBAN RENEWAL|SSMID", na=False)]
    d["rate"] = pd.to_numeric(d.consolidated_rate) / 10
    d["cn"] = d.city_name.map(norm)
    out = []
    for r in t.itertuples():
        g = d[(d.cn == norm(r.city)) & (d.county_name.map(norm) == norm(r.county))]
        for y, gy in g.groupby("fiscal_year"):
            out.append(dict(zip=r.zip, tax_year=int(y), rate_per_100=gy.rate.median(),
                            matched_as=f"median of {gy.district_name.nunique()} city districts"))
    return pd.DataFrame(out)


def tennessee(t):
    d = pd.read_csv(RAW / "TN/TN_tax_rates_all_years.csv", dtype=str)
    d["cn"], d["co"] = d.City.fillna("").map(norm), d.County.map(norm)
    out = []
    for r in t.itertuples():
        g = d[(d.co == norm(r.county)) & (d.cn == norm(r.city))]
        how = "county + city"
        if g.empty:                               # unincorporated: county rate only
            g, how = d[(d.co == norm(r.county)) & (d.cn == "")], "county only (unincorporated)"
        for x in g.itertuples():
            out.append(dict(zip=r.zip, tax_year=int(x.TaxYear), rate_per_100=float(x.Total), matched_as=how))
    return pd.DataFrame(out)


def texas(t):
    out = []
    for f in sorted(RAW.glob("TX/TX_20*_statewide_total.xlsx")):
        y = int(f.name[3:7])
        d = pd.read_excel(f, header=None, dtype=str)
        hi = next(i for i in range(10) if any("TAXING UNIT NAME" in str(v).upper() for v in d.iloc[i]))
        d.columns = [str(c).strip().upper() for c in d.iloc[hi]]
        d = d.iloc[hi + 1:]
        d["rate"] = pd.to_numeric(d[[c for c in d.columns if "RATE" in c][0]], errors="coerce")
        d["n"] = d["TAXING UNIT NAME"].map(norm)
        d = d.drop_duplicates("n")
        county_rates = texas_counties(y)          # some years' statewide list skips counties
        for r in t.itertuples():
            city = d[d.n == norm(r.city)]
            county = d[d.n == norm(r.county) + " COUNTY"]
            crate = county.rate.iloc[0] if len(county) else county_rates.get(norm(r.county))
            if len(city) and crate is not None:
                out.append(dict(zip=r.zip, tax_year=y, rate_per_100=city.rate.iloc[0] + crate,
                                matched_as=f"{r.city} + {r.county} County"))
    return pd.DataFrame(out)


def texas_counties(y) -> dict:
    """County name -> total county rate, from the Comptroller's county file."""
    f = RAW / f"TX/TX_{y}_county.xlsx"
    if not f.exists():
        return {}
    x = pd.ExcelFile(f)
    for s in x.sheet_names:
        d = pd.read_excel(x, sheet_name=s, header=None, dtype=str)
        hits = [i for i in range(min(10, len(d))) if "COUNTY NAME" in [str(v).strip().upper() for v in d.iloc[i]]]
        if not hits:
            continue
        d.columns = [str(c).strip().upper() for c in d.iloc[hits[0]]]
        d = d.iloc[hits[0] + 1:]
        rc = [c for c in d.columns if "TOTAL" in c and "RATE" in c][-1]
        return dict(zip(d["COUNTY NAME"].map(norm), pd.to_numeric(d[rc], errors="coerce")))
    return {}


def oklahoma(t):
    out = []
    for f in sorted(RAW.glob("OK/OK_FY*_mill_levies.pdf")):
        fy = int(f.name[5:9])
        with pdfplumber.open(f) as p:
            pages = [pg.extract_text() or "" for pg in p.pages]
        for r in t.itertuples():
            pat = re.compile(rf"Table \d+\. {re.escape(r.county.upper())} County", re.I)
            text = "\n".join(pg for pg in pages if pat.search(pg))
            hits = [ln for ln in text.split("\n")
                    if re.match(r"^\d{3} \d{3} [ID] \d+ \S+ ", ln) and norm(r.city) in norm(ln)]
            if hits:
                out.append(dict(zip=r.zip, tax_year=fy - 1, rate_per_100=float(hits[0].split()[-1]) / 10,
                                matched_as=" ".join(hits[0].split()[5:-1][:3])))
    return pd.DataFrame(out)


def north_dakota(t):
    out = []
    for f in sorted(RAW.glob("ND/ND_*_stat_report.pdf")):
        y = int(f.name[3:7])
        with pdfplumber.open(f) as p:
            lines = [ln for pg in p.pages for ln in (pg.extract_text() or "").split("\n")]
        avg = {ln.split()[0]: float(ln.split()[-1]) for ln in lines
               if re.match(r"^[A-Z ]+ [\d,.]+ [\d,]+ \d{2,3}\.\d{2}$", ln)}
        for r in t.itertuples():
            k = norm(r.county)
            if k in avg:
                out.append(dict(zip=r.zip, tax_year=y, rate_per_100=avg[k] / 10, matched_as=f"{r.county} County average"))
    return pd.DataFrame(out)


def oregon(t):
    out = []
    for f in sorted(RAW.glob("OR/OR_FY*_stats.pdf")):
        y = int(f.name[5:9]) - 1                  # FY2025 = tax year 2024-25
        with pdfplumber.open(f) as p:
            lines = [ln for pg in p.pages for ln in (pg.extract_text() or "").split("\n")]
        rates = {}
        for ln in lines:
            m = re.match(r"^([A-Z][a-z]+(?: [A-Z][a-z]+)?) (?:[\d,]+ )*\$(\d+\.\d\d) \$(\d+\.\d\d)$", ln)
            if m:
                rates[norm(m.group(1))] = float(m.group(3))
        for r in t.itertuples():
            if norm(r.county) in rates:
                out.append(dict(zip=r.zip, tax_year=y, rate_per_100=rates[norm(r.county)] / 10,
                                matched_as=f"{r.county} County average"))
    return pd.DataFrame(out)


STATES = {"IN": indiana, "IA": iowa, "TN": tennessee, "TX": texas, "OK": oklahoma,
          "ND": north_dakota, "OR": oregon}


def main() -> int:
    t = towns()
    parts = []
    for st, fn in STATES.items():
        sub = t[t.state == st]
        got = fn(sub)
        if got.empty:
            print(f"{st}: nothing found")
            continue
        got = got.merge(sub, on="zip").assign(source=SOURCES[st][0], source_url=SOURCES[st][1])
        parts.append(got)
        missing = sub[~sub.zip.isin(got.zip)]
        print(f"{st}: {got.zip.nunique()} of {len(sub)} places found"
              + (f"; not in the state file: {', '.join(missing.city + ' (' + missing.county + ')')}" if len(missing) else ""))
    out = pd.concat(parts, ignore_index=True)
    out = out[["site_id", "match_id", "role", "zip", "city", "county", "state", "tax_year",
               "rate_per_100", "matched_as", "source", "source_url"]]
    out["rate_per_100"] = out.rate_per_100.round(5)
    out.sort_values(["site_id", "role", "zip", "tax_year"], ascending=[True, False, True, True]).to_csv(OUT, index=False)
    print(f"\n{len(out)} rows -> {OUT.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
