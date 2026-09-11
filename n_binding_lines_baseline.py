"""(n) Step 1 - Full-grid baseline and binding lines.

Goal: find the small set of lines that actually matter, across the WHOLE
grid (all-island), not just the north-west target line the rest of this
project has focused on. This is a different scope on purpose - Track A's
own audit already flagged that the north-west's own bottleneck doesn't
even appear in the all-island top-5 view, so a full-grid run needs its
own binding-lines pass rather than assuming the north-west target line
still matters nationally.

    python examples/n_binding_lines_baseline.py [SCENARIO] [SCOPE] [RANK_BY] [N_SELECT]
    python examples/n_binding_lines_baseline.py WP2033 all-island total_overload_MWh 15

REAL-WEATHER DLR RATING USED WHERE WE HAVE ONE, SHIPPED RATING EVERYWHERE
ELSE. This project has a real, Met-Eireann-derived seasonal DLR rating for
exactly one line so far (5041-17010-2, from j_seasonal_weather_rating.py /
j_apply_seasonal_dlr.py) - not for the other ~754 lines in the all-island
network, since that would need a weather station mapped to every line,
which hasn't been done. So this script applies gridkit.set_rating() with
the real-weather rating on that one line (winter multiplier under WP2033,
summer multiplier under SV2033 - same season-picks-the-scenario pairing
established in j_apply_seasonal_dlr.py) BEFORE solving, and leaves every
other line's static shipped rating untouched. DLR_LINES below is the
single place this is configured - extensible if/when more lines get a
real weather-derived rating of their own.

Applying the updated rating BEFORE gridkit.solve() (not just relabelling
the rating column after a static-rating solve) matters for the same
reason it has throughout this project: a wider rating on one line can
change what the LOPF dispatches everywhere else on the grid, so the flows
in baseline_hourly_flows.csv are the flows that actually happen once this
line's real capacity is used, not the old (lower, static) capacity's
flows with a new number written next to them.

Mechanics: solve -> freeze_dispatch -> lpf, in that exact order (skipping
freeze_dispatch is the "impossible flows" failure mode the quality gate
below checks for - a line reading ~1600% loaded is the classic symptom).

OVERLOAD DEFINITION: overload_MW = max(abs_flow_MW - rating_MW, 0) per
line per snapshot - i.e. MW actually over the limit, floored at zero
(never negative "overload", that's just headroom). Overload uses
|flow| > rating, not signed flow > rating - a line can bind in either
flow direction and both count.

RANKING: three metrics are computed for every line (overload_hours,
max_overload_MW, total_overload_MWh) so the team can re-sort by whichever
matters for the next step; this script's own selection for binding_lines.csv
defaults to ranking by overload_hours (pass a different RANK_BY
argument to change it) and states that choice explicitly in its own
output, per the quality gate's requirement that the team know which
metric was used.

SCOPE LIMITATION, same one Track A's own audit flagged: this only covers
n.lines, not n.transformers. The stock kit doesn't check transformer
loading either, so a transformer-bound constraint elsewhere in the
all-island grid would not show up here - noted, not silently expanded
past what's been verified.
"""

import os
import sys

import pandas as pd

# FIX (Track A audit F-06): the two lines below assumed this script lives at
# participant-kit/examples/, so "two directories up" would land on the repo
# root containing participant-kit. On this branch the script is flattened at
# the repo root instead, so that path was silently wrong (ModuleNotFoundError
# on a clean checkout). Probe both layouts rather than assuming one.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(_HERE, "grid_TF_Wind", "participant-kit"),          # flat repo-root layout (this branch)
    os.path.dirname(os.path.dirname(_HERE)),                          # original participant-kit/examples/ layout
):
    if os.path.isfile(os.path.join(_candidate, "gridkit.py")):
        sys.path.insert(0, _candidate)
        break
else:
    raise ModuleNotFoundError(
        "could not find gridkit.py in either the flat repo-root layout or "
        "the participant-kit/examples/ layout - check your checkout")
import gridkit

ROOT = _HERE
FIGURES = os.path.join(ROOT, "figures")

