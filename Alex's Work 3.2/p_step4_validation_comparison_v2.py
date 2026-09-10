"""
Step 4 -- Validation and comparison  (v2 -- two bugs fixed, see notes below)
=============================================================================

Fixes versus the first version of this script:

1. DLR patch was missing. binding_lines.csv / baseline_hourly_flows.csv were
   generated with line 5041-17010-2's rating already replaced by its real
   winter DLR value (301.9 MVA instead of the default 210 MVA) BEFORE
   solving. Every fresh network load in this script now applies that same
   patch, so it's solving the same problem that produced your input files,
   not a slightly different one.

2. The 10 MW curtailment cap was being applied per GENERATOR instead of per
   NODE (bus). Multiple wind/solar generators can sit at the same bus, so
   this let some nodes get cut far more than the agreed 10 MW rule intended.
   apply_group_cuts() now caps the total cut per node at DELTA_MW, splitting
   it proportionally across that node's own generators if it has more than
   one.

Reads:
    BINDING_LINES_CSV     -> which lines are binding, and their real ratings
    BASELINE_FLOWS_CSV    -> the full week of hourly flows (to search for
                              near-binding hours per line)
    PROPOSED_GROUPS_CSV   -> Method A's candidate groups, incl. the
                              has_adverse_tradeoff flag that separates
                              "simple" from "multi-line-aware"

Writes:
    validation_results.csv          -- one row per (case, method)
    validation_comparison_table.csv -- the summed simple-vs-multiline table

Run:
    python p_step4_validation_comparison.py
"""

import sys
from collections import defaultdict
import pandas as pd
import gridkit  # your team's kit -- must already be importable in this env

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BINDING_LINES_CSV = "binding_lines.csv"
BASELINE_FLOWS_CSV = "baseline_hourly_flows.csv"
PROPOSED_GROUPS_CSV = "proposed_groups.csv"

OUTPUT_RESULTS_CSV = "validation_results.csv"
OUTPUT_COMPARISON_CSV = "validation_comparison_table.csv"

SCENARIO = "WP2033"     # must match the "scenario" column in binding_lines.csv
SCOPE = "all-island"    # must match the "scope" column in binding_lines.csv

DELTA_MW = 10.0          # the team's agreed per-NODE curtailment rule
NOISE_FLOOR_MW = 0.5     # anything smaller than this is solver floating-point
                          # noise, not a real overload
N_CANDIDATE_HOURS = 5    # how many near-binding hours to try per line before
                          # giving up and reporting "no genuine overload"

# The one line in this project with a real, measured Dynamic Line Rating.
# Person 1's baseline script applies this BEFORE solving, so every network
# load anywhere downstream has to match it -- otherwise you're validating
# against a network that isn't the one that produced your input CSVs.
# VERIFY THIS against whoever ran n_binding_lines_baseline.py / gridkit.py's
# own DLR_LINES mapping in your repo -- this is my best reconstruction from
# the project's documented history, not something I've read out of your
# actual source file.
DLR_LINE = "5041-17010-2"
DLR_RATING_MW = 301.9   # WP2033 (winter), real-weather P10 rating


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def load_fresh_network(relax_line=None, relax_to=None):
    """
    Load a brand-new network from disk every time this is called, with the
    project's one real DLR patch applied every time, then (optionally) a
    further, separate rating override for whichever line is under test.
    """
    n = gridkit.load(SCENARIO, SCOPE)
    gridkit.set_rating(n, DLR_LINE, DLR_RATING_MW)
    if relax_line is not None:
        gridkit.set_rating(n, relax_line, relax_to)
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)
    return n


def get_frozen_dispatch(network):
    """
    Return the per-snapshot generator dispatch table that freeze_dispatch()
    fixed in place (generators_t.p_set, falling back to generators_t.p).
    """
    if hasattr(network.generators_t, "p_set") and not network.generators_t.p_set.empty:
        return network.generators_t.p_set
    if hasattr(network.generators_t, "p") and not network.generators_t.p.empty:
        return network.generators_t.p
    raise AttributeError(
        "Could not find frozen generator dispatch on this network object. "
        "Check network.generators_t in your own gridkit.py -- expected "
        "'p_set' or 'p' to be populated after freeze_dispatch()."
    )


