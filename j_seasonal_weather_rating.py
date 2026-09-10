"""(j.1) Representative seasonal weather -> dynamic line rating (DLR) multiplier.

    python examples/j_seasonal_weather_rating.py [LINE] [SEASON] [PERCENTILE]
    python examples/j_seasonal_weather_rating.py 5041-17010-2 winter 10
    python examples/j_seasonal_weather_rating.py 5041-17010-2 all 10

WIND GENERATION != WIND WEATHER. This script has nothing to do with the
network's wind farm output (that's a modelled seasonal generation
scenario/forecast - WP2033 is "2033 winter peak" - and stays exactly as
shipped; per grid_TF_Wind/participant-kit/README.md, "every time series is
synthetic" - no individual network snapshot hour ever happened). This
script uses independent, real 2024 Met Eireann weather observations plus
real 2024 PVGIS solar radiation for one purpose only: estimating how much
*cooling/heating* a specific overhead line gets from real weather, and
therefore how much thermal (ampacity) headroom it has compared with its
static nameplate rating. The two data sources are never mixed - see
j_apply_seasonal_dlr.py's module docstring for how the result of this
script is applied without touching generation at all.

WHY "REPRESENTATIVE SEASONAL", NOT HOUR-BY-HOUR AGAINST THE NETWORK
-------------------------------------------------------------------
An earlier version of this pipeline tried to align Met Eireann's real
timestamped weather hour-by-hour against the network's 168 snapshots
(snapshot 1 <-> weather hour 1, snapshot 2 <-> weather hour 2, ...). That is
wrong and has been discarded: the network's snapshots are a MODELLED
SCENARIO WEEK (a representative winter- or summer-peak profile), not 168
consecutive real calendar hours, so there is no real hour that snapshot 1
"is". Pretending otherwise would let a real calm hour sit next to a
snapshot where the model assumed high wind generation, or vice versa, for
no physical reason.

What we do instead: gather every real 2024 Met Eireann observation from the
same broad SEASON as the generation scenario, compute what this line's
thermal rating would have been in each of those real hours (wind, its
direction relative to the line, air temperature AND solar radiation all
together, per hour - see "SOLAR AND WIND DIRECTION ARE HOURLY INPUTS"
below), and collapse THAT distribution of per-hour multipliers down to ONE
representative number - a single seasonal DLR multiplier - which is what
actually gets applied to the network (see j_apply_seasonal_dlr.py). That's
a defensible claim: "here is a realistic rating for this line under
representative 2024 winter weather." It is NOT a claim that any particular
network snapshot corresponds to any particular real hour, and it is NOT a
real-time or hour-by-hour DLR series.

WHY 2024 ONLY, NOT THE FULL 1997-2026 ARCHIVE
-----------------------------------------------
finner_camp_historical_hourly.csv (see WEATHER_CSV_FOR_LINE below) actually
holds ~29 years of Met Eireann observations (1997-10-01 to 2026-09-01). An
earlier version of this analysis used that entire archive as the seasonal
distribution. This version deliberately restricts every calculation to
calendar year 2024 only (see TARGET_YEAR, filter_to_target_year() below,
and the printed diagnostics every run produces) - a single, recent,
internally-consistent year, rather than a multi-decade blend that could
mix in weather from a materially different climate baseline. "winter" here
means Jan + Feb + Dec **2024** specifically - NOT Dec 2023 + Jan/Feb 2024
(the usual meteorological DJF convention that spans a calendar-year
boundary) - because this study is explicitly restricted to 2024
observations only; see SEASON_MONTHS and filter_to_season() below. This is
a narrower, single-year sample than the old 29-year version (see the
sample-size warning printed by representative_multiplier() below) - that's
a real tradeoff, made deliberately for a single self-consistent reference
year, not an oversight.

SOLAR AND WIND DIRECTION ARE HOURLY INPUTS, NOT SEASONAL AVERAGES
-------------------------------------------------------------------
Every one of wind speed, wind direction (via the line's real azimuth -
see LINE_AZIMUTH_FOR_LINE below), air temperature and solar radiation is
looked up PER OBSERVATION and fed into the SAME heat-balance calculation
for that hour, before any statistics are taken. The representative
seasonal multiplier is a percentile of the resulting per-hour multiplier
distribution (see representative_multiplier()) - never a thermal
calculation run once on a seasonally-averaged wind speed/temperature/solar
value. Averaging the inputs first would be physically wrong: heat loss is
a non-linear function of wind speed and temperature, and a calm, hot,
sunny hour needs to be represented by ITS OWN (low) multiplier, not
smoothed away by averaging it against a windy, cold, dark hour elsewhere in
the season.

DATA SOURCES (read this before trusting any number this script prints)
------------------------------------------------------------------------
Station 104, Finner Camp, Co. Donegal (54.4939 N, -8.2431 W) - the nearest
Met Eireann synoptic station to Ballyshannon / Cathaleen's Fall / Srananagh,
i.e. both ends of the target line 5041-17010-2 (Cathaleen's Fall end: 5.4
km away; Srananagh 220 end: 36.3 km away - see LINE_AZIMUTH_FOR_LINE's
comment for how that was measured. Finner Camp is a much better proxy for
one end of this line than the other; that asymmetry is a real limitation,
not something this script can fix without a second station - see "SINGLE
STATION" below).

  * finner_camp_historical_hourly.csv (WEATHER_CSV_FOR_LINE below) - Met
    Eireann's real historical archive for this station ("Finner Hourly
    Data", downloaded by hand from https://data.gov.ie/dataset/finner-hourly-data
    - it's blocked from automated fetching by robots.txt, both there and at
    the direct CSV host, so this file has to be re-downloaded by hand if it
    needs refreshing). Columns: observed_at_utc, wind_speed_kts,
    wind_speed_ms, wind_gust_kts, wind_gust_ms, wind_direction_deg_true,
    air_temperature_c. This script filters it down to calendar year 2024
    only - see above.
  * pvgis_2024_solar.csv (SOLAR_CSV_FOR_LINE below) - hourly global
    horizontal solar irradiance from the EU JRC's PVGIS, for the SAME
    Finner Camp coordinates the weather observations come from (so solar
    and wind/temperature are co-located, not two different points), labelled
    as 2024 but ACTUALLY BUILT FROM REAL 2023 PVGIS OBSERVATIONS - PVGIS's
    radiation database did not yet cover 2024 when this project was built;
    2023 (its most recent complete year) is calendar-matched onto 2024's
    dates (same month/day/hour) as a documented proxy - see
    fetch_pvgis_2024_solar.py's docstring's "PVGIS DOES NOT YET HAVE 2024
    DATA" for the full reasoning and the one date (2024-02-29, a leap day
    with no 2023 equivalent) that needed a one-day fallback. This is a real,
    stated limitation of this analysis, not something to gloss over -
    "2024 solar" in this project means "2023's real, measured solar,
    replayed onto the 2024 calendar," not actual 2024 observations. Columns:
    observed_at_utc (2024-labelled), global_solar_radiation_wm2 (W/m^2,
    already an irradiance - not an energy total, no Wh->W conversion
    needed - see fetch_pvgis_2024_solar.py's docstring for why),
    solar_elevation_deg, source_observed_at_utc and source_year (the real
    2023 hour each row's values were copied from - see load_solar()'s
    diagnostics). This project's own fetch_pvgis_2024_solar.py script
    builds this file, either from the PVGIS API directly (if reachable -
    it wasn't from any automated channel tried while building this
    project) or from a file downloaded by hand from PVGIS's own
    interactive tool (the path actually used here). If pvgis_2024_solar.csv
    is missing, this script stops with a clear error rather than silently
    assuming solar_wm2=0 - see main() below. An earlier version of this
    script did default missing solar to 0.0; that was fine as a
    placeholder but is NOT an acceptable final assumption (solar heating
    is a real, and in summer often dominant, input to the conductor heat
    balance - see heat_loss_wm() below).
  * PVGIS's G(i) at angle=0 (horizontal plane) is used as global horizontal
    irradiance - an approximation of "solar heating incident on the
    conductor", not an exact measurement of irradiance on a horizontal
    CYLINDER's curved surface at every hour angle. See
    fetch_pvgis_2024_solar.py's docstring for the full reasoning on why
    that quantity (and not PV electricity yield, or a tilted plane-of-array
    figure) is the right one here. Documented approximation, not claimed
    exact.

SINGLE STATION, NOT MULTIPLE - INVESTIGATED, NOT IMPLEMENTED
----------------------------------------------------------------
The network's own line/bus tables (grid_TF_Wind/participant-kit/networks/
WP2033_north-west/{lines,buses}.csv) were checked for other nearby,
geocoded stations that could give a second or third representative point
along this line (e.g. to take a limiting min() across stations - the
conceptually "right" way to extend this to multi-station DLR). No second
Met Eireann station with hourly wind/temperature data was identified as
part of this project's data for the Srananagh end of the line. Rather than
fabricate a second station location, this script keeps the existing
single-station assumption and states it plainly: THE MODEL ASSUMES THAT
FINNER CAMP OBSERVATIONS ARE REPRESENTATIVE OF THE WEATHER EXPERIENCED
ALONG THE WHOLE TARGET LINE, even though the two ends are 5.4 km and 36.3
km away from the station respectively. Multi-station DLR is a genuine
future enhancement, not something faked here.

Do not add further weather/solar assumptions beyond what's listed above -
if a future run has more real columns available (e.g. a second station),
extend the relevant lookup dict and calculation, don't guess values that
were never measured.
"""