#: Lines with a real Met Eireann weather-derived seasonal DLR rating.
#: Extend this dict, not the code, if another line gets a real
#: weather-derived rating of its own.
#:
#: FIX (Track A audit F-06 / F-01): this used to call out to
#: j_seasonal_weather_rating.main() live, which (a) isn't committed on
#: this branch at all - ModuleNotFoundError on a clean checkout - and
#: (b) would have computed the now-RETRACTED 301.9/231.1 MVA figures
#: even if it were present (29-year archive, no solar, perpendicular-
#: wind assumption - see dlr-2024-real-weather-rewrite.md). Confirmed
#: directly: this branch's own committed baseline_hourly_flows.csv has
#: 301.854198 MVA baked in for 5041-17010-2 - the retracted number, not
#: the current one. Replaced with the current, authoritative ratings as
#: plain constants, sourced from dlr-2024-real-weather-rewrite.md
#: (2024-only real weather, real PVGIS solar, real wind-direction
#: geometry). Update these two numbers, not the mechanism, if Q3
#: revises the DLR figure again.
DLR_RATINGS_MVA = {
    "5041-17010-2": {"WP2033": 213.0, "SV2033": 184.4},
}


def apply_dlr_ratings(network, scenario):
    """Overrides the shipped static rating with the real-weather DLR
    rating for any line in DLR_RATINGS_MVA that has one for this
    scenario. Returns {line: (old_rating, new_rating)} for the printout
    / provenance record - empty if nothing applies (e.g. a scenario
    with no DLR_RATINGS_MVA entry)."""
    applied = {}
    for line, rating_by_scenario in DLR_RATINGS_MVA.items():
        new_rating = rating_by_scenario.get(scenario)
        if new_rating is None or line not in network.lines.index:
            continue
        old_rating = float(network.lines.at[line, "s_nom"])
        gridkit.set_rating(network, line, new_rating)
        applied[line] = (old_rating, new_rating)
        print(f"DLR rating applied: {line} {old_rating:.1f} -> {new_rating:.1f} MVA "
              f"(current real-weather figure, dlr-2024-real-weather-rewrite.md)")
    return applied


def run_baseline(scenario, scope):
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    dlr_applied = apply_dlr_ratings(n, scenario)

    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    return n, dlr_applied


def sanity_check(network):
    """Quality gate item: no obvious impossible flows from a skipped
    freeze_dispatch (classic symptom: a line reading >>100% loaded,
    seen at ~1600% in this project's own earlier debugging)."""
    loading = gridkit.line_loading(network)
    worst = float(loading.max().max())
    if worst > 2.0:   # 200% - generous margin above a real, tightly-bound line
        raise SystemExit(
            f"sanity check failed: worst line loading is {worst:.1%} - this is the "
            f"'impossible flows' signature of a skipped/misordered freeze_dispatch "
            f"step, not a real result. Aborting rather than writing bad output.")
    print(f"sanity check passed: worst line loading {worst:.1%} (no impossible-flow signature)")


def extract_hourly_flows(network):
    """baseline_hourly_flows.csv: one row per (snapshot, line). Only
    n.lines - see module docstring's SCOPE LIMITATION on transformers.

    Also carries an internal at_rating flag (loading >= 0.999, i.e.
    gridkit.binding()'s own threshold) alongside overload_MW - see
    binding_lines()'s docstring for why both exist and which one
    actually drives line selection."""
    flow = network.lines_t.p0                      # signed MW, snapshots x lines
    rating = network.lines["s_nom"]                 # MVA/MW, per line (DLR-adjusted where applied)
    bus0 = network.lines["bus0"]
    bus1 = network.lines["bus1"]

    rows = []
    for line in flow.columns:
        f = flow[line]
        abs_f = f.abs()
        r = float(rating[line])
        overload = (abs_f - r).clip(lower=0.0)
        at_rating = (abs_f / r) >= 0.999
        rows.append(pd.DataFrame({
            "snapshot": f.index,
            "line_id": line,
            "bus0": bus0[line],
            "bus1": bus1[line],
            "flow_MW": f.values,
            "abs_flow_MW": abs_f.values,
            "rating_MW": r,
            "overload_MW": overload.values,
            "_at_rating": at_rating.values,   # internal only, not part of the brief's schema
        }))
    return pd.concat(rows, ignore_index=True)


