"""(j.2) Apply a representative seasonal DLR (from real Met Eireann weather) to
one line, and compare against the static rating - CASE 1 (static) vs
CASE 2 (representative seasonal DLR), same generation scenario both times.

    python examples/j_apply_seasonal_dlr.py [SCOPE] [LINE] [SEASON] [PERCENTILE] [SCENARIO]
    python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 winter 10
    python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 summer 10

SEASON PICKS THE SCENARIO TOO - read this before running anything. The kit's
scenarios are WP2033 (winter peak) and SV2033 (summer valley): two different
generation scenarios, not one scenario run at two times of year. An earlier
version of this script defaulted to WP2033 regardless of season, which would
have applied a *summer* weather-derived rating to the *winter-peak* network -
wrong pairing. SEASON_SCENARIO below fixes that: season='winter' loads
WP2033, season='summer' loads SV2033, automatically, unless you pass a
SCENARIO explicitly to override it (e.g. to deliberately test a mismatched
pairing).

WIND GENERATION != WIND WEATHER - read this before changing anything below.
The network's generation scenario is untouched by this script. gridkit.load()
returns the network exactly as shipped, with its own modelled wind-farm
output; nothing here recalculates that output from Met Eireann wind speed.
The ONLY thing this script changes is one line's static thermal rating
(s_nom), via gridkit.set_rating - the same mechanism
g_thermal_rating_sensitivity.py already uses for its 1.1x/1.2x/1.3x sweep,
and the same mechanism Q3's own brief (Chibuikeim's Dynamic Line Rating
task) describes. The one difference: instead of a round arbitrary factor
(+10%/+20%/+30%), the factor here comes from j_seasonal_weather_rating.py's
representative-seasonal-weather calculation on real Met Eireann data - a
direct, better-grounded answer to the exact limitation Q3's own brief tells
you to flag ("you're really testing what if the rating were permanently
higher as a proxy, not literally simulating live weather-based uplift" -
true of a bare +10/20/30% sweep, not true of a representative-seasonal-
weather-derived factor, though it's still a single constant per season
rather than an hour-by-hour series - see this module's next paragraph).

This applies ONE constant multiplier across the whole scenario - a
representative seasonal rating, not a genuinely time-varying hourly DLR
series (see j_seasonal_weather_rating.py's module docstring for why: the
network's snapshots are a modelled week, not 168 real consecutive hours, so
there is no honest way to vary the rating hour-by-hour against them).

Mechanics mirror g_thermal_rating_sensitivity.py exactly: solve -> freeze_
dispatch -> lpf, on a FRESH network copy per case (not stacking the DLR
case on top of the static one), since a changed rating on the monitored
line can change what the LOPF dispatches elsewhere in the network.

"DISPATCH-DOWN" IS NOT CURTAILMENT - straight from gridkit's own README,
read in full before this line existed: gridkit.dispatch_down(n) reports wind
and solar offered and not taken, which splits into constraint-based
(stranded behind a binding line rating - this is what widening a rating can
recover) and surplus-based (more supply than demand can absorb that hour, no
network topology fixes it - WP2033 alone carries 42.6 GW of plant against an
8.8 GW peak, so a lot of any dispatch-down total is this). It is explicitly
*not* curtailment in the SEM/EirGrid sense - no SNSP constraint, no inertia
constraint, no unit commitment in this model - so don't present the MWh
figure below against a published EirGrid curtailment number. This script
reports the simple before/after total (matching what Q3's brief asks for:
"MWh actually saved... at each rating level") - it does NOT isolate the
constraint-based component the way examples/b_lopf_dispatch.py's
_congestion_share() does (lift every rating, re-solve, take the
difference). The before/after total here is still a fair, honest answer to
"did widening this one line help, network-wide" - just don't call it
curtailment avoided, call it dispatch-down avoided, and cite this caveat.

OUTPUT SCHEMA MATCHES g_thermal_sensitivity_WP2033_north-west.csv on purpose
(line, rating_factor, s_nom_mva, max_loading, hours_at_rating) plus
dispatch_down_mwh. Rows from this script's output can be appended straight
onto that existing sensitivity table/chart - a winter and a summer row
alongside the existing 1.0/1.1/1.2/1.3 rows, exactly as Q3's brief asks for
("one more line" on the existing chart), rather than a separate table.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gridkit
import j_seasonal_weather_rating as weather

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Which network scenario each season pairs with by default. WP = winter
#: peak, SV = summer valley (gridkit.SCENARIOS: WP2024, SV2024, WP2033,
#: SV2033) - see this module's docstring for why this mapping exists.
SEASON_SCENARIO = {
    "winter": "WP2033",
    "summer": "SV2033",
}


def total_dispatch_down_mwh(network):
    """gridkit.dispatch_down(n) returns a DataFrame indexed by generator with
    columns offered_mwh, dispatched_mwh, dispatch_down_mwh, dispatch_down_pct,
    carrier (confirmed against the real gridkit.py - see this module's
    docstring on why that matters). The network-wide total is the sum of
    just the dispatch_down_mwh column - NOT every numeric column, which
    would wrongly add a percentage into a MWh total."""
    lost = gridkit.dispatch_down(network)
    if not len(lost):
        return 0.0
    return float(lost["dispatch_down_mwh"].sum())


def run_case(scenario, scope, line, rating_mva=None):
    """Solves the network once, optionally overriding one line's static
    rating first (rating_mva=None leaves the shipped static rating as-is).
    Returns (applied_rating_mva, hours_at_rating, max_loading, dispatch_down_mwh)."""
    gridkit.quiet()
    n = gridkit.load(scenario, scope)   # fresh copy - see module docstring
    if rating_mva is not None:
        gridkit.set_rating(n, line, rating_mva)

    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    loading = gridkit.line_loading(n)
    hours_at_rating = int((loading[line] >= 0.999).sum())
    max_loading = float(loading[line].max())
    applied_rating = float(n.lines.at[line, "s_nom"])
    dispatch_down_mwh = total_dispatch_down_mwh(n)

    return applied_rating, hours_at_rating, max_loading, dispatch_down_mwh


def main(scope="north-west", line="5041-17010-2", season="winter",
         percentile="10", scenario=None):
    if scenario is None:
        scenario = SEASON_SCENARIO.get(season, "WP2033")
        print(f"season='{season}' -> scenario='{scenario}' "
              f"(pass an explicit scenario to override)")

    print(f"\ncase 1/2: static rating (as shipped) - {scenario} {scope}")
    static_rating, static_hours, static_max_loading, static_mwh = run_case(
        scenario, scope, line)

    # --- weather -> representative seasonal multiplier (independent of PyPSA) ---
    rep_mult = weather.main(line=line, season=season, percentile=percentile)
    dlr_rating = static_rating * rep_mult

    print(f"\ncase 2/2: representative seasonal DLR ({season}, p{percentile})")
    _, dlr_hours, dlr_max_loading, dlr_mwh = run_case(
        scenario, scope, line, rating_mva=dlr_rating)

    pct_change = (rep_mult - 1.0) * 100.0
    mwh_diff = static_mwh - dlr_mwh

    print(f"\n{'='*70}")
    print(f"static vs representative-seasonal-DLR comparison: {line} "
          f"({scenario} {scope}, season={season}, p{percentile})")
    print(f"{'='*70}")
    summary = pd.DataFrame({
        "static (as shipped)": {
            "rating_mva": round(static_rating, 1),
            "hours_at_rating": static_hours,
            "max_loading": round(static_max_loading, 3),
            "dispatch_down_mwh": round(static_mwh, 1),
        },
        "representative seasonal DLR": {
            "rating_mva": round(dlr_rating, 1),
            "hours_at_rating": dlr_hours,
            "max_loading": round(dlr_max_loading, 3),
            "dispatch_down_mwh": round(dlr_mwh, 1),
        },
    })
    print(summary.to_string())
    print(f"\nrating_multiplier: {rep_mult:.4f}")
    print(f"change vs static: {pct_change:+.1f}%  "
          f"({static_rating:.1f} MVA -> {dlr_rating:.1f} MVA)")
    print(f"hours_at_rating: {static_hours} -> {dlr_hours} "
          f"({static_hours - dlr_hours:+d})")
    print(f"dispatch-down (NOT curtailment - see module docstring): "
          f"{static_mwh:,.1f} -> {dlr_mwh:,.1f} MWh ({mwh_diff:+,.1f} MWh)")

    # Row shaped to match g_thermal_sensitivity_WP2033_north-west.csv's own
    # columns (line, rating_factor, s_nom_mva, max_loading, hours_at_rating)
    # plus dispatch_down_mwh - append this straight onto that table/chart as
    # the weather-derived counterpart to its arbitrary 1.1/1.2/1.3 rows.
    sensitivity_row = pd.DataFrame([{
        "line": line,
        "rating_factor": round(rep_mult, 4),
        "s_nom_mva": round(dlr_rating, 1),
        "max_loading": round(dlr_max_loading, 3),
        "hours_at_rating": dlr_hours,
        "dispatch_down_mwh": round(dlr_mwh, 1),
        "season": season,
        "scenario": scenario,
        "percentile": percentile,
    }])

    out_path = os.path.join(ROOT, f"j_seasonal_dlr_comparison_{line}_{season}.csv")
    summary.to_csv(out_path)
    row_path = os.path.join(ROOT, f"j_seasonal_dlr_row_{line}_{season}.csv")
    sensitivity_row.to_csv(row_path, index=False)
    print(f"\ncomparison table -> {out_path}")
    print(f"sensitivity-table-shaped row (append to g_'s CSV) -> {row_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