import math
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))

#: This study is restricted to a single, recent calendar year - see this
#: module's docstring ("WHY 2024 ONLY"). Every filter below is anchored to
#: this constant on purpose, so changing the target year means changing it
#: in exactly one place and can't be done by accident.
TARGET_YEAR = 2024

#: Which weather CSV backs which monitored line. Extend this as other
#: teammates' target lines get their own nearest station - do NOT apply
#: Finner Camp's weather to a line near a different station without adding
#: it here explicitly, since "nearest station" varies by line.
WEATHER_CSV_FOR_LINE = {
    "5041-17010-2": os.path.join(ROOT, "finner_camp_historical_hourly.csv"),
}

#: Which cached 2024 PVGIS solar CSV backs which monitored line - see
#: fetch_pvgis_2024_solar.py, and this module's docstring's "DATA SOURCES"
#: section for the exact columns expected.
SOLAR_CSV_FOR_LINE = {
    "5041-17010-2": os.path.join(ROOT, "pvgis_2024_solar.csv"),
}

#: Weather station used per line, for the printed report (id -> human name).
STATION_FOR_LINE = {
    "5041-17010-2": ("104", "Finner Camp, Co. Donegal"),
}

#: Real line orientation (compass bearing, degrees true, 0-360 - either end
#: works, see wind_perpendicular_ms()'s docstring for why), calculated from
#: the network's own geocoded bus coordinates - NOT invented:
#:
#:   grid_TF_Wind/participant-kit/networks/WP2033_north-west/buses.csv
#:     Srananagh 220     x=-8.383984     y=54.1777596     (bus0)
#:     Cathaleen's Fall   x=-8.15878725   y=54.49594499999999  (bus1)
#:   both rows have coordinate_source=geocoded (not a "neighbour mean"
#:   fallback - see that file's other rows for what a lower-confidence
#:   coordinate looks like).
#:
#: Forward-azimuth (initial bearing) from bus0 to bus1, standard formula:
#:   dlon = radians(lon2 - lon1)
#:   y = sin(dlon) * cos(radians(lat2))
#:   x = cos(radians(lat1))*sin(radians(lat2))
#:       - sin(radians(lat1))*cos(radians(lat2))*cos(dlon)
#:   bearing = degrees(atan2(y, x)) % 360
#: gives 22.33 degrees true. bearing_deg() below reproduces this exactly -
#: use it to derive a new line's azimuth from its own bus coordinates
#: rather than hand-copying this one. Great-circle bus0-bus1 distance is
#: 38.3 km against this line's lines.csv `length` of 49.67 km - a real
#: overhead route is never perfectly straight, so a routed length longer
#: than the great-circle distance is expected and is itself a small sanity
#: check that these are real, sensible coordinates.
LINE_AZIMUTH_FOR_LINE = {
    "5041-17010-2": 22.33,
}