def binding_lines(hourly, rank_by, n_select):
    """binding_lines.csv: one row per line, only lines that actually
    bind at some hour - not padded with non-binding lines to hit a
    target count, per the brief's own "depending on how many actually
    bind" wording.

    IMPORTANT FINDING, belongs in the quality-gate writeup, not hidden:
    overload_MW (abs_flow - rating) comes out ~0 (floating-point noise,
    1e-10 to 1e-12 MW) for EVERY line in this network, every hour. This
    is not a bug - it is a direct, structural consequence of the
    solve -> freeze_dispatch -> lpf pipeline the brief's own quality
    gate asks for: gridkit.solve() is a LOPF that enforces every line's
    rating as a hard constraint when choosing generator dispatch;
    freeze_dispatch() fixes that exact dispatch; and DC lpf is a
    deterministic linear function of the (now-fixed) bus injections, so
    it reproduces the identical flows the LOPF already computed
    internally - flows that, by construction, never exceed the rating
    that was in effect when the LOPF ran. A correctly-solved network
    cannot show a genuine "overload" in this sense; it can only reach
    100% and stop. (This is the exact same thing Harshitha's Q2 writeup
    found when trying to read curtailment off hourly_flows.csv directly
    - see harshitha-q2-q4-summary.md's "One correction to the task
    brief" section - and is worth citing alongside this finding.)

    So overload_hours/max_overload_MW/total_overload_MWh below are
    computed from _at_rating (loading >= 0.999, the same threshold
    gridkit's own binding() helper uses), NOT from overload_MW > 0,
    which would make "binding" depend on which side of solver tolerance
    the floating-point noise happens to land on. overload_MW itself is
    still reported in baseline_hourly_flows.csv exactly as the brief
    specifies (for anyone downstream who wants it), just flagged here as
    structurally near-zero rather than a real overload signal."""
    grouped = hourly.groupby("line_id")
    summary = pd.DataFrame({
        "bus0": grouped["bus0"].first(),
        "bus1": grouped["bus1"].first(),
        "rating_MW": grouped["rating_MW"].first(),
        "overload_hours": grouped["_at_rating"].sum().astype(int),
        "max_overload_MW": grouped["overload_MW"].max(),
        "total_overload_MWh": grouped["overload_MW"].sum(),   # 1 snapshot = 1 hour
    }).reset_index()

    binding = summary[summary["overload_hours"] > 0].copy()
    binding = binding.sort_values(rank_by, ascending=False).reset_index(drop=True)
    binding["rank"] = binding.index + 1
    binding["selected"] = binding["rank"] <= n_select
    # SELF-DESCRIBING CSV: the real definition driving selection is loading
    # >= 99.9%, not overload_MW > 0 - stated in this function's docstring,
    # but a docstring doesn't travel with the CSV if it's separated from
    # this script. Baking the definition into a column means the file
    # stays unambiguous on its own.
    binding["binding_definition"] = "loading_ge_99.9pct"

    # quality gate: every selected line has a real, finite rating
    selected = binding[binding["selected"]]
    bad_rating = selected[~selected["rating_MW"].apply(
        lambda v: pd.notna(v) and v not in (float("inf"), float("-inf")) and v > 0)]
    if len(bad_rating):
        raise SystemExit(
            f"quality gate failed: {len(bad_rating)} selected line(s) have a "
            f"non-finite or non-positive rating - not a usable binding-lines list:\n"
            f"{bad_rating[['line_id', 'rating_MW']].to_string(index=False)}")

    return binding


def draw_chart(binding, scenario, scope, rank_by):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    top = binding[binding["selected"]].sort_values(rank_by, ascending=True)
    fig, ax = plt.subplots(figsize=(9, max(3.5, 0.4 * len(top))))
    ax.barh(top["line_id"], top[rank_by], color="#4C78A8")
    ax.set_xlabel(rank_by)
    ax.set_ylabel("line_id")
    ax.set_title(f"{scenario} {scope}: top {len(top)} binding lines, ranked by {rank_by}")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()

    os.makedirs(FIGURES, exist_ok=True)
    path = os.path.join(FIGURES, f"n_binding_lines_{scenario}_{scope}.png")
    fig.savefig(path, dpi=150)
    return path


