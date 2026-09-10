"""One-off helper: get hourly PVGIS solar irradiance for the Finner Camp
location and cache it locally as pvgis_2024_solar.csv, so
j_seasonal_weather_rating.py never has to hit the network to run.

    python fetch_pvgis_2024_solar.py
    python fetch_pvgis_2024_solar.py --lat 54.4939 --lon -8.2431 --out pvgis_2024_solar.csv
    python fetch_pvgis_2024_solar.py --from-csv Timeseries_54.487_8.222_SA3_0deg_0deg_2023_2023.csv

PVGIS DOES NOT YET HAVE 2024 DATA - THIS SCRIPT USES 2023 AS A CALENDAR-
MATCHED PROXY, AND SAYS SO EVERYWHERE
------------------------------------------------------------------------
As of when this project was built, PVGIS's PVGIS-SARAH3 radiation database
(the one it auto-selects for this Irish coastal location) only extends
through calendar year 2023 - requesting startyear=2024 has nothing to
return. SOURCE_YEAR below (2023) is therefore the most recent full year
PVGIS actually has, and TARGET_YEAR (2024, matching the rest of this
project's methodology - see j_seasonal_weather_rating.py's docstring) is
what the output file is labelled as. remap_calendar_year() below maps each
SOURCE_YEAR hour onto the TARGET_YEAR calendar date with the SAME month,
day and hour (not a straight "+1 year" or row-shift - see that function's
docstring for why, and for the one date that has no direct match: 2024 is
a leap year and 2023 is not, so 2024-02-29 has no 2023-02-29 to copy from).

WHY THIS IS A DEFENSIBLE PROXY, NOT SOMETHING INVENTED: unlike wind speed
or temperature, solar irradiance at a given latitude and calendar date is
overwhelmingly driven by predictable, unchanging astronomical geometry (sun
angle/day length) - the same reason a solar-elevation curve looks nearly
identical from one year to the next at a fixed location. Real year-to-year
variation exists (cloud cover mainly) but is a second-order effect on top
of that stable seasonal shape. Using the closest available real year's
*measured* cloud-affected irradiance, calendar-matched by date, is a much
better-grounded stand-in for "2024 solar" than inventing a clear-sky curve
or defaulting to 0 - but it is still a real, stated substitution, not
actual 2024 solar radiation. Every row in the output CSV carries
source_observed_at_utc and source_year columns precisely so this
substitution is auditable, not hidden - see OUTPUT COLUMNS below.

WHY THIS IS A SEPARATE SCRIPT, NOT INLINE IN j_seasonal_weather_rating.py
--------------------------------------------------------------------------
Same reasoning the project already applies to the Met Eireann weather data
(see finner_camp_historical_hourly.csv's own note in
j_seasonal_weather_rating.py's docstring): the analysis script should be
reproducible from a local file without a network call every run. The JRC's
re.jrc.ec.europa.eu host was not reachable via the PVGIS API from ANY
automated channel tried while building this project - not the cloud sandbox
(network policy), not WebFetch (robots.txt), and navigating to it in the
desktop app's own browser pane was also refused (flagged as a high-risk
site there) - so the API path below (fetch_pvgis_json / --lat/--lon/--year)
is kept for anyone who DOES have a clear path to the API, but it was never
actually exercised end-to-end while building this. What WAS exercised: a
person manually downloading the same data by hand from PVGIS's own
interactive tool (https://re.jrc.ec.europa.eu/pvg_tools/en/, "Hourly Data"
tab - free-text location "Finner Camp" or the same lat/lon, tick "Solar
radiation", leave slope/angle at 0 to keep this at global HORIZONTAL
irradiance, matching the API params documented below), which downloads a
file named like Timeseries_<lat>_<lon>_<db>_0deg_0deg_<year>_<year>.csv -
`--from-csv` (parse_manual_pvgis_csv() below) reads that shape directly, no
API call needed, and is the path this project's own pvgis_2024_solar.csv
was actually built from.

WHICH PVGIS QUANTITY THIS PULLS, AND WHY
------------------------------------------
The API path (build_request_url) calls PVGIS's non-interactive "seriescalc"
with:
  pvcalculation=0   - we want raw irradiance, NOT a PV-panel electricity
                       yield estimate (kWh from an assumed panel) - those are
                       a different, wrong quantity for a conductor heat
                       balance and are explicitly NOT what's fetched here.
  angle=0            - the receiving "plane" is horizontal (tilt 0 degrees
                       from the ground), so the result is global irradiance
                       on a HORIZONTAL plane - i.e. global horizontal
                       irradiance (GHI), not plane-of-array irradiance on
                       some assumed tilted panel. A horizontal plane is the
                       closest readily-available PVGIS quantity to "solar
                       heating incident on the site" for a roughly-
                       horizontal overhead conductor; it is an approximation
                       (a real conductor is a horizontal CYLINDER, not a
                       flat plate, so its actual interception geometry
                       differs slightly from a flat horizontal plane through
                       the day) but it is the standard, defensible
                       simplification also used by IEEE 738-style DLR
                       heat-balance models when panel-specific plane-of-
                       array data isn't the point. This approximation is
                       repeated in j_seasonal_weather_rating.py's docstring
                       - don't silently claim GHI is the exact irradiance
                       seen by every metre of conductor.
  aspect=0           - irrelevant at angle=0, a horizontal plane has no
                       compass-facing "aspect"; set for completeness.

The manual-download path (parse_manual_pvgis_csv) gets the SAME horizontal-
plane quantity a different way: PVGIS's own interactive tool exports the
irradiance split into its three physical components - Gb(i) beam (direct),
Gd(i) diffuse, Gr(i) ground-reflected onto the plane - rather than one
combined column. global_solar_radiation_wm2 here is computed as
Gb(i) + Gd(i) + Gr(i), which IS global horizontal irradiance, just summed
from its parts instead of returned pre-summed; confirmed the real export
this project used has Gr(i) = 0.0 at every one of its 8,760 hours (exactly
what's physically expected at 0-degree tilt - a horizontal plane doesn't
"see" its own ground reflection), so in practice this reduces to
Gb(i) + Gd(i). This is NOT plane-of-array irradiance on some assumed
tilted PV panel, and NOT PV electricity yield - the download used slope=0,
same horizontal-plane quantity as the API path above.

PVGIS's irradiance columns (G(i), Gb(i), Gd(i), Gr(i) alike) are already in
W/m^2 - an irradiance, not an energy total - so despite this module's
docstring flagging the Wh/m^2 -> W/m^2 conversion as something to check, no
conversion is actually needed for PVGIS's hourly output. WH_TO_W_PER_HOUR
below is kept anyway (a no-op multiply-by-1) so this stays correct and
self-documenting even if that ever changes upstream.

Timestamps: PVGIS's 'time' field (format YYYYMMDD:HHMM) is UTC. The real
export this project used stamps every hour at HH:11 (11 minutes past the
hour - PVGIS-SARAH3's own hourly-bin convention, not an error) rather than
HH:00 - each row is floored to its hour (HH:00) when written out, both
because that's what it represents (an hourly bin, not an instant at :11)
and to match Met Eireann's on-the-hour observed_at_utc convention exactly,
so the two files can be merged by plain timestamp equality with no
reparsing surprises.

OUTPUT COLUMNS (pvgis_2024_solar.csv)
----------------------------------------
observed_at_utc            - TARGET_YEAR-labelled hour, on-the-hour, UTC
                              (what j_seasonal_weather_rating.py merges on)
global_solar_radiation_wm2 - global horizontal irradiance, W/m^2
solar_elevation_deg        - PVGIS's H_sun (sun height), degrees; unused by
                              the thermal model, kept for anyone auditing
                              day/night rows by hand
source_observed_at_utc     - the REAL SOURCE_YEAR timestamp this row's
                              values were copied from (see "PVGIS DOES NOT
                              YET HAVE 2024 DATA" above) - what makes the
                              substitution auditable row-by-row rather than
                              hidden
source_year                - SOURCE_YEAR, repeated per row for convenience
"""

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