def line_flow_at(network, line_id, snapshot):
    """Signed flow on a line at one snapshot, PyPSA's bus0->bus1 convention."""
    return network.lines_t.p0.loc[snapshot, line_id]


def find_counterfactual_hour(target_line, target_rating, near_binding_hours):
    """
    Try each candidate hour in turn: relax the target line's rating hugely,
    solve -> freeze -> lpf, and check whether the flow now genuinely exceeds
    the line's REAL rating by more than the noise floor.
    """
    relaxed_rating = target_rating * 1000
    for snapshot in near_binding_hours:
        print(f"    trying {snapshot} ...")
        n = load_fresh_network(relax_line=target_line, relax_to=relaxed_rating)
        flow = line_flow_at(n, target_line, snapshot)
        overload = abs(flow) - target_rating
        if overload > NOISE_FLOOR_MW:
            print(f"    -> genuine counterfactual overload: {overload:.2f} MW")
            return snapshot, overload, n
        else:
            print(f"    -> {overload:.2f} MW, below noise floor, trying next hour")
    return None, 0.0, None


def apply_group_cuts(network, snapshot, node_ids, delta_mw):
    """
    Reduce the frozen dispatch of the generators at each given node (bus)
    by up to delta_mw TOTAL PER NODE -- not per generator -- at one
    snapshot only, then reflow. If a node hosts several generators, the
    node's own delta_mw allowance is split across them proportionally to
    their current output.

    Returns: total MW actually cut (capped by each node's own available
    dispatch -- you cannot cut a node's generators below 0 MW combined).
    """
    dispatch = get_frozen_dispatch(network)
    gens = network.generators
    node_ids_str = {str(n) for n in node_ids}

    # Group generator names by their bus (node) first, so the cap applies
    # once per node, across all of that node's own generators together.
    gens_by_node = defaultdict(list)
    for gen_name, bus in gens["bus"].items():
        if str(bus) in node_ids_str:
            gens_by_node[str(bus)].append(gen_name)

    total_cut = 0.0
    for node, gen_names in gens_by_node.items():
        current_by_gen = {
            g: dispatch.loc[snapshot, g] for g in gen_names
            if dispatch.loc[snapshot, g] > 0
        }
        node_available = sum(current_by_gen.values())
        if node_available <= 0:
            continue
        node_cut_target = min(delta_mw, node_available)
        for g, current in current_by_gen.items():
            share = current / node_available
            cut = node_cut_target * share
            dispatch.loc[snapshot, g] = current - cut
            total_cut += cut

    if hasattr(network.generators_t, "p_set"):
        network.generators_t.p_set = dispatch
    network.lpf(network.snapshots)
    return total_cut


