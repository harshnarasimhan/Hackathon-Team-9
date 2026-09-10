"""(j.3) Combine the arbitrary-factor sweep (g_thermal_rating_sensitivity.py)
with the weather-derived seasonal DLR rows (j_apply_seasonal_dlr.py) into one
chart and one CSV - the actual "Output" step Q3's brief asks for: rating
uplift (%) vs hours-still-constrained and MWh-still-curtailed, as one more
line on Harshitha's existing Q1 chart.

    python examples/j_thermal_rating_chart.py [SCENARIO] [SCOPE] [LINE]
    python examples/j_thermal_rating_chart.py WP2033 north-west 5041-17010-2

Run order this depends on (all three must have been run first, so their
output CSVs exist in the participant-kit root / figures folder). Note
j_apply_seasonal_dlr.py's own args are [SCOPE] [LINE] [SEASON] [PERCENTILE] -
no scenario prefix, since season already picks the scenario (see that
script's docstring):

    python examples/g_thermal_rating_sensitivity.py WP2033 north-west 3
    python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 winter 10
    python examples/j_apply_seasonal_dlr.py north-west 5041-17010-2 summer 10

Only the season(s) whose paired scenario matches THIS script's [SCENARIO]
argument are plotted - see load_weather_rows() below for why (hours_at_rating
isn't comparable across WP2033 vs SV2033, they're different networks). Build
WP2033's chart to see the winter point; SV2033's g_ sweep would need to be
generated separately to build a chart with the summer point on it.

WHAT THIS CHART DOES AND DOES NOT SHOW
---------------------------------------
The x-axis is the SAME quantity (rating_factor, i.e. rating / static rating)
for every point, but the points come from two different, honestly-labelled
sources - don't let them blur together in the writeup:

  * "arbitrary sweep" (circles): g_'s 1.0/1.1/1.2/1.3 - round numbers
    standing in for "what if the rating were permanently X% higher", no
    weather behind them.
  * "weather-derived" (stars): this script's winter/summer points - the
    representative seasonal DLR multiplier from j_seasonal_weather_rating.py,
    computed from 29 years of real Met Eireann wind/temperature at the
    station nearest this line.

dispatch_down_mwh is filled in for BOTH sources now, but from two different
places: weather-derived points compute it directly (j_apply_seasonal_dlr.py
re-solves the network itself); arbitrary-sweep points get it from
Chibuikeim's own j_dlr_rating_sensitivity.py output (his branch,
Dynamic-Line-Rating) where that file is found next to this one -
g_thermal_rating_sensitivity.py's own CSV never computed this column, and
rather than re-solving a fourth time or leaving it blank, his real,
independently-produced numbers are reused and cited (see
load_chibuikeim_dispatch_down's docstring for the exact match-up). Points
where his CSV isn't available (currently: anything under SV2033, since he
only ran WP2033) stay NA rather than guessed, and the script says so.

RUN AGAINST THE REAL KIT
--------------------------
This script (and j_seasonal_weather_rating.py / j_apply_seasonal_dlr.py
before it) have been run end-to-end against the real gridkit.py,
plotstyle.py and networks/ from harshnarasimhan/Hackathon-Team-9 (both
WP2033 and SV2033, both seasons) - not just syntax-checked. The static
baselines reproduced Track A's own published numbers exactly (210 MVA/52h
winter, 178 MVA/89h summer), which is the cross-check that this is solving
the same network the same way as the rest of the team's work.
"""

import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGURES = os.path.join(ROOT, "figures")