def main(scenario="WP2033", scope="all-island", rank_by="overload_hours", n_select="15"):
    n_select = int(n_select)
    valid_rank_by = {"overload_hours", "max_overload_MW", "total_overload_MWh"}
    if rank_by not in valid_rank_by:
        raise SystemExit(f"rank_by must be one of {sorted(valid_rank_by)}, got {rank_by!r}")
    if rank_by != "overload_hours":
        print(f"note: ranking by {rank_by}, not overload_hours (the default) - see "
              f"binding_lines()'s docstring for why max_overload_MW/total_overload_MWh "
              f"read as ~0 for every line in a correctly-solved network, which makes "
              f"them a poor ranking choice even though they're computed and reported.")

    print(f"Step 1: full-grid baseline, {scenario} {scope}\n")
    network, dlr_applied = run_baseline(scenario, scope)
    sanity_check(network)

    hourly = extract_hourly_flows(network)
    hourly_path = os.path.join(ROOT, "baseline_hourly_flows.csv")
    hourly.drop(columns=["_at_rating"]).to_csv(hourly_path, index=False)
    print(f"\n{len(hourly):,} rows ({hourly['line_id'].nunique()} lines x "
          f"{hourly['snapshot'].nunique()} snapshots) -> {hourly_path}")

    binding = binding_lines(hourly, rank_by, n_select)
    # PROVENANCE STAMP: scenario/scope on every row, so a downstream reader
    # (Step 2, or anyone else) can verify this file was produced for the
    # case they think it was, rather than trusting the filename/caller's
    # memory. A stale binding_lines.csv from a different scenario/scope
    # silently feeding into another step's "case name" claim is exactly
    # the kind of data-lineage bug this guards against.
    binding.insert(0, "scenario", scenario)
    binding.insert(1, "scope", scope)
    binding_path = os.path.join(ROOT, "binding_lines.csv")
    binding.to_csv(binding_path, index=False)
    print(f"{len(binding)} line(s) actually bind at some hour; "
          f"{binding['selected'].sum()} selected (rank <= {n_select}, by {rank_by}) "
          f"-> {binding_path}")

    print(f"\ntop selected lines (ranked by {rank_by}):")
    print(binding[binding["selected"]][
        ["rank", "line_id", "rating_MW", "overload_hours",
         "max_overload_MW", "total_overload_MWh"]
    ].to_string(index=False))

    chart_path = draw_chart(binding, scenario, scope, rank_by)
    print(f"\nfigure -> {chart_path}")

    print("\n--- quality gate ---")
    print("[x] no impossible-flow signature (sanity_check passed above)")
    print("[x] overload uses |flow| > rating, not signed flow > rating")
    print("[x] every selected line has a real, finite, positive rating (checked in binding_lines())")
    print(f"[x] ranking metric used for selection: {rank_by} (team: re-sort binding_lines.csv "
          f"by overload_hours or max_overload_MW if you want a different view - all three are in the file)")
    print("[!] FINDING FOR THE TEAM, not a bug: max_overload_MW/total_overload_MWh come out "
          "~0 (1e-10 to 1e-12 MW) for every line - solve->freeze_dispatch->lpf can never "
          "produce a flow genuinely over the rating that was in effect when it solved, so "
          "'binding' here means loading >= 99.9% (overload_hours, same threshold as "
          "gridkit.binding()), not overload_MW > 0. Same issue Harshitha's Q2 writeup found "
          "reading hourly_flows.csv directly - see binding_lines()'s docstring for the full "
          "explanation before Person 2 builds anything on max_overload_MW/total_overload_MWh.")
    if dlr_applied:
        for line, (old, new) in dlr_applied.items():
            print(f"[x] {line} uses the real-weather DLR rating ({old:.1f} -> {new:.1f} MVA), "
                  f"not the old static GitHub value - every other line still uses its shipped rating")
    else:
        print("[ ] no DLR_LINES entry matched this scenario - every line used its shipped static rating")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
