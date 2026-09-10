"""(j) Dynamic Line Rating proxy: thermal-rating uplift on the target line.

    python examples/j_dlr_rating_sensitivity.py [SCENARIO] [SCOPE] [LINE]

Q3 ask: "How could Dynamic Line Rating reduce wind constraint on the model?"

DLR raises a conductor's real-time thermal rating based on live weather
(mainly wind speed cooling the conductor). This kit's gridkit.set_rating()
can only set ONE FIXED s_nom value, not an hour-by-hour weather-driven
series -- so this script tests "what if the rating were permanently
raised by X%" as a proxy for DLR, not a literal simulation of live
weather-based uplift. That distinction is stated explicitly in every
printout below and must be repeated in the writeup.

For each uplift factor, re-solves fresh (solve -> freeze_dispatch -> lpf,
in that exact order per gridkit's own warning) and reports:
  - hours_at_rating on the target line (from gridkit.line_loading)
  - MWh of wind actually recovered from dispatch-down (gridkit.dispatch_down)

Writes figures/j_dlr_sensitivity_<scenario>_<scope>.csv (long-form) and
.png (chart), matching the plot axes used in the Q1 thermal-rating chart
so the two can sit on the same figure.
"""

import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def _find_participant_kit_dir():
    """Locate the directory containing gridkit.py, whether this script is
    sitting at participant-kit/examples/ (the layout this file originally
    assumed) or flattened at the repo root (the layout actually committed
    on this branch - see Track A audit F-06). Tries this file's own
    directory first, then its parent, and raises a clear error rather than
    a confusing downstream ImportError if neither has gridkit.py.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    for candidate in (here, parent):
        if os.path.exists(os.path.join(candidate, "gridkit.py")):
            return candidate
    raise SystemExit(
        f"could not find gridkit.py next to this script or one directory "
        f"up (checked: {here}, {parent}). This script expects either the "
        f"participant-kit/examples/ layout or a flattened repo-root layout."
    )


KIT_ROOT = _find_participant_kit_dir()
sys.path.insert(0, KIT_ROOT)
import gridkit
import plotstyle

FIGURES = os.path.join(KIT_ROOT, "figures")

#: DLR uplift factors to test, as a proxy for a permanently higher rating.
#: Range chosen to match literature cited for real DLR pilots (TWENTIES
#: project: 10-15% average uplift; Malaysia pilot: up to 30%).
FACTORS = (0.00, 0.10, 0.20, 0.30)


def main(scenario="WP2033", scope="north-west", line=None):
    plotstyle.use()
    gridkit.quiet()

    # Establish the target line the same way Q1 did, if not given.
    if line is None:
        n0 = gridkit.load(scenario, scope)
        gridkit.solve(n0)
        gridkit.freeze_dispatch(n0)
        n0.lpf(n0.snapshots)
        loading0 = gridkit.line_loading(n0)
        line = loading0.max(axis=1).idxmax()
        print(f"no line given; using worst-loaded circuit from a fresh "
              f"solve: {line}\n")

    base_rating = None
    rows = []
    for factor in FACTORS:
        n = gridkit.load(scenario, scope)
        if base_rating is None:
            base_rating = float(n.lines.at[line, "s_nom"]
                                 if line in n.lines.index
                                 else n.transformers.at[line, "s_nom"])
        new_rating = base_rating * (1.0 + factor)
        gridkit.set_rating(n, line, new_rating)

        gridkit.solve(n)
        gridkit.freeze_dispatch(n)
        n.lpf(n.snapshots)

        loading = gridkit.line_loading(n)
        hours_at_rating = int((loading[line] >= 0.999).sum())

        dispatch_down = gridkit.dispatch_down(n)
        wind_down_mwh = float(
            dispatch_down.loc[dispatch_down["carrier"] == "wind",
                              "dispatch_down_mwh"].sum()
        ) if len(dispatch_down) else 0.0

        rows.append({
            "uplift_pct": factor * 100.0,
            "rating_mva": new_rating,
            "hours_at_rating": hours_at_rating,
            "wind_dispatch_down_mwh": wind_down_mwh,
        })
        print(f"uplift {factor:+.0%} -> rating {new_rating:.0f} MVA, "
              f"hours_at_rating {hours_at_rating}, "
              f"wind dispatch-down {wind_down_mwh:,.0f} MWh")

    table = pd.DataFrame(rows)
    os.makedirs(FIGURES, exist_ok=True)
    csv_path = os.path.join(
        FIGURES, f"j_dlr_sensitivity_{scenario}_{scope}.csv")
    table.to_csv(csv_path, index=False)
    print(f"\n-> {csv_path}")

    baseline_hours = table.loc[table["uplift_pct"] == 0, "hours_at_rating"].iloc[0]
    baseline_wind_down = table.loc[table["uplift_pct"] == 0,
                                   "wind_dispatch_down_mwh"].iloc[0]
    print(f"\nIMPORTANT CAVEAT: this uses gridkit.set_rating(), a single "
          f"fixed MVA value applied for the whole week. Real DLR varies "
          f"hour to hour with live weather (mainly wind speed cooling the "
          f"conductor). This tests 'what if the rating were permanently "
          f"raised by X%', not a literal simulation of weather-driven DLR. "
          f"State this explicitly in the writeup.")

    _draw(table, line, scenario, scope, baseline_hours, baseline_wind_down)
    return 0


def _draw(table, line, scenario, scope, baseline_hours, baseline_wind_down):
    fig, (left, right) = plt.subplots(1, 2, figsize=(11.0, 4.6))

    left.plot(table["uplift_pct"], table["hours_at_rating"],
              marker="o", color=plotstyle.CATEGORICAL[0], linewidth=1.8)
    left.set_xlabel("thermal rating uplift (%) — DLR proxy")
    left.set_ylabel(f"hours at rating on {line} (of 168)")
    left.set_title("constrained hours vs. rating uplift", fontsize=10)
    left.set_ylim(0, max(table["hours_at_rating"].max() * 1.15, 1))
    left.grid(axis="y", alpha=0.3)

    right.plot(table["uplift_pct"], table["wind_dispatch_down_mwh"],
               marker="o", color=plotstyle.STATUS["serious"], linewidth=1.8)
    right.set_xlabel("thermal rating uplift (%) — DLR proxy")
    right.set_ylabel("wind dispatch-down over the week (MWh)")
    right.set_title("wind recovered vs. rating uplift", fontsize=10)
    right.set_ylim(0, max(table["wind_dispatch_down_mwh"].max() * 1.15, 1))
    right.grid(axis="y", alpha=0.3)

    fig.suptitle(
        f"{scenario} {scope}: DLR rating-uplift proxy on {line}",
        x=0.012, ha="left", fontsize=12, fontweight="bold",
        color=plotstyle.INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = os.path.join(FIGURES, f"j_dlr_sensitivity_{scenario}_{scope}.png")
    fig.savefig(path, bbox_inches="tight")
    print(f"-> {path}")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