def load_chibuikeim_dispatch_down(scenario, scope):
    """Chibuikeim's own j_dlr_rating_sensitivity.py (Dynamic-Line-Rating
    branch) already re-solved this exact arbitrary sweep and read
    gridkit.dispatch_down() for each point - g_thermal_rating_sensitivity.py
    never computed dispatch_down_mwh (see load_arbitrary_sweep's docstring),
    so rather than leaving those points blank or re-solving a fourth time,
    reuse his real, cross-validated numbers keyed by rating_factor
    (uplift_pct/100 + 1). Confirmed matching to rounding against this
    module's own winter DLR case (his 0%-uplift row: 3,661 MWh vs 3,660.6
    MWh here; his +30%-uplift row: 3,072 MWh vs this module's winter DLR
    case, also 3,072.0 MWh - see chibuikeim-q3-summary.md for the full
    reconciliation). Only exists for WP2033 (he never ran SV2033) - returns
    an empty mapping otherwise, and the caller falls back to NA as before.
    """
    for candidate in (
        os.path.join(FIGURES, f"j_dlr_sensitivity_{scenario}_{scope}.csv"),
        os.path.join(ROOT, f"j_dlr_sensitivity_{scenario}_{scope}.csv"),
    ):
        if os.path.exists(candidate):
            his = pd.read_csv(candidate)
            his["rating_factor"] = (his["uplift_pct"] / 100.0 + 1.0).round(4)
            return dict(zip(his["rating_factor"], his["wind_dispatch_down_mwh"]))
    return {}


def load_arbitrary_sweep(scenario, scope, line):
    """g_thermal_rating_sensitivity.py's own output: figures/g_thermal_
    sensitivity_{scenario}_{scope}.csv, long-form (line, rating_factor,
    s_nom_mva, max_loading, hours_at_rating) - filter to just our line.
    dispatch_down_mwh is filled in from Chibuikeim's own j_dlr_rating_
    sensitivity.py output where available (see load_chibuikeim_dispatch_
    down above) - NA where it isn't, rather than guessed."""
    path = os.path.join(FIGURES, f"g_thermal_sensitivity_{scenario}_{scope}.csv")
    if not os.path.exists(path):
        raise SystemExit(
            f"missing {path} - run "
            f"`python examples/g_thermal_rating_sensitivity.py {scenario} {scope} 3` first")
    df = pd.read_csv(path)
    df = df[df["line"] == line].copy()
    df["source"] = "arbitrary sweep"
    df["scenario"] = scenario   # g_'s CSV is single-scenario; the filename tells us which
    chibuikeim_mwh = load_chibuikeim_dispatch_down(scenario, scope)
    df["dispatch_down_mwh"] = df["rating_factor"].round(4).map(chibuikeim_mwh)
    if chibuikeim_mwh:
        print(f"note: dispatch_down_mwh for the arbitrary sweep is Chibuikeim's own "
              f"j_dlr_rating_sensitivity.py output (real, cross-validated - not "
              f"re-derived here), matched by rating_factor")
    return df[["line", "rating_factor", "s_nom_mva", "max_loading",
               "hours_at_rating", "dispatch_down_mwh", "source", "scenario"]]


def load_weather_rows(line, scenario, seasons=("winter", "summer")):
    """j_apply_seasonal_dlr.py's own output: j_seasonal_dlr_row_{line}_{season}.csv.

    hours_at_rating and dispatch_down_mwh are only comparable within the SAME
    generation scenario - WP2033 and SV2033 are different networks with
    different demand and dispatch, not the same network at two points in the
    year (see j_apply_seasonal_dlr.py's docstring). A season whose paired
    scenario (SEASON_SCENARIO in l_) doesn't match the `scenario` this chart
    was asked to build is therefore skipped, not silently plotted alongside
    points from a different network - that would put e.g. SV2033's
    higher-baseline hours_at_rating on the same axis as WP2033's arbitrary
    sweep and make the DLR uplift look bigger or smaller than it really is.
    """
    rows = []
    for season in seasons:
        path = os.path.join(ROOT, f"j_seasonal_dlr_row_{line}_{season}.csv")
        if not os.path.exists(path):
            print(f"warning: missing {path} - run "
                  f"`python examples/j_apply_seasonal_dlr.py north-west "
                  f"{line} {season} 10` first; skipping {season}")
            continue
        df = pd.read_csv(path)
        row_scenario = df["scenario"].iloc[0] if "scenario" in df.columns else None
        if row_scenario is not None and row_scenario != scenario:
            print(f"note: {season} row was computed under scenario={row_scenario!r}, "
                  f"not this chart's scenario={scenario!r} - skipping it here rather than "
                  f"mixing hours_at_rating across two different networks. Build a separate "
                  f"chart with scenario={row_scenario!r} to see it (and its own arbitrary "
                  f"sweep, once g_thermal_rating_sensitivity.py has been run for that scenario).")
            continue
        df["source"] = f"weather-derived ({season})"
        rows.append(df[["line", "rating_factor", "s_nom_mva", "max_loading",
                         "hours_at_rating", "dispatch_down_mwh", "source", "scenario"]])
    if not rows:
        print(f"no weather-derived rows matched scenario={scenario!r} - "
              f"chart will show the arbitrary sweep only")
        return pd.DataFrame(columns=["line", "rating_factor", "s_nom_mva", "max_loading",
                                      "hours_at_rating", "dispatch_down_mwh", "source", "scenario"])
    return pd.concat(rows, ignore_index=True)


