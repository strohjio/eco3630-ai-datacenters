"""Phase 1: geography for the comparison group.

Builds the pool of places that are allowed to serve as controls. A control
must be in the same state as a treated place, and far enough from every data
center in the panel that it isn't partly treated itself:

* at least CONTROL_BUFFER_MILES (15) from every site with coordinates,
  including non-AI, proposed and under-construction sites; and
* not in any county that hosts a panel site (this also covers the few sites
  without a ZIP, whose exact location is unknown).

ZIP locations come from the `zipcodes` package (USPS data shipped with the
package, so this runs offline). Only active, standard ZIPs are used: PO-box
and single-building ZIPs have no housing market of their own.
"""
from functools import lru_cache

import addfips
import numpy as np
import pandas as pd
import zipcodes

from src import config

EARTH_RADIUS_MILES = 3958.8


def miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles. Works on single numbers or arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


@lru_cache(maxsize=1)
def load_zip_centroids() -> pd.DataFrame:
    """Every active, standard US ZIP with its state, county FIPS and center point."""
    z = pd.DataFrame(zipcodes.list_all())
    z = z[(z.zip_code_type == "STANDARD") & z.active]
    af = addfips.AddFIPS()
    z["county_fips"] = [af.get_county_fips(c, state=s) for c, s in zip(z.county, z.state)]
    z = z.dropna(subset=["county_fips"])
    out = pd.DataFrame({
        "zip": z.zip_code.astype(str),
        "state": z.state,
        "county_fips": z.county_fips.astype(str),
        "lat": z.lat.astype(float),
        "lon": z.long.astype(float),
    })
    return out.drop_duplicates("zip").reset_index(drop=True)


def miles_to_nearest_site(lat, lon, panel: pd.DataFrame) -> np.ndarray:
    """For each point, the distance in miles to the closest panel site."""
    sites = panel.dropna(subset=["zip_lat", "zip_lon"])
    d = miles(np.asarray(lat)[:, None], np.asarray(lon)[:, None],
              sites.zip_lat.to_numpy()[None, :], sites.zip_lon.to_numpy()[None, :])
    return d.min(axis=1)


def candidate_zips(panel: pd.DataFrame, treated: pd.DataFrame,
                   buffer_miles: float = config.CONTROL_BUFFER_MILES) -> pd.DataFrame:
    """ZIPs allowed to serve as controls for the treated ZIPs' states."""
    z = load_zip_centroids()
    z = z[z.state.isin(treated.state.unique())].copy()
    z["miles_to_nearest_site"] = miles_to_nearest_site(z.lat, z.lon, panel)
    host_counties = set(panel.county_fips)
    keep = ((z.miles_to_nearest_site >= buffer_miles)
            & ~z.county_fips.isin(host_counties)
            & ~z.zip.isin(treated.geo_id))
    return z[keep].reset_index(drop=True)


def candidate_counties(panel: pd.DataFrame, treated: pd.DataFrame,
                       buffer_miles: float = config.CONTROL_BUFFER_MILES) -> pd.DataFrame:
    """Counties allowed to serve as controls: same state, no panel site, and
    no part of the county (no ZIP in it) within the buffer of any site."""
    z = load_zip_centroids()
    z = z[z.state.isin(treated.state.unique())].copy()
    z["miles_to_nearest_site"] = miles_to_nearest_site(z.lat, z.lon, panel)
    c = (z.groupby(["county_fips", "state"], as_index=False)
           .agg(n_zips=("zip", "count"), lat=("lat", "mean"), lon=("lon", "mean"),
                miles_to_nearest_site=("miles_to_nearest_site", "min")))
    keep = ((c.miles_to_nearest_site >= buffer_miles)
            & ~c.county_fips.isin(set(panel.county_fips)))
    return c[keep].reset_index(drop=True)


def pool_summary(treated: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """Treated places and available controls, per state."""
    t = treated.groupby("state").size().rename("treated")
    c = candidates.groupby("state").size().rename("candidates")
    out = t.to_frame().join(c, how="left").fillna(0).astype(int)
    out["candidates_per_treated"] = (out.candidates / out.treated).round(0).astype(int)
    return out.reset_index().sort_values("state")