#: Finner Camp, Co. Donegal - Met Eireann station 104, the same station
#: finner_camp_historical_hourly.csv's weather observations come from (see
#: STATION_FOR_LINE in j_seasonal_weather_rating.py). Solar is pulled for
#: the SAME point as the weather observations on purpose, so wind/temp and
#: solar are co-located and can be merged hour-for-hour without introducing
#: a second, different location into the heat balance.
DEFAULT_LAT = 54.4939
DEFAULT_LON = -8.2431

#: See this module's docstring's "PVGIS DOES NOT YET HAVE 2024 DATA".
DEFAULT_SOURCE_YEAR = 2023
DEFAULT_TARGET_YEAR = 2024

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/seriescalc"

WH_TO_W_PER_HOUR = 1.0  # a 1-hour energy total in Wh/m^2 numerically equals
                         # the average W/m^2 over that hour - see docstring.


def build_request_url(lat, lon, year):
    params = {
        "lat": lat,
        "lon": lon,
        "startyear": year,
        "endyear": year,
        "outputformat": "json",
        "pvcalculation": 0,   # raw irradiance, NOT PV electricity yield
        "angle": 0,           # horizontal plane -> global horizontal irradiance
        "aspect": 0,          # irrelevant at angle=0, set for completeness
        "components": 0,      # single combined G(i), not direct/diffuse/reflected
        "usehorizon": 1,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{PVGIS_URL}?{query}"


def fetch_pvgis_json(lat, lon, year, timeout=60):
    url = build_request_url(lat, lon, year)
    print(f"requesting: {url}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"could not reach the PVGIS API ({exc}). This is expected in "
            f"network-restricted environments (see this module's docstring "
            f"- this path was never actually reachable while building this "
            f"project). Use --from-csv instead with a file downloaded by "
            f"hand from https://re.jrc.ec.europa.eu/pvg_tools/en/ (Hourly "
            f"Data tab, slope/angle left at 0) - see "
            f"parse_manual_pvgis_csv()'s docstring for the expected shape.")


def parse_api_json(payload):
    """Extract the hourly time series from PVGIS's seriescalc JSON (the
    components=0 shape - one combined G(i) column). Returns a list of
    (source_observed_at_utc, global_solar_radiation_wm2, solar_elevation_deg)
    tuples, source_observed_at_utc already floored to the hour."""
    try:
        hourly = payload["outputs"]["hourly"]
    except (KeyError, TypeError):
        raise SystemExit(
            "unexpected PVGIS response shape - no outputs.hourly array. "
            "Check the 'inputs'/'meta' sections PVGIS normally includes for "
            "what went wrong (e.g. a location outside its radiation-"
            "database coverage).")

    rows = []
    for rec in hourly:
        observed_at_utc = _floor_to_hour(rec["time"])
        solar_wm2 = float(rec["G(i)"]) * WH_TO_W_PER_HOUR
        solar_elevation_deg = float(rec.get("H_sun", "nan") or "nan")
        rows.append((observed_at_utc, solar_wm2, solar_elevation_deg))
    return rows


def parse_manual_pvgis_csv(path):
    """Parses a file downloaded by hand from PVGIS's interactive "Hourly
    Data" tool (Timeseries_<lat>_<lon>_<db>_<tilt>deg_<azimuth>deg_<start>_
    <end>.csv) - the path this project's own pvgis_2024_solar.csv was
    actually built from (see this module's docstring). That export has a
    handful of metadata lines, then a CSV table with EITHER a single G(i)
    column (components unticked) OR split Gb(i)/Gd(i)/Gr(i) columns
    (components ticked, PVGIS's default in the interactive tool - the shape
    actually encountered here), then a text legend after a blank line. This
    function locates the real header ("time,...") and the blank line that
    ends the data programmatically, rather than assuming a fixed line
    number, so small metadata-block differences between PVGIS tool versions
    don't silently break it.

    Returns the same (source_observed_at_utc, global_solar_radiation_wm2,
    solar_elevation_deg) row shape as parse_api_json(), plus the detected
    source year (from the data itself, not the filename - the filename is
    only used as a fallback if the data is somehow ambiguous)."""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_idx = next((i for i, l in enumerate(lines) if l.startswith("time,")), None)
    if header_idx is None:
        raise SystemExit(
            f"{path} doesn't look like a PVGIS 'Hourly Data' export - no "
            f"line starting with 'time,' found. Re-download from "
            f"https://re.jrc.ec.europa.eu/pvg_tools/en/ (Hourly Data tab).")
    end_idx = next((i for i in range(header_idx + 1, len(lines))
                     if not lines[i].strip()), len(lines))

    header = [c.strip() for c in lines[header_idx].strip().split(",")]
    if "G(i)" in header:
        solar_cols = ["G(i)"]
    elif {"Gb(i)", "Gd(i)"}.issubset(header):
        # Gr(i) (ground-reflected) is physically ~0 at 0-degree tilt - a
        # horizontal plane doesn't see its own ground reflection - but sum
        # it in if present rather than assuming that's true for every
        # export (see this module's docstring).
        solar_cols = [c for c in ("Gb(i)", "Gd(i)", "Gr(i)") if c in header]
    else:
        raise SystemExit(
            f"{path}'s header {header} has neither a G(i) column nor "
            f"Gb(i)/Gd(i) columns - can't identify the irradiance data. "
            f"Re-download with 'Solar radiation' ticked in PVGIS's tool.")
    if "H_sun" not in header:
        raise SystemExit(f"{path} is missing the H_sun (sun height) column.")

    col_idx = {name: i for i, name in enumerate(header)}
    rows = []
    years_seen = set()
    for line in lines[header_idx + 1:end_idx]:
        fields = [c.strip() for c in line.strip().split(",")]
        if not fields or not fields[0]:
            continue
        time_raw = fields[col_idx["time"]]
        observed_at_utc = _floor_to_hour(time_raw)
        years_seen.add(int(time_raw[0:4]))
        solar_wm2 = sum(float(fields[col_idx[c]]) for c in solar_cols) * WH_TO_W_PER_HOUR
        h_sun = float(fields[col_idx["H_sun"]])
        rows.append((observed_at_utc, solar_wm2, h_sun))

    if len(years_seen) != 1:
        raise SystemExit(
            f"{path} spans more than one year ({sorted(years_seen)}) - "
            f"this script expects a single-year export (PVGIS's tool takes "
            f"the same start/end year); re-download with matching start "
            f"and end years.")
    source_year = years_seen.pop()

    print(f"parsed {len(rows)} hourly row(s) from {os.path.basename(path)} "
          f"(source year {source_year}, columns used: {solar_cols} + H_sun)")
    return rows, source_year


def _floor_to_hour(pvgis_time_str):
    """PVGIS's 'time' field, e.g. '20230101:0011' (SARAH3's hourly bins are
    stamped 11 minutes past the hour, not on it - see this module's
    docstring) -> 'YYYY-MM-DD HH:00:00+00:00', UTC, matching
    finner_camp_historical_hourly.csv's observed_at_utc shape exactly."""
    date_part, hm_part = pvgis_time_str.split(":")
    year, month, day = date_part[0:4], date_part[4:6], date_part[6:8]
    hour = hm_part[0:2]
    return f"{year}-{month}-{day} {hour}:00:00+00:00"


def remap_calendar_year(rows, source_year, target_year):
    """Re-labels a full year of (source_observed_at_utc, solar_wm2,
    elevation_deg) rows onto target_year's calendar, matching the SAME
    month/day/hour - NOT a naive "+1 year" or sequential row-shift. Matching
    on calendar date (rather than, say, day-of-year index) is what actually
    preserves each hour's real solar geometry (day length, sun elevation
    curve) when the substitution crosses a leap-year boundary.

    target_year=2024 is a leap year (366 days) and source_year=2023 is not
    (365) - so 2024-02-29 has no 2023-02-29 to copy from. That one date
    falls back to 2023-02-28 (documented here, and reported below - solar
    geometry one calendar day either side of Feb 29 is close enough that
    this is a reasonable, clearly-flagged fallback, not a silent gap).

    Returns (output_rows, n_leap_day_fallback) where output_rows is a list
    of (target_observed_at_utc, solar_wm2, elevation_deg,
    source_observed_at_utc, source_year) - every row keeps a pointer back to
    the real source hour it came from, for auditability (see this module's
    OUTPUT COLUMNS docstring)."""
    # index source rows by (month, day, hour) for direct lookup
    by_mdh = {}
    for source_ts, solar_wm2, elev in rows:
        dt = datetime.datetime.strptime(source_ts, "%Y-%m-%d %H:00:00+00:00")
        by_mdh[(dt.month, dt.day, dt.hour)] = (source_ts, solar_wm2, elev)

    output_rows = []
    n_fallback = 0
    start = datetime.date(target_year, 1, 1)
    end = datetime.date(target_year, 12, 31)
    day = start
    while day <= end:
        for hour in range(24):
            key = (day.month, day.day, hour)
            if key not in by_mdh and day.month == 2 and day.day == 29:
                # leap day with no source match - fall back to Feb 28,
                # same source_year, same hour (see docstring).
                key = (2, 28, hour)
                n_fallback += 1
            if key not in by_mdh:
                raise SystemExit(
                    f"source data has no {source_year}-{key[0]:02d}-"
                    f"{key[1]:02d} {key[2]:02d}:00 to map onto "
                    f"{target_year}-{day.month:02d}-{day.day:02d} "
                    f"{hour:02d}:00 - the source export is missing hours "
                    f"(expected a complete {source_year}).")
            source_ts, solar_wm2, elev = by_mdh[key]
            target_ts = (f"{target_year}-{day.month:02d}-{day.day:02d} "
                         f"{hour:02d}:00:00+00:00")
            output_rows.append((target_ts, solar_wm2, elev, source_ts, source_year))
        day += datetime.timedelta(days=1)

    return output_rows, n_fallback


def write_output_csv(output_rows, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "observed_at_utc", "global_solar_radiation_wm2", "solar_elevation_deg",
            "source_observed_at_utc", "source_year"])
        writer.writerows(output_rows)


