"""(j.1) Representative seasonal weather -> dynamic line rating (DLR) multiplier.

    python examples/j_seasonal_weather_rating.py [LINE] [SEASON] [PERCENTILE]
    python examples/j_seasonal_weather_rating.py 5041-17010-2 winter 10
    python examples/j_seasonal_weather_rating.py 5041-17010-2 all 10

WIND GENERATION != WIND WEATHER. This script has nothing to do with the
network's wind farm output (that's a modelled seasonal generation
scenario/forecast - WP2033 is "2033 winter peak" - and stays exactly as
shipped). This script uses independent, real Met Eireann weather
observations for one purpose only: estimating how much *cooling* a specific
overhead line gets, and therefore how much thermal (ampacity) headroom it
has compared with its static nameplate rating. The two data sources are
never mixed - see j_apply_seasonal_dlr.py's module docstring for how the
result of this script is applied without touching generation at all.

WHY "REPRESENTATIVE SEASONAL", NOT HOUR-BY-HOUR
-------------------------------------------------
An earlier version of this pipeline tried to align Met Eireann's real
timestamped weather hour-by-hour against the network's 168 snapshots
(snapshot 1 <-> weather hour 1, snapshot 2 <-> weather hour 2, ...). That is
wrong and has been discarded: the network's snapshots are a MODELLED
SCENARIO WEEK (a representative winter- or summer-peak profile), not 168
consecutive real calendar hours, so there is no real hour that snapshot 1
"is". Pretending otherwise would let a real calm hour sit next to a
snapshot where the model assumed high wind generation, or vice versa, for
no physical reason.

What we do instead: gather real Met Eireann observations from the same
broad SEASON as the generation scenario, compute what this line's thermal
rating would have been in each of those real hours, and collapse that
distribution down to ONE representative number - a single seasonal DLR
multiplier - which is what actually gets applied to the network (see
j_apply_seasonal_dlr.py). That's a defensible claim: "here is a realistic
rating for this line under representative winter weather." It is NOT a
claim that any particular network snapshot corresponds to any particular
real hour.

WHAT'S CURRENTLY AVAILABLE FROM MET EIREANN (read this before trusting any
number this script prints)
-----------------------------------------------------------------------
Station 104, Finner Camp, Co. Donegal (54.4939 N, -8.2431 W) - the nearest
Met Eireann synoptic station to Ballyshannon / Cathaleen's Fall / Srananagh,
i.e. both ends of the target line 5041-17010-2. Two sources were used, and
it matters which one a given CSV came from:

  * finner_camp_historical_hourly.csv (the default, WEATHER_CSV_FOR_LINE
    below) - Met Eireann's real historical archive for this station
    ("Finner Hourly Data", downloaded by hand from
    https://data.gov.ie/dataset/finner-hourly-data - it's blocked from
    automated fetching by robots.txt, both there and at the direct CSV
    host, so this file has to be re-downloaded by hand if it needs
    refreshing). 173,818 real hourly observations, 1997-10-01 to
    2026-09-01 - 41,451 of them in winter (Dec/Jan/Feb) and 44,904 in
    summer (Jun/Jul/Aug), so --season winter and --season summer both
    have a real, many-year sample to compute a percentile over, not a
    handful of days. Columns: wind_speed (mean hourly, converted from the
    source's knots), wind_direction, air_temperature. No wind_gust column
    in this dataset (the archive only carries mean hourly speed, not
    gust) - left blank; nothing in this script's thermal calculation uses
    gust anyway.
  * finner_camp_hourly_met_eireann.csv - Met Eireann's LIVE EDR API
    (collection observations-swob-nrt-60min), a rolling near-real-time
    feed, not an archive. Useful only for "current conditions right now"
    (pass --season all against it) since it can't yet cover a full
    winter or summer - keep it around for that purpose, but it is not
    the default for line 5041-17010-2 any more now that the real
    historical file exists.

  Neither source has global_solar_radiation_energy pulled in yet (it's
  available at the live API level, hourly total J/cm^2, but not in either
  CSV) - the solar heat-gain term below defaults to 0 until that column
  is added (see load_observations()'s docstring for the column name to
  add it under).

Do not add temperature/solar/etc. assumptions beyond what's listed above -
if a future run has more columns available, extend ASSUMED_PARAMS and the
heat-loss calculation, don't guess values that were never measured.
"""

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Which weather CSV backs which monitored line. Extend this as other
#: teammates' target lines get their own nearest station - do NOT apply
#: Finner Camp's weather to a line near a different station without adding
#: it here explicitly, since "nearest station" varies by line.
WEATHER_CSV_FOR_LINE = {
    "5041-17010-2": os.path.join(ROOT, "finner_camp_historical_hourly.csv"),
}