#: month-of-year buckets used by --season, evaluated only AFTER data has
#: already been restricted to TARGET_YEAR (see filter_to_target_year()) -
#: so "winter" here means Jan+Feb+Dec of TARGET_YEAR specifically, never a
#: Dec from the previous year. "all" (handled specially in
#: filter_to_season()) skips month filtering entirely and uses every
#: TARGET_YEAR observation.
SEASON_MONTHS = {
    "winter": (1, 2, 12),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}

#: -----------------------------------------------------------------------
#: Conductor / rating-reference assumptions. THESE ARE ASSUMED, not read
#: from the PyPSA network or from any EirGrid-published conductor spec -
#: the network's line table (as shipped in this kit) carries s_nom (MVA)
#: and per-unit electrical parameters (r, x, b) for the DC power-flow
#: approximation, and grid_TF_Wind/participant-kit/README.md states
#: explicitly that s_nom is a TYTFS RATE1 planning figure, not derived from
#: physical conductor properties in this kit. No EirGrid document giving
#: this specific circuit's conductor type, diameter or emissivity was found
#: in this project's data. Every value below is a stated, typical
#: engineering assumption for an overhead 110/220kV circuit of this kind -
#: swap in the real values if/when this line's actual conductor spec is
#: found. Do NOT present these as "EirGrid's exact values" - they aren't.
#: -----------------------------------------------------------------------
ASSUMED_PARAMS = {
    "conductor_diameter_m": 0.0286,   # typical ACSR "Zebra" 400 mm^2 overhead conductor
    "emissivity": 0.5,                # moderately weathered conductor surface, 0-1 scale
    "absorptivity": 0.5,              # solar absorptivity, 0-1 scale
    "max_conductor_temp_c": 75.0,     # typical ACSR continuous thermal design limit
    "reference_wind_speed_ms": 0.6,   # wind speed assumed for the STATIC nameplate rating
    "reference_ambient_temp_c": 20.0, # ambient temp assumed for the STATIC nameplate rating
}

#: Used ONLY when a line has no entry in LINE_AZIMUTH_FOR_LINE (i.e. its
#: real geometry hasn't been looked up yet) - treats every hour's wind as
#: if it struck the conductor perpendicular (angle_difference=90 degrees,
#: abs(sin(90))=1.0, i.e. no reduction at all vs raw wind speed). This is
#: this script's PREVIOUS default behaviour for every line, kept only as an
#: explicit, reported fallback. Read this carefully before trusting a run
#: that uses it: assuming perpendicular incidence is the MAXIMUM-cooling
#: assumption for a given wind speed, not a conservative one - an earlier
#: version of this file's comments called it "worst-case/conservative",
#: which has it backwards (the actually-conservative assumption for a
#: rating is LOW cooling, i.e. wind closer to parallel with the line, which
#: is why the static reference case below uses a low 0.6 m/s speed rather
#: than a favourable angle). So a line falling back to this constant gets a
#: multiplier that may be somewhat OPTIMISTIC relative to its true,
#: unknown, per-hour wind angle - flagged loudly in main()'s printed output
#: whenever it's used.
FALLBACK_WIND_ANGLE_FACTOR = 1.0

SIGMA = 5.670374e-8   # Stefan-Boltzmann constant, W/(m^2 K^4) - exact, not assumed
K_AIR = 0.0270         # W/(m.K), representative air thermal conductivity (not temp-varying -
                       # stated simplification; real IEEE738 varies this with film temperature)
NU_AIR = 1.60e-5       # m^2/s, representative air kinematic viscosity (same simplification)