def main(lat=DEFAULT_LAT, lon=DEFAULT_LON, source_year=DEFAULT_SOURCE_YEAR,
         target_year=DEFAULT_TARGET_YEAR, out_path=None, from_csv=None):
    if out_path is None:
        out_path = os.path.join(ROOT, "pvgis_2024_solar.csv")

    if from_csv:
        rows, detected_source_year = parse_manual_pvgis_csv(from_csv)
        source_year = detected_source_year
    else:
        payload = fetch_pvgis_json(lat, lon, source_year)
        rows = parse_api_json(payload)

    if not rows:
        raise SystemExit("no hourly rows found - nothing to cache.")

    if source_year == target_year:
        # real target-year data (e.g. PVGIS has caught up since this was
        # written) - no remapping needed, write it straight through with
        # source columns pointing at themselves for schema consistency.
        output_rows = [(ts, wm2, elev, ts, source_year) for ts, wm2, elev in rows]
        n_fallback = 0
    else:
        print(f"\nPVGIS's most recent available year is {source_year}, not "
              f"{target_year} - remapping {source_year} onto the "
              f"{target_year} calendar by matching month/day/hour (see "
              f"this module's docstring's \"PVGIS DOES NOT YET HAVE 2024 "
              f"DATA\"). This is a documented proxy, not real {target_year} "
              f"solar data.")
        output_rows, n_fallback = remap_calendar_year(rows, source_year, target_year)

    write_output_csv(output_rows, out_path)

    solar_vals = [r[1] for r in output_rows]
    print(f"\nwrote {len(output_rows)} hourly rows -> {out_path}")
    print(f"location: {lat}, {lon}   source year: {source_year}   "
          f"labelled as: {target_year}")
    if n_fallback:
        print(f"leap-day fallback used on {n_fallback} hour(s) "
              f"({target_year}-02-29, copied from {source_year}-02-28)")
    print(f"first row: {output_rows[0]}")
    print(f"last row:  {output_rows[-1]}")
    n_daylight = sum(1 for v in solar_vals if v > 0)
    print(f"hours with solar > 0 (daylight): {n_daylight} / {len(solar_vals)}")
    print(f"solar radiation (W/m^2): min={min(solar_vals):.1f} "
          f"mean={sum(solar_vals)/len(solar_vals):.1f} max={max(solar_vals):.1f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lat", type=float, default=DEFAULT_LAT)
    p.add_argument("--lon", type=float, default=DEFAULT_LON)
    p.add_argument("--source-year", type=int, default=DEFAULT_SOURCE_YEAR,
                    help="year to request from the PVGIS API (ignored with --from-csv, "
                         "which detects it from the file itself)")
    p.add_argument("--target-year", type=int, default=DEFAULT_TARGET_YEAR,
                    help="calendar year to label the output as - see this module's "
                         "docstring's \"PVGIS DOES NOT YET HAVE 2024 DATA\"")
    p.add_argument("--out", type=str, default=None)
    p.add_argument("--from-csv", type=str, default=None,
                    help="parse a file downloaded by hand from PVGIS's interactive "
                         "Hourly Data tool instead of calling the API")
    args = p.parse_args()
    main(lat=args.lat, lon=args.lon, source_year=args.source_year,
         target_year=args.target_year, out_path=args.out, from_csv=args.from_csv)