def check_new_overloads(network, snapshot, binding_lines_df, target_line):
    """
    After a cut-and-reflow, check every OTHER selected binding line against
    its own REAL rating. Returns (count, largest).
    """
    other_lines = binding_lines_df[
        (binding_lines_df["selected"] == True)
        & (binding_lines_df["line_id"] != target_line)
    ]
    new_overloads = []
    for _, row in other_lines.iterrows():
        line_id = row["line_id"]
        real_rating = row["rating_MW"]
        flow = line_flow_at(network, line_id, snapshot)
        overload = abs(flow) - real_rating
        if overload > NOISE_FLOOR_MW:
            new_overloads.append(overload)
    if new_overloads:
        return len(new_overloads), max(new_overloads)
    return 0, 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    binding_lines_df = pd.read_csv(BINDING_LINES_CSV)
    baseline_flows_df = pd.read_csv(BASELINE_FLOWS_CSV, parse_dates=["snapshot"])
    proposed_groups_df = pd.read_csv(PROPOSED_GROUPS_CSV)
    proposed_groups_df["node_id"] = proposed_groups_df["node_id"].astype(str)

    method_a = proposed_groups_df[proposed_groups_df["method"] == "A"]

    testable_lines = (
        method_a[method_a["has_adverse_tradeoff"] == True]["target_line"]
        .unique()
        .tolist()
    )
    print(f"Lines with at least one adverse-tradeoff node (testable): {testable_lines}")

    all_lines = binding_lines_df[binding_lines_df["selected"] == True]["line_id"].tolist()
    non_testable = [l for l in all_lines if l not in testable_lines]
    if non_testable:
        print(f"Skipping (simple == multi-line-aware, nothing to compare): {non_testable}")

    results_rows = []

    for case_id, target_line in enumerate(testable_lines, start=1):
        print(f"\n=== Case {case_id}: {target_line} ===")
        target_rating = binding_lines_df.loc[
            binding_lines_df["line_id"] == target_line, "rating_MW"
        ].iloc[0]

        line_flows = baseline_flows_df[baseline_flows_df["line_id"] == target_line].copy()
        line_flows["loading"] = line_flows["abs_flow_MW"] / line_flows["rating_MW"]
        candidate_hours = (
            line_flows.sort_values("loading", ascending=False)
            ["snapshot"]
            .head(N_CANDIDATE_HOURS)
            .tolist()
        )

        snapshot, overload_before, relaxed_network = find_counterfactual_hour(
            target_line, target_rating, candidate_hours
        )

        if snapshot is None:
            print(f"  No genuine overload found across {N_CANDIDATE_HOURS} near-binding hours.")
            for method_label in ("simple", "multiline_aware"):
                results_rows.append({
                    "case_id": case_id, "hour": "", "target_line": target_line,
                    "method": method_label, "renewable_MW_reduced": 0.0,
                    "target_overload_before_MW": 0.0, "target_overload_after_MW": 0.0,
                    "target_relief_MW": 0.0, "new_overloads_count": 0,
                    "largest_new_overload_MW": 0.0,
                    "validation_status": "no_genuine_overload_to_relieve",
                })
            continue

        group_a = method_a[method_a["target_line"] == target_line]
        groups = {
            "simple": group_a["node_id"].tolist(),
            "multiline_aware": group_a[group_a["has_adverse_tradeoff"] != True]["node_id"].tolist(),
        }

        for method_label, node_ids in groups.items():
            print(f"  method={method_label}, group size={len(node_ids)}")
            n = load_fresh_network(relax_line=target_line, relax_to=target_rating * 1000)
            cut_mw = apply_group_cuts(n, snapshot, node_ids, DELTA_MW)
            new_flow = line_flow_at(n, target_line, snapshot)
            overload_after = max(0.0, abs(new_flow) - target_rating)
            relief = overload_before - overload_after
            n_over, largest_over = check_new_overloads(n, snapshot, binding_lines_df, target_line)

            status = "relieved_clean" if overload_after <= NOISE_FLOOR_MW else "partial_relief"

            results_rows.append({
                "case_id": case_id, "hour": str(snapshot), "target_line": target_line,
                "method": method_label, "renewable_MW_reduced": round(cut_mw, 2),
                "target_overload_before_MW": round(overload_before, 2),
                "target_overload_after_MW": round(overload_after, 2),
                "target_relief_MW": round(relief, 2),
                "new_overloads_count": n_over,
                "largest_new_overload_MW": round(largest_over, 2),
                "validation_status": status,
            })
            print(f"    cut={cut_mw:.2f} MW, before={overload_before:.2f}, "
                  f"after={overload_after:.2f}, relief={relief:.2f}, "
                  f"new_overloads={n_over}")

    results_df = pd.DataFrame(results_rows)
    results_df.to_csv(OUTPUT_RESULTS_CSV, index=False)
    print(f"\nWrote {OUTPUT_RESULTS_CSV} ({len(results_df)} rows)")

    summary_rows = []
    for method_label in ("simple", "multiline_aware"):
        sub = results_df[results_df["method"] == method_label]
        summary_rows.append({
            "method": method_label,
            "target_overload_relieved_MW": round(sub["target_relief_MW"].sum(), 2),
            "renewable_MW_reduced": round(sub["renewable_MW_reduced"].sum(), 2),
            "new_monitored_line_overloads": int(sub["new_overloads_count"].sum()),
        })
    comparison_df = pd.DataFrame(summary_rows)
    comparison_df.to_csv(OUTPUT_COMPARISON_CSV, index=False)
    print(f"Wrote {OUTPUT_COMPARISON_CSV}")
    print(comparison_df.to_string(index=False))


if __name__ == "__main__":
    main()