def bearing_deg(lat1, lon1, lat2, lon2):
    """Forward azimuth (initial compass bearing, degrees true, 0-360) from
    point 1 to point 2, standard great-circle bearing formula. Used to
    derive LINE_AZIMUTH_FOR_LINE's entries from real bus coordinates (see
    that dict's comment) - call this again with a new line's bus0/bus1
    (x=lon, y=lat) coordinates from its networks/.../buses.csv rather than
    hand-guessing a new line's azimuth."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def wind_perpendicular_ms(wind_speed_ms, wind_direction_deg, line_azimuth_deg):
    """Component of wind speed perpendicular to the line - the physically
    relevant quantity for forced-convection cross-flow cooling of a
    cylindrical conductor (a wind blowing along the line barely disturbs
    its boundary layer; a wind blowing across it does most of the cooling).
    wind_direction_deg follows Met Eireann's convention - the direction the
    wind is blowing FROM, not the compass heading the air itself is
    travelling towards - but that 180-degree difference in convention does
    NOT change the result here, since the formula below only uses the
    angle's magnitude via abs(sin(...)): a wind blowing from along the line
    gives the same (near-zero) perpendicular component as one blowing
    towards along the line, either way. line_azimuth_deg only needs to be
    one of the line's two ends' bearings (0-360) - the min(..., 360-...)
    step below already collapses the calculation onto a 0-180 degree
    angular difference, so it doesn't matter which end's bearing was used
    to build LINE_AZIMUTH_FOR_LINE.
    """
    angle_difference = abs(wind_direction_deg - line_azimuth_deg)
    angle_difference = min(angle_difference, 360.0 - angle_difference)
    return wind_speed_ms * abs(math.sin(math.radians(angle_difference)))


def load_observations(csv_path):
    """Reads a Met Eireann weather CSV in the shape
    finner_camp_historical_hourly.csv is in: observed_at_utc,
    wind_speed_kts, wind_speed_ms, wind_gust_kts, wind_gust_ms,
    wind_direction_deg_true, air_temperature_c. Solar radiation is a
    SEPARATE file now (see load_solar() and this module's docstring) - it
    used to be looked for as a column on this same CSV, but Met Eireann
    doesn't carry it and PVGIS does, so the two are merged by timestamp in
    main() instead of expected to already be one file.
    """
    if not os.path.exists(csv_path):
        raise SystemExit(
            f"weather CSV not found: {csv_path}\n"
            f"Pass --weather-csv to point at the real file, or add/fix its "
            f"path in WEATHER_CSV_FOR_LINE at the top of this file.")
    df = pd.read_csv(csv_path, parse_dates=["observed_at_utc"])
    if df["observed_at_utc"].isna().any():
        raise SystemExit(
            f"{df['observed_at_utc'].isna().sum()} row(s) in {csv_path} have "
            f"an observed_at_utc timestamp that failed to parse - fix or "
            f"drop those rows in the source CSV before trusting this run.")
    df["year"] = df["observed_at_utc"].dt.year
    df["month"] = df["observed_at_utc"].dt.month
    return df


def load_solar(csv_path):
    """Reads the cached PVGIS solar CSV (see fetch_pvgis_2024_solar.py and
    this module's docstring). Expected columns: observed_at_utc,
    global_solar_radiation_wm2 (W/m^2), and optionally solar_elevation_deg
    (unused here, kept for anyone auditing day/night rows by hand),
    source_observed_at_utc and source_year (also unused in the calculation
    - present only when fetch_pvgis_2024_solar.py had to substitute a
    different real year's data for TARGET_YEAR because PVGIS didn't have
    TARGET_YEAR yet; see that script's docstring. Surfaced here as a loud
    print, not silently passed through, so a run against a cross-year-
    substituted solar file is never mistaken for one against real
    TARGET_YEAR solar observations)."""
    if not os.path.exists(csv_path):
        raise SystemExit(
            f"solar CSV not found: {csv_path}\n"
            f"This script requires real 2024 PVGIS solar radiation for the "
            f"final analysis (see this module's docstring - solar is a real "
            f"heat input, not something that can be defaulted to 0 any "
            f"more). Run:\n"
            f"    python fetch_pvgis_2024_solar.py\n"
            f"once (from a machine that can reach the PVGIS API) to build "
            f"this file, or pass --solar-csv to point at an existing one.")
    df = pd.read_csv(csv_path, parse_dates=["observed_at_utc"])
    required = {"observed_at_utc", "global_solar_radiation_wm2"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(
            f"{csv_path} is missing required column(s) {sorted(missing)} - "
            f"see this module's docstring for the expected PVGIS CSV shape.")
    if df["global_solar_radiation_wm2"].lt(0).any():
        n_bad = int(df["global_solar_radiation_wm2"].lt(0).sum())
        raise SystemExit(
            f"{n_bad} row(s) in {csv_path} have negative "
            f"global_solar_radiation_wm2 - that's not physically valid "
            f"irradiance, check the source data/units before trusting this "
            f"run.")
    dupes = df["observed_at_utc"].duplicated().sum()
    if dupes:
        print(f"WARNING: {dupes} duplicate observed_at_utc timestamp(s) in "
              f"{os.path.basename(csv_path)} - keeping the first of each "
              f"and dropping the rest.")
        df = df.drop_duplicates(subset="observed_at_utc", keep="first")

    years_present = sorted(df["observed_at_utc"].dt.year.unique().tolist())
    print(f"solar file {os.path.basename(csv_path)}: {len(df)} row(s), "
          f"covering {df['observed_at_utc'].min()} to "
          f"{df['observed_at_utc'].max()} (year(s) present: {years_present})")

    if "source_year" in df.columns:
        source_years = sorted(df["source_year"].dropna().unique().tolist())
        if source_years != [TARGET_YEAR]:
            print(f"NOTE: this solar file's observed_at_utc is labelled "
                  f"{TARGET_YEAR}, but its values were copied from real "
                  f"{source_years} PVGIS observations (calendar-matched by "
                  f"month/day/hour - see fetch_pvgis_2024_solar.py's "
                  f"docstring's \"PVGIS DOES NOT YET HAVE 2024 DATA\"). "
                  f"This run's solar input is a documented proxy, NOT "
                  f"real {TARGET_YEAR} solar observations.")

    if TARGET_YEAR not in years_present:
        raise SystemExit(
            f"{csv_path} does not contain any {TARGET_YEAR} observations "
            f"(years present: {years_present}) - this script requires "
            f"{TARGET_YEAR} solar data to match the {TARGET_YEAR} weather "
            f"data. Re-run fetch_pvgis_2024_solar.py or check --solar-csv.")
    return df


def filter_to_target_year(df, year=TARGET_YEAR):
    """Restricts observations to a single calendar year - see this module's
    docstring's "WHY 2024 ONLY" section. Always call this BEFORE
    filter_to_season(), never the other way round, so "winter" can never
    accidentally pull in December of the previous year."""
    filtered = df[df["year"] == year].reset_index(drop=True)
    if filtered.empty:
        raise SystemExit(
            f"no observations fall in year={year} - the weather CSV only "
            f"covers {df['observed_at_utc'].min()} to "
            f"{df['observed_at_utc'].max()}. This script deliberately does "
            f"NOT fall back to a different year (see this module's "
            f"docstring) - fix TARGET_YEAR or the input CSV.")
    return filtered


def filter_to_season(df, season):
    """Restrict (already year-filtered - see filter_to_target_year())
    observations to the given season's months. season='all' skips month
    filtering entirely and uses every TARGET_YEAR observation."""
    if season == "all":
        return df
    if season not in SEASON_MONTHS:
        raise SystemExit(
            f"unknown season '{season}' - choose from "
            f"{list(SEASON_MONTHS)} or 'all'")
    months = SEASON_MONTHS[season]
    filtered = df[df["month"].isin(months)]
    if filtered.empty:
        raise SystemExit(
            f"no {TARGET_YEAR} observations fall in season='{season}' "
            f"(months {months}) - check the input CSV actually covers "
            f"{TARGET_YEAR} for these months.")
    return filtered


def merge_solar(weather_df, solar_df):
    """Left-merges PVGIS solar onto the (already year+season filtered)
    weather observations by exact observed_at_utc match - NOT by row
    position (see this module's docstring: two different real datasets,
    aligned only by their real timestamps). Prints match/miss diagnostics.
    Rows with no matching solar timestamp are kept with
    global_solar_radiation_wm2 = NaN, EXCLUDED later from the rating
    calculation (see compute_hourly_rating()) rather than silently given an
    assumed value - a missing PVGIS hour is a real data gap, not something
    this script infers as night (PVGIS's own series already contains
    physically-correct zeros at night, so a still-missing value after this
    merge means the hour genuinely wasn't returned by PVGIS, not that it
    was dark)."""
    dupes = weather_df["observed_at_utc"].duplicated().sum()
    if dupes:
        print(f"WARNING: {dupes} duplicate observed_at_utc timestamp(s) in "
              f"the weather data - keeping the first of each.")
        weather_df = weather_df.drop_duplicates(subset="observed_at_utc", keep="first")

    merged = weather_df.merge(
        solar_df[["observed_at_utc", "global_solar_radiation_wm2"]],
        on="observed_at_utc", how="left")

    n_total = len(merged)
    n_matched = int(merged["global_solar_radiation_wm2"].notna().sum())
    n_missing = n_total - n_matched
    print(f"\nsolar observations loaded: {len(solar_df)} "
          f"(from {os.path.basename(str(solar_df.attrs.get('source', '')))})"
          if solar_df.attrs.get("source") else
          f"\nsolar observations loaded: {len(solar_df)}")
    print(f"solar observations matched to weather hours: {n_matched} / {n_total} "
          f"({100.0 * n_matched / n_total:.1f}%)")
    print(f"solar observations missing (excluded from rating calc): {n_missing} "
          f"({100.0 * n_missing / n_total:.1f}%)")
    if n_matched:
        matched_solar = merged.loc[merged["global_solar_radiation_wm2"].notna(),
                                    "global_solar_radiation_wm2"]
        print(f"solar radiation (W/m^2): min={matched_solar.min():.1f} "
              f"mean={matched_solar.mean():.1f} max={matched_solar.max():.1f}")
    return merged


def nusselt_hilpert(re):
    """Standard Hilpert correlation for forced convection over a circular
    cylinder in cross-flow (textbook heat-transfer correlation - the same
    physical basis IEEE738's own convection term is built on). Nu = C * Re^n,
    piecewise in Reynolds number."""
    if re < 4:
        c, n = 0.989, 0.330
    elif re < 40:
        c, n = 0.911, 0.385
    elif re < 4000:
        c, n = 0.683, 0.466
    elif re < 40000:
        c, n = 0.193, 0.618
    else:
        c, n = 0.0266, 0.805
    return c * (re ** n)


def heat_loss_wm(wind_perpendicular_ms, air_temp_c, solar_wm2=0.0, params=ASSUMED_PARAMS):
    """Conductor heat LOSS (convective + radiative), in W/m, at the given
    PERPENDICULAR wind speed and ambient temperature, holding the conductor
    at its assumed max temperature - and nets off solar heat GAIN if
    solar_wm2 is provided. Returns (pc, pr, ps) in W/m so callers can
    inspect each term; net = pc + pr - ps is what actually goes into the
    rating multiplier (see compute_hourly_rating()) - solar SUBTRACTS from
    available heat-loss capacity, it never adds to it, since more solar
    heating means less current-driven heating the conductor can additionally
    tolerate before hitting its temperature limit.

    wind_perpendicular_ms MUST already be the component of wind speed
    perpendicular to the line (see wind_perpendicular_ms() above) - this
    function itself does no angle correction; the Reynolds number, and
    therefore the whole convective term, is computed directly from whatever
    speed is passed in, which is the physically correct place for the
    angle-of-attack effect to enter (rather than a post-hoc multiplier on
    Nusselt number, which an earlier version of this file used).

    Convection: Hilpert cylinder-in-crossflow correlation (see
    nusselt_hilpert). Radiation: exact Stefan-Boltzmann physics. Both are
    evaluated at max_conductor_temp_c, which is what "thermal rating" means:
    the current at which the conductor sits at its temperature LIMIT, not
    its temperature right now.
    """
    d = params["conductor_diameter_m"]
    tc_max_c = params["max_conductor_temp_c"]

    # v_eff floor: a purely numerical safeguard against Re=0 (division by
    # a near-zero characteristic velocity), NOT a claim that 0.1 m/s is a
    # real physical wind condition - true still air still gets a (small,
    # non-zero) natural-convection cooling contribution in reality, which
    # this simplified forced-convection-only correlation can't represent at
    # V=0; the floor exists so the model degrades gracefully instead of
    # blowing up, nothing more.
    v_eff = max(wind_perpendicular_ms, 0.1)
    re = v_eff * d / NU_AIR
    nu = nusselt_hilpert(re)
    h_c = nu * K_AIR / d
    dt = max(tc_max_c - air_temp_c, 0.01)
    pc = h_c * math.pi * d * dt  # convective loss, W/m

    tc_k = tc_max_c + 273.15
    ta_k = air_temp_c + 273.15
    pr = params["emissivity"] * SIGMA * math.pi * d * (tc_k**4 - ta_k**4)  # radiative loss, W/m

    ps = params["absorptivity"] * d * solar_wm2  # solar gain, W/m

    return pc, pr, ps


def compute_hourly_rating(df, line_azimuth_deg, params=ASSUMED_PARAMS):
    """Full per-hour heat-balance pipeline: wind speed + wind direction +
    line azimuth -> perpendicular wind speed -> convection; + air
    temperature -> radiation; + solar radiation -> solar heat gain
    (subtracted); net heat-loss capacity -> relative rating multiplier:

        M_t = sqrt(net_heat_loss_t / net_heat_loss_reference)

    WHY THIS RATIO NEVER NEEDS THE CONDUCTOR'S ELECTRICAL RESISTANCE: at
    thermal equilibrium, current-driven (I^2 * R) heating equals net heat
    LOSS capacity, so I_max = sqrt(net_heat_loss / R). R is NOT irrelevant
    to that equation - it's very much in there - but it cancels out of the
    RATIO M_t = I_max,t / I_max,reference specifically because both the
    weather case and the reference (static-rating) case are evaluated at
    the same assumed maximum conductor temperature
    (params["max_conductor_temp_c"], see ASSUMED_PARAMS). Assuming the same
    physical conductor in both cases, resistance is a function of
    conductor temperature (it rises with temperature) - so R at 75C in the
    weather case is the same R(75C) as in the reference case, and it
    divides out of the ratio: M_t = sqrt((net_t/R) / (net_ref/R)) =
    sqrt(net_t / net_ref). No specific resistance value is invented or
    needed anywhere in this file - not because resistance doesn't matter
    physically, but because this particular ratio, under the fixed-Tmax
    assumption, doesn't require knowing it.

    line_azimuth_deg=None means this line has no known real geometry (see
    LINE_AZIMUTH_FOR_LINE) - every hour then falls back to
    FALLBACK_WIND_ANGLE_FACTOR (documented above - NOT a conservative
    assumption, flagged loudly in main()).

    Returns a DataFrame with one row per input observation and every
    intermediate column this project's methodology asks to be auditable
    (see this module's OUTPUT DATASET columns, written out by main()) -
    rows where wind direction is missing (can't compute a real perpendicular
    component) or where solar is missing (see merge_solar()) get
    rating_multiplier = NaN and are excluded, not guessed, downstream in
    representative_multiplier().
    """
    ref_pc, ref_pr, ref_ps = heat_loss_wm(
        params["reference_wind_speed_ms"], params["reference_ambient_temp_c"],
        solar_wm2=0.0, params=params)
    ref_net = ref_pc + ref_pr - ref_ps
    if ref_net <= 0:
        raise SystemExit(
            "reference (static-rating) net heat-loss capacity came out "
            "<= 0 W/m - that means ASSUMED_PARAMS itself is unphysical "
            "(e.g. absorptivity/solar term overwhelming the reference "
            "convective+radiative loss with solar_wm2=0, which shouldn't "
            "be possible) - check ASSUMED_PARAMS before trusting anything "
            "downstream.")

    n_missing_direction = 0
    n_used_fallback_azimuth = int(line_azimuth_deg is None)
    n_missing_solar = 0
    n_net_leq_zero = 0

    rows = []
    for _, r in df.iterrows():
        wind_speed = r["wind_speed_ms"]
        wind_dir = r["wind_direction_deg_true"]
        air_temp = r["air_temperature_c"]
        solar = r["global_solar_radiation_wm2"]

        if pd.isna(solar):
            n_missing_solar += 1
            rows.append(_blank_row(r, wind_speed, wind_dir, air_temp))
            continue

        if line_azimuth_deg is None:
            # No real geometry for this line - see FALLBACK_WIND_ANGLE_FACTOR's
            # docstring above for exactly what this assumes and why it is
            # NOT a conservative substitute for the real angle.
            v_perp = wind_speed * FALLBACK_WIND_ANGLE_FACTOR
        elif pd.isna(wind_dir):
            n_missing_direction += 1
            rows.append(_blank_row(r, wind_speed, wind_dir, air_temp, solar))
            continue
        else:
            v_perp = wind_perpendicular_ms(wind_speed, wind_dir, line_azimuth_deg)

        pc, pr, ps = heat_loss_wm(v_perp, air_temp, solar_wm2=solar, params=params)
        net = pc + pr - ps
        if net <= 0:
            n_net_leq_zero += 1
            rows.append(_blank_row(r, wind_speed, wind_dir, air_temp, solar,
                                    v_perp=v_perp, pc=pc, pr=pr, ps=ps, net=net))
            continue

        multiplier = (net / ref_net) ** 0.5
        rows.append({
            "observed_at_utc": r["observed_at_utc"],
            "year": r["year"],
            "wind_speed_ms": wind_speed,
            "wind_direction_deg_true": wind_dir,
            "line_azimuth_deg": line_azimuth_deg,
            "wind_perpendicular_ms": v_perp,
            "air_temperature_c": air_temp,
            "global_solar_radiation_wm2": solar,
            "convective_heat_loss_wm": pc,
            "radiative_heat_loss_wm": pr,
            "solar_heat_gain_wm": ps,
            "net_heat_loss_wm": net,
            "rating_multiplier": multiplier,
        })

    result = pd.DataFrame(rows)

    print(f"\nwind direction: missing on {n_missing_direction} observation(s) "
          f"(excluded from the rating calc)")
    if n_used_fallback_azimuth:
        print(f"WARNING: no real line azimuth known for this line - every "
              f"hour used FALLBACK_WIND_ANGLE_FACTOR "
              f"({FALLBACK_WIND_ANGLE_FACTOR}), NOT this line's real "
              f"geometry. See FALLBACK_WIND_ANGLE_FACTOR's docstring: this "
              f"is an upper-bound-on-cooling assumption, not a conservative "
              f"one.")
    else:
        print(f"line azimuth: {line_azimuth_deg:.2f} deg true "
              f"(from real geocoded bus coordinates - see "
              f"LINE_AZIMUTH_FOR_LINE's comment)")
    print(f"solar: missing/unmatched on {n_missing_solar} observation(s) "
          f"(excluded from the rating calc)")
    if n_net_leq_zero:
        print(f"WARNING: net heat-loss capacity <= 0 W/m on "
              f"{n_net_leq_zero} observation(s) (solar heat gain exceeded "
              f"convective+radiative loss) - excluded from the rating calc "
              f"rather than taking sqrt() of a non-positive number.")

    return result


def _blank_row(r, wind_speed, wind_dir, air_temp, solar=float("nan"),
                v_perp=float("nan"), pc=float("nan"), pr=float("nan"),
                ps=float("nan"), net=float("nan")):
    """One excluded observation, kept in the output for auditability
    (rating_multiplier=NaN) rather than silently dropped from the CSV."""
    return {
        "observed_at_utc": r["observed_at_utc"],
        "year": r["year"],
        "wind_speed_ms": wind_speed,
        "wind_direction_deg_true": wind_dir,
        "line_azimuth_deg": r.get("line_azimuth_deg", float("nan")),
        "wind_perpendicular_ms": v_perp,
        "air_temperature_c": air_temp,
        "global_solar_radiation_wm2": solar,
        "convective_heat_loss_wm": pc,
        "radiative_heat_loss_wm": pr,
        "solar_heat_gain_wm": ps,
        "net_heat_loss_wm": net,
        "rating_multiplier": float("nan"),
    }


def representative_multiplier(multipliers, percentile=10):
    """Collapses a season's worth of per-hour multipliers into ONE
    representative value, by calculating the multiplier PER OBSERVATION
    first (see compute_hourly_rating()) and taking a percentile of the
    resulting distribution - not by averaging the raw weather first and
    running it through the thermal model once (that would be physically
    wrong, since heat loss is a non-linear function of wind speed,
    temperature and solar radiation; the average of the ratings is not the
    rating of the average weather). NaN entries (excluded observations -
    see compute_hourly_rating()) are dropped before the percentile is taken.

    Why percentile 10, not the mean, and why this is a STUDY CHOICE, not an
    EirGrid or industry standard: this multiplier is going to stand in for
    a transmission thermal CONSTRAINT for an entire season. The mean rating
    is, by construction, exceeded only about half the time within that
    season - using it would mean the line is silently over-rated on
    below-average-cooling hours roughly half the season. Taking a low
    percentile instead is a deliberately conservative statistical choice
    for THIS study: P10 represents a rating multiplier that was met or
    exceeded by approximately 90% of the selected {TARGET_YEAR} season's
    observations. Nothing in the shared kit, in EirGrid's published
    material, or in any task brief requires P10 specifically - it is not
    presented as an EirGrid convention. Pass a different percentile (e.g.
    50 for a central estimate, or 5 for a more conservative one) to compare.
    """
    valid = multipliers.dropna()
    if len(valid) == 0:
        raise SystemExit(
            "every observation in this season was excluded (missing solar, "
            "missing direction, or non-positive net heat loss) - nothing "
            "left to compute a percentile from. See the diagnostics printed "
            "above for which check is failing.")

    sorted_vals = valid.sort_values().reset_index(drop=True)
    if len(sorted_vals) == 1:
        return float(sorted_vals.iloc[0])
    rank = (percentile / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    frac = rank - lo
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals.iloc[lo] * (1 - frac) + sorted_vals.iloc[hi] * frac)


def _validate_inputs(seasonal):
    """Section-14-style sanity checks on the season-filtered weather data,
    before it goes anywhere near the thermal model. Deliberately loose
    bounds (real physically-plausible ranges, not tight limits that could
    reject legitimate weather) - the point is to catch unit/parsing bugs,
    not to police normal Irish weather variability."""
    if (seasonal["wind_speed_ms"] < 0).any():
        raise SystemExit("negative wind_speed_ms present in the input data - "
                          "that's not physically valid, check the source CSV/units.")
    bad_dir = seasonal["wind_direction_deg_true"].dropna()
    if ((bad_dir < 0) | (bad_dir > 360)).any():
        raise SystemExit("wind_direction_deg_true outside 0-360 present in "
                          "the input data - check the source CSV/units.")
    temp = seasonal["air_temperature_c"]
    if ((temp < -30) | (temp > 45)).any():
        raise SystemExit("air_temperature_c outside a physically plausible "
                          "range for this location (-30C to 45C) - check the "
                          "source CSV/units before trusting this run.")


def main(line="5041-17010-2", season="winter", percentile="10",
         weather_csv=None, solar_csv=None):
    percentile = float(percentile)
    if not (0.0 <= percentile <= 100.0):
        raise SystemExit(f"percentile must be between 0 and 100, got {percentile}")

    if weather_csv is None:
        if line not in WEATHER_CSV_FOR_LINE:
            raise SystemExit(
                f"no weather CSV mapped for line '{line}' - add it to "
                f"WEATHER_CSV_FOR_LINE (and STATION_FOR_LINE) at the top of "
                f"this file, or pass --weather-csv explicitly.")
        weather_csv = WEATHER_CSV_FOR_LINE[line]
    if solar_csv is None:
        if line not in SOLAR_CSV_FOR_LINE:
            raise SystemExit(
                f"no solar CSV mapped for line '{line}' - add it to "
                f"SOLAR_CSV_FOR_LINE at the top of this file, or pass "
                f"--solar-csv explicitly.")
        solar_csv = SOLAR_CSV_FOR_LINE[line]

    station_id, station_name = STATION_FOR_LINE.get(line, ("?", "unmapped station"))
    line_azimuth_deg = LINE_AZIMUTH_FOR_LINE.get(line)

    print(f"line: {line}   weather station: {station_id} ({station_name})")

    df = load_observations(weather_csv)
    by_year = filter_to_target_year(df, TARGET_YEAR)
    seasonal = filter_to_season(by_year, season)

    # Section-1-style diagnostics: printed unconditionally, every run, so
    # it's impossible to accidentally be looking at the old multi-decade
    # distribution instead of TARGET_YEAR.
    print(f"year: {TARGET_YEAR}   season: {season}")
    print(f"observations: {len(seasonal)}")
    print(f"observation window: {seasonal['observed_at_utc'].min()} to "
          f"{seasonal['observed_at_utc'].max()}")

    _validate_inputs(seasonal)

    solar_df = load_solar(solar_csv)
    solar_df.attrs["source"] = solar_csv
    merged = merge_solar(seasonal, solar_df)

    detail = compute_hourly_rating(merged, line_azimuth_deg)
    detail["season"] = season
    # Column order matches this project's documented OUTPUT DATASET schema
    # exactly, so a reader can find a given field without hunting.
    detail = detail[[
        "observed_at_utc", "year", "season", "wind_speed_ms",
        "wind_direction_deg_true", "line_azimuth_deg", "wind_perpendicular_ms",
        "air_temperature_c", "global_solar_radiation_wm2",
        "convective_heat_loss_wm", "radiative_heat_loss_wm",
        "solar_heat_gain_wm", "net_heat_loss_wm", "rating_multiplier",
    ]]

    n_valid = int(detail["rating_multiplier"].notna().sum())
    if n_valid < 20:
        print(f"\nWARNING: only {n_valid} valid observation(s) available for "
              f"the percentile (of {len(detail)} in the season) - a thin "
              f"sample for a seasonal statistic; treat the result with "
              f"appropriate caution.")

    rep_mult = representative_multiplier(detail["rating_multiplier"], percentile=percentile)

    print(f"\nwind speed (m/s): min={merged['wind_speed_ms'].min():.2f} "
          f"max={merged['wind_speed_ms'].max():.2f} "
          f"mean={merged['wind_speed_ms'].mean():.2f}")
    valid_perp = detail["wind_perpendicular_ms"].dropna()
    if len(valid_perp):
        print(f"wind perpendicular to line (m/s): min={valid_perp.min():.2f} "
              f"max={valid_perp.max():.2f} mean={valid_perp.mean():.2f}")
    print(f"air temperature (C): min={merged['air_temperature_c'].min():.2f} "
          f"max={merged['air_temperature_c'].max():.2f} "
          f"mean={merged['air_temperature_c'].mean():.2f}")

    mults = detail["rating_multiplier"]
    print(f"\nper-observation rating multiplier distribution "
          f"({mults.notna().sum()} valid of {len(mults)}):")
    print(f"  min={mults.min():.3f}  "
          f"p5={representative_multiplier(mults, 5):.3f}  "
          f"p10={representative_multiplier(mults, 10):.3f}  "
          f"p25={representative_multiplier(mults, 25):.3f}  "
          f"p50={representative_multiplier(mults, 50):.3f}  "
          f"mean={mults.mean():.3f}  max={mults.max():.3f}")
    print(f"\nrepresentative multiplier (p{percentile:.0f}, study choice - "
          f"see representative_multiplier() docstring): {rep_mult:.4f}")

    out_path = os.path.join(
        ROOT, f"j_seasonal_dlr_{line}_{TARGET_YEAR}_{season}.csv")
    detail.to_csv(out_path, index=False)
    print(f"\nper-observation detail -> {out_path}")

    return rep_mult


if __name__ == "__main__":
    args = sys.argv[1:]
    weather_csv = None
    solar_csv = None
    if "--weather-csv" in args:
        i = args.index("--weather-csv")
        weather_csv = args[i + 1]
        del args[i:i + 2]
    if "--solar-csv" in args:
        i = args.index("--solar-csv")
        solar_csv = args[i + 1]
        del args[i:i + 2]
    result = main(*args, weather_csv=weather_csv, solar_csv=solar_csv)
    print(f"\n(representative_multiplier = {result:.4f})")