#: Weather station used per line, for the printed report (id -> human name).
STATION_FOR_LINE = {
    "5041-17010-2": ("104", "Finner Camp, Co. Donegal"),
}

#: month-of-year buckets used by --season. "all" (below, handled specially)
#: skips filtering entirely and uses every observation in the CSV.
SEASON_MONTHS = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}

#: -----------------------------------------------------------------------
#: Conductor / rating-reference assumptions. THESE ARE ASSUMED, not read
#: from the PyPSA network - the network's line table (as shipped in this
#: kit) carries s_nom (MVA) and per-unit electrical parameters (r, x, b)
#: for the DC power-flow approximation; it does not carry physical
#: conductor properties (diameter, material, emissivity) or the ambient
#: conditions the static rating was calculated under, and nothing in the
#: kit's own docs states them. Every value below is a stated, typical
#: assumption for an overhead 110/220kV circuit of this kind - swap in the
#: real values if/when the network's actual conductor spec is known.
#: -----------------------------------------------------------------------
ASSUMED_PARAMS = {
    "conductor_diameter_m": 0.0286,   # typical ACSR "Zebra" 400 mm^2 overhead conductor
    "emissivity": 0.5,                # moderately weathered conductor surface, 0-1 scale
    "absorptivity": 0.5,              # solar absorptivity; only used if solar data is present
    "max_conductor_temp_c": 75.0,     # typical ACSR continuous thermal design limit
    "reference_wind_speed_ms": 0.6,   # wind speed assumed for the STATIC nameplate rating
    "reference_ambient_temp_c": 20.0, # ambient temp assumed for the STATIC nameplate rating
    "wind_angle_correction": 1.0,     # assume wind perpendicular to the line (worst-case/
                                       # conservative default - we don't have line azimuth
                                       # to compute the real IEEE738 angle-of-attack factor)
}

SIGMA = 5.670374e-8   # Stefan-Boltzmann constant, W/(m^2 K^4) - exact, not assumed
K_AIR = 0.0270         # W/(m.K), representative air thermal conductivity (not temp-varying -
                       # stated simplification; real IEEE738 varies this with film temperature)
NU_AIR = 1.60e-5       # m^2/s, representative air kinematic viscosity (same simplification)


def load_observations(csv_path):
    """Reads a weather CSV in the shape finner_camp_hourly_met_eireann.csv is in:
    observed_at_utc, wind_speed_kts, wind_speed_ms, wind_gust_kts, wind_gust_ms,
    wind_direction_deg_true, air_temperature_c.

    To add solar radiation once it's pulled from the API: add a
    'global_solar_radiation_wm2' column (average W/m^2 over the hour - convert
    from Met Eireann's hourly-total J/cm^2 via wm2 = joules_per_cm2 * 10000/3600)
    and heat_loss_wm() below will pick it up automatically.
    """
    df = pd.read_csv(csv_path, parse_dates=["observed_at_utc"])
    df["month"] = df["observed_at_utc"].dt.month
    return df