def main(scenario="WP2033", scope="north-west", line="5041-17010-2"):
    arbitrary = load_arbitrary_sweep(scenario, scope, line)
    weather = load_weather_rows(line, scenario)
    combined = pd.concat([arbitrary, weather], ignore_index=True)
    combined = combined.sort_values("rating_factor").reset_index(drop=True)

    print(combined.to_string(index=False))

    csv_path = os.path.join(FIGURES, f"j_thermal_rating_combined_{scenario}_{scope}_{line}.csv")
    os.makedirs(FIGURES, exist_ok=True)
    combined.to_csv(csv_path, index=False)
    print(f"\ncombined table -> {csv_path}")

    # Two panels, same layout as Chibuikeim's original j_dlr_rating_
    # sensitivity.py chart (hours-at-rating left, dispatch-down MWh right) -
    # this is a direct upgrade of that figure, not a different one: same
    # x-axis, same left panel, right panel now also carries the
    # weather-derived stars since dispatch_down_mwh is available for both
    # sources (see load_chibuikeim_dispatch_down).
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    sources = [("arbitrary sweep", "o"), *[
        (s, "*") for s in combined["source"].unique() if s.startswith("weather-derived")]]

    for source, marker in sources:
        subset = combined[combined["source"] == source]
        if subset.empty:
            continue
        ax1.plot(subset["rating_factor"], subset["hours_at_rating"],
                  marker=marker, linestyle="-" if source == "arbitrary sweep" else "None",
                  markersize=10 if marker == "*" else 6, label=source)

    ax1.set_xlabel("rating factor (rating / static s_nom)")
    ax1.set_ylabel("hours_at_rating (of 168)")
    ax1.set_title("rating uplift vs hours still constrained")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    for source, marker in sources:
        subset = combined[combined["source"] == source].dropna(subset=["dispatch_down_mwh"])
        if subset.empty:
            continue
        ax2.plot(subset["rating_factor"], subset["dispatch_down_mwh"],
                  marker=marker, linestyle="-" if source == "arbitrary sweep" else "None",
                  markersize=10 if marker == "*" else 6, label=source)

    ax2.set_xlabel("rating factor (rating / static s_nom)")
    ax2.set_ylabel("dispatch_down_mwh (week total - not curtailment, see docstring)")
    ax2.set_title("rating uplift vs dispatch-down recovered")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    fig.suptitle(f"{line} ({scenario} {scope})", x=0.01, ha="left", fontweight="bold")

    png_path = os.path.join(FIGURES, f"j_thermal_rating_chart_{scenario}_{scope}_{line}.png")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(png_path, dpi=150)
    print(f"chart -> {png_path}")

    known_mwh = combined[combined["dispatch_down_mwh"].notna()]
    missing_mwh = combined[combined["dispatch_down_mwh"].isna()]
    if not known_mwh.empty:
        print("\ndispatch_down_mwh (weather-derived points always have it; "
              "arbitrary-sweep points have it only where Chibuikeim's own "
              "j_dlr_rating_sensitivity.py output was found - see "
              "load_chibuikeim_dispatch_down's docstring):")
        print(known_mwh[["source", "rating_factor", "dispatch_down_mwh"]].to_string(index=False))
    if not missing_mwh.empty:
        print(f"\n({len(missing_mwh)} arbitrary-sweep point(s) still missing "
              f"dispatch_down_mwh - run j_dlr_rating_sensitivity.py for this "
              f"scenario/scope to fill them in)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