def filter_season(df, season):
    """Restrict observations to the given season's months. season='all' skips
    filtering entirely (explicit opt-in to using whatever is available,
    regardless of season - use this only when you know the data doesn't yet
    cover the target season, and say so in the writeup, per this module's
    docstring)."""
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
            f"no observations fall in season='{season}' (months {months}) - "
            f"the weather CSV only covers "
            f"{df['observed_at_utc'].min()} to {df['observed_at_utc'].max()}. "
            f"This is expected right now: the Met Eireann feed we have is a "
            f"rolling ~5-6 day near-real-time window, not a historical "
            f"archive, so it can't yet supply real winter or summer data "
            f"out of season. Either re-run with season='all' (and label the "
            f"result as 'current conditions', not seasonal, in the writeup), "
            f"or supply a --weather-csv that actually covers the target "
            f"season (e.g. Met Eireann's historical Finner Hourly Data).")
    return filtered


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


def heat_loss_wm(wind_speed_ms, air_temp_c, solar_wm2=0.0, params=ASSUMED_PARAMS):
    """Conductor heat LOSS (convective + radiative), in W/m, at the given wind
    speed and ambient temperature, holding the conductor at its assumed max
    temperature. Also nets off solar heat GAIN if solar_wm2 is provided
    (defaults to 0 - see this module's docstring on why solar isn't wired up
    yet). Returns (pc, pr, ps) in W/m so callers can inspect each term.

    Convection: Hilpert cylinder-in-crossflow correlation (see
    nusselt_hilpert). Radiation: exact Stefan-Boltzmann physics. Both are
    evaluated at max_conductor_temp_c, which is what "thermal rating" means:
    the current at which the conductor sits at its temperature LIMIT, not
    its temperature right now.
    """
    d = params["conductor_diameter_m"]
    tc_max_c = params["max_conductor_temp_c"]

    v_eff = max(wind_speed_ms, 0.1)  # avoid Re=0; still allow near-still-air convection
    re = v_eff * d / NU_AIR
    nu = nusselt_hilpert(re) * params["wind_angle_correction"]
    h_c = nu * K_AIR / d
    dt = max(tc_max_c - air_temp_c, 0.01)
    pc = h_c * 3.141592653589793 * d * dt  # convective loss, W/m

    tc_k = tc_max_c + 273.15
    ta_k = air_temp_c + 273.15
    pr = params["emissivity"] * SIGMA * 3.141592653589793 * d * (tc_k**4 - ta_k**4)  # radiative loss, W/m

    ps = params["absorptivity"] * d * solar_wm2  # solar gain, W/m (0 unless solar_wm2 given)

    return pc, pr, ps


def rating_multiplier_series(df, params=ASSUMED_PARAMS):
    """One thermal-rating multiplier per observation row (dynamic rating /
    static rating). Ratio form means the conductor's electrical resistance
    never has to be known: current ~ sqrt(net heat loss / resistance), and
    resistance is the same (evaluated at the same max_conductor_temp_c) in
    both the numerator and the reference/static condition, so it cancels.
    """
    ref_pc, ref_pr, ref_ps = heat_loss_wm(
        params["reference_wind_speed_ms"], params["reference_ambient_temp_c"],
        solar_wm2=0.0, params=params)
    ref_net = ref_pc + ref_pr - ref_ps

    solar_col = "global_solar_radiation_wm2"
    has_solar = solar_col in df.columns

    def _row_multiplier(row):
        solar = float(row[solar_col]) if has_solar else 0.0
        pc, pr, ps = heat_loss_wm(row["wind_speed_ms"], row["air_temperature_c"],
                                   solar_wm2=solar, params=params)
        net = pc + pr - ps
        return (net / ref_net) ** 0.5

    return df.apply(_row_multiplier, axis=1)


def representative_multiplier(multipliers, percentile=10):
    """Collapses a season's worth of per-hour multipliers into ONE
    representative value, by calculating the multiplier PER OBSERVATION
    first and taking a percentile of the resulting distribution - not by
    averaging the raw weather first and running it through the thermal
    model once (that would be physically wrong, since heat loss is a
    non-linear function of wind speed and temperature; the average of the
    ratings is not the rating of the average weather).

    Why percentile 10, not the mean: this multiplier is going to stand in
    for a transmission thermal CONSTRAINT for an entire season. The mean
    rating is, by construction, exceeded only about half the time within
    that season - using it would mean the line is silently over-rated on
    below-average-wind hours roughly half the season. Taking a low
    percentile instead (10th percentile: the rating that real conditions
    matched or beat on ~90% of the season's observed hours) is the same
    "exceedance" logic utilities and CIGRE-style ambient-adjusted/seasonal
    ratings use, and is directly analogous to the P90 convention used for
    wind-resource estimates in project finance - a number you can reasonably
    rely on being available, not just an average. It is a default, not a
    law: pass a different --percentile (e.g. 50 for a central estimate, or
    5 for a more conservative one) if the project's methodology calls for
    something else; nothing in the shared kit or task briefs specifies a
    required statistic, so this default is Lucy's own documented choice,
    not an existing project convention being overridden.
    """
    sorted_vals = multipliers.sort_values().reset_index(drop=True)
    if len(sorted_vals) == 1:
        return float(sorted_vals.iloc[0])
    rank = (percentile / 100.0) * (len(sorted_vals) - 1)
    lo = int(rank)
    frac = rank - lo
    hi = min(lo + 1, len(sorted_vals) - 1)
    return float(sorted_vals.iloc[lo] * (1 - frac) + sorted_vals.iloc[hi] * frac)


def main(line="5041-17010-2", season="winter", percentile="10", weather_csv=None):
    percentile = float(percentile)

    if weather_csv is None:
        if line not in WEATHER_CSV_FOR_LINE:
            raise SystemExit(
                f"no weather CSV mapped for line '{line}' - add it to "
                f"WEATHER_CSV_FOR_LINE (and STATION_FOR_LINE) at the top of "
                f"this file, or pass --weather-csv explicitly.")
        weather_csv = WEATHER_CSV_FOR_LINE[line]

    station_id, station_name = STATION_FOR_LINE.get(line, ("?", "unmapped station"))

    df = load_observations(weather_csv)
    seasonal = filter_season(df, season)
    mults = rating_multiplier_series(seasonal)
    rep_mult = representative_multiplier(mults, percentile=percentile)

    print(f"line: {line}   weather station: {station_id} ({station_name})")
    print(f"season filter: {season}   observations used: {len(seasonal)} "
          f"(of {len(df)} total in {os.path.basename(weather_csv)})")
    print(f"observation window: {seasonal['observed_at_utc'].min()} to "
          f"{seasonal['observed_at_utc'].max()}")
    print(f"wind speed (m/s): min={seasonal['wind_speed_ms'].min():.2f} "
          f"max={seasonal['wind_speed_ms'].max():.2f} "
          f"mean={seasonal['wind_speed_ms'].mean():.2f}")
    print(f"air temperature (C): min={seasonal['air_temperature_c'].min():.2f} "
          f"max={seasonal['air_temperature_c'].max():.2f} "
          f"mean={seasonal['air_temperature_c'].mean():.2f}")
    print(f"\nper-observation rating multiplier distribution:")
    print(f"  min={mults.min():.3f}  p10={representative_multiplier(mults, 10):.3f}  "
          f"p50={representative_multiplier(mults, 50):.3f}  "
          f"mean={mults.mean():.3f}  max={mults.max():.3f}")
    print(f"\nrepresentative seasonal multiplier (p{percentile:.0f}): {rep_mult:.4f}")

    out_path = os.path.join(
        ROOT, f"j_seasonal_dlr_{line}_{season}.csv")
    pd.DataFrame({
        "observed_at_utc": seasonal["observed_at_utc"],
        "wind_speed_ms": seasonal["wind_speed_ms"],
        "air_temperature_c": seasonal["air_temperature_c"],
        "rating_multiplier": mults,
    }).to_csv(out_path, index=False)
    print(f"\nper-observation detail -> {out_path}")

    return rep_mult


if __name__ == "__main__":
    args = sys.argv[1:]
    weather_csv = None
    if "--weather-csv" in args:
        i = args.index("--weather-csv")
        weather_csv = args[i + 1]
        del args[i:i + 2]
    result = main(*args, weather_csv=weather_csv)
    print(f"\n(representative_multiplier = {result:.4f})")
