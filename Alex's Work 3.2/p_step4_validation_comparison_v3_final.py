"""
Step 4 -- Validation and comparison  (v3)
=============================================================================

This is a fix on top of p_step4_validation_comparison_v2.py. It does NOT
change the modelling method -- same fresh-network-per-attempt approach,
same hour search, same simple-vs-multiline-aware group definitions. It
fixes gaps found reviewing v2 against the task brief.

WHAT CHANGED FROM v2, AND WHY
------------------------------

1. THE FINAL COMPARISON TABLE WAS INCOMPLETE.
   The brief asks for 5 rows: target overload relieved, renewable MW
   reduced, new monitored-line overloads, NODES CURTAILED, and
   OVERLAPPING/TRADE-OFF NODES FLAGGED. v2's comparison_df only computed
   the first 3 -- nothing anywhere tracked node counts. Fixed by:
     - apply_group_cuts() now returns (total_cut_MW, nodes_curtailed)
       instead of just total_cut_MW.
     - Each case now also records how many nodes were excluded from the
       multiline_aware group because Method B flagged them with a
       genuine adverse trade-off (simple keeps everyone -> 0 excluded;
       multiline_aware excludes all flagged nodes for that line).
     - The final comparison table now has all 5 rows.

2. THE PER-NODE CAP-AND-SPLIT ARITHMETIC IS NOW ISOLATED AND TESTED.
   v2's cut-splitting logic lived inline inside apply_group_cuts(), mixed
   in with gridkit/pandas network calls, so it couldn't be checked without
   a full gridkit environment and real data. It's now pulled out into a
   plain function, split_node_cut(), with a hand-checkable unit test
   (test_split_node_cut()) that needs no gridkit import at all. Run:

       python p_step4_validation_comparison_v3.py --test

   to check the arithmetic on its own before trusting a full run. This
   was done because the total renewable MW curtailed jumped by roughly
   5-40x between the pre-v2 script's results and v2's -- a change too
   large to wave through without independently confirming the rule that
   drives it is doing exactly what it's supposed to.

3. DEFENSIVE: proposed_groups.csv is only filtered to method == "A" rows
   IF a "method" column actually exists. Your own project documentation
   describes proposed_groups.csv as already being Method A's 179
   candidate rows (enriched by Method B), which suggests there may be no
   literal "method" column to filter on at all -- v2 would have thrown a
   KeyError immediately on such a file. This version checks first and
   falls back to treating every row as Method A if the column is absent.
   >>> Worth confirming directly against your actual proposed_groups.csv
   >>> column headers rather than relying on this fallback silently. <<<

4. DEFENSIVE: binding_lines.csv is now checked against SCENARIO/SCOPE
   before anything else runs, the same hard-fail pattern your project's
   Step 2 script already uses. v2 had no such check, so a stale or
   mismatched CSV would have been used silently.

5. DLR_RATING_MW CORRECTED (2026-09-11, Track A audit F-01/F-02).
   The 301.8541975480315 MVA value below was verified against a
   baseline_hourly_flows.csv that has since been superseded - it was
   built from Q3's now-RETRACTED DLR figure (29-year weather archive, no
   solar term, perpendicular-wind assumption). Q3's corrected, current
   figure is 213.0 MVA (2024-only real weather, real PVGIS solar, real
   wind-direction geometry - see dlr-2024-real-weather-rewrite.md).
   Updated below. If you regenerate binding_lines.csv / baseline_hourly_
   flows.csv again later, re-verify this constant against the new file
   the same way point 5 originally did - don't assume it stays 213.0
   forever any more than 301.9 turned out to.

WHAT DID NOT CHANGE
--------------------
- The hour-search method (try up to N_CANDIDATE_HOURS near-binding hours,
  relax the target line's rating x1000, solve/freeze/lpf, look for a
  genuine counterfactual overload above the noise floor).
- The DLR patch itself being applied on every fresh network load.
- The definition of "simple" (every Method A candidate) vs
  "multiline_aware" (Method A candidates minus adverse-trade-off nodes).
- validation_results.csv's required column set/order -- still exactly
  what the brief specifies, no more, no less. The new node-count
  bookkeeping is kept in memory for the comparison table only.

Reads:
    BINDING_LINES_CSV, BASELINE_FLOWS_CSV, PROPOSED_GROUPS_CSV
Writes:
    validation_results.csv, validation_comparison_table.csv

Run:
    python p_step4_validation_comparison_v3.py            # full run (needs gridkit + data files)
    python p_step4_validation_comparison_v3.py --test     # arithmetic self-test only (no gridkit needed)
"""
import os
import sys
from collections import defaultdict
import pandas as pd

# FIX (Track A audit F-06): this used to rely on gridkit already being on
# sys.path (e.g. only worked if launched from inside participant-kit/).
# Probe both this repo's flat layout and the original participant-kit/
# examples/ layout before giving up.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(_HERE, "grid_TF_Wind", "participant-kit"),
    os.path.join(os.path.dirname(_HERE), "grid_TF_Wind", "participant-kit"),
    os.path.dirname(os.path.dirname(_HERE)),
):
    if os.path.isfile(os.path.join(_candidate, "gridkit.py")):
        sys.path.insert(0, _candidate)
        break

try:
    import gridkit  # only needed for the real run, not for --test
except ImportError:
    gridkit = None

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
BINDING_LINES_CSV = "binding_lines.csv"
BASELINE_FLOWS_CSV = "baseline_hourly_flows.csv"
PROPOSED_GROUPS_CSV = "proposed_groups.csv"

OUTPUT_RESULTS_CSV = "validation_results.csv"
OUTPUT_COMPARISON_CSV = "validation_comparison_table.csv"

SCENARIO = "WP2033"
SCOPE = "all-island"

DELTA_MW = 10.0          # the team's agreed per-NODE curtailment rule
NOISE_FLOOR_MW = 0.5
N_CANDIDATE_HOURS = 5

# CORRECTED (Track A audit F-01/F-02): 213.0 MVA is Q3's current,
# authoritative winter DLR figure - not a reconstruction, not the
# retracted 301.9 figure. See point 5 above.
DLR_LINE = "5041-17010-2"
DLR_RATING_MW = 213.0

# The brief's required schema for validation_results.csv -- exactly these
# columns, in this order.
REQUIRED_RESULT_COLUMNS = [
    "case_id", "hour", "target_line", "method",
    "renewable_MW_reduced",
    "target_overload_before_MW", "target_overload_after_MW",
    "target_relief_MW",
    "new_overloads_count", "largest_new_overload_MW",
    "validation_status",
]


# ---------------------------------------------------------------------------
# PURE ARITHMETIC -- no gridkit, no network objects. This is the actual
# "how do we split a per-node cap across that node's generators" rule,
# isolated so it can be tested on its own. See test_split_node_cut().
# ---------------------------------------------------------------------------

def split_node_cut(generator_outputs_mw, delta_mw):
    """
    generator_outputs_mw: dict {generator_name: current_output_mw} for ALL
        generators sitting at ONE node (bus), at one snapshot.
    delta_mw: the team's agreed per-NODE cap (e.g. 10.0).

    Returns: dict {generator_name: mw_to_cut_from_that_generator}. The
    cuts sum to min(delta_mw, total_positive_output_at_this_node) and are
    split across generators in proportion to their current output.
    Generators with zero/negative output get 0.0 (never a negative cut).
    """
    positive_outputs = {g: v for g, v in generator_outputs_mw.items() if v > 0}
    node_available = sum(positive_outputs.values())
    if node_available <= 0:
        return {g: 0.0 for g in generator_outputs_mw}
    node_cut_target = min(delta_mw, node_available)
    cuts = {}
    for g, current in generator_outputs_mw.items():
        if current > 0:
            share = current / node_available
            cuts[g] = node_cut_target * share
        else:
            cuts[g] = 0.0
    return cuts


def test_split_node_cut():
    """Hand-checkable toy example. No gridkit needed. Run with --test."""
    print("Test 1: single generator, plenty of headroom")
    cuts = split_node_cut({"gen_A": 40.0}, delta_mw=10.0)
    assert abs(cuts["gen_A"] - 10.0) < 1e-9, cuts
    print(f"  gen_A cut = {cuts['gen_A']:.4f} MW (expected 10.0) -- OK")

    print("Test 2: two generators at the same node, split proportionally")
    cuts = split_node_cut({"gen_A": 30.0, "gen_B": 10.0}, delta_mw=10.0)
    assert abs(cuts["gen_A"] - 7.5) < 1e-9, cuts
    assert abs(cuts["gen_B"] - 2.5) < 1e-9, cuts
    assert abs(sum(cuts.values()) - 10.0) < 1e-9, cuts
    print(f"  gen_A cut = {cuts['gen_A']:.4f} (expected 7.5) -- OK")
    print(f"  gen_B cut = {cuts['gen_B']:.4f} (expected 2.5) -- OK")
    print(f"  total cut = {sum(cuts.values()):.4f} (expected 10.0) -- OK")

    print("Test 3: node has LESS than delta_mw available -- cut everything, not more")
    cuts = split_node_cut({"gen_A": 4.0, "gen_B": 2.0}, delta_mw=10.0)
    assert abs(cuts["gen_A"] - 4.0) < 1e-9, cuts
    assert abs(cuts["gen_B"] - 2.0) < 1e-9, cuts
    assert abs(sum(cuts.values()) - 6.0) < 1e-9, cuts
    print(f"  total cut = {sum(cuts.values()):.4f} (expected 6.0, capped by availability) -- OK")

    print("Test 4: node has zero output -- no cut, no crash")
    cuts = split_node_cut({"gen_A": 0.0}, delta_mw=10.0)
    assert cuts["gen_A"] == 0.0
    print("  zero-output node handled cleanly -- OK")

    print("\nAll split_node_cut() tests passed. The per-node capping rule")
    print("itself is doing what it's supposed to. If your full run's")
    print("renewable_MW_reduced numbers still look surprising, the cause")
    print("is elsewhere (group membership size, DLR_RATING_MW mismatch,")
    print("or the input CSVs) -- not this arithmetic.")


# ---------------------------------------------------------------------------
# gridkit-dependent helpers
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
    by up to delta_mw TOTAL PER NODE (via split_node_cut), at one
    snapshot only, then reflow.

    Returns: (total_mw_cut, nodes_actually_curtailed)
        total_mw_cut            -- summed across all nodes
        nodes_actually_curtailed -- how many of node_ids had ANY positive
            generation to cut at this snapshot (a group member with zero
            output that hour contributes 0 MW and isn't counted here --
            this is what fills in the brief's "Nodes curtailed" metric)
    """
    dispatch = get_frozen_dispatch(network)
    gens = network.generators
    node_ids_str = {str(n) for n in node_ids}

    gens_by_node = defaultdict(list)
    for gen_name, bus in gens["bus"].items():
        if str(bus) in node_ids_str:
            gens_by_node[str(bus)].append(gen_name)

    total_cut = 0.0
    nodes_actually_curtailed = 0

    for node, gen_names in gens_by_node.items():
        outputs = {g: dispatch.loc[snapshot, g] for g in gen_names}
        cuts = split_node_cut(outputs, delta_mw)
        node_total_cut = sum(cuts.values())
        if node_total_cut <= 0:
            continue
        nodes_actually_curtailed += 1
        for g, cut in cuts.items():
            if cut > 0:
                dispatch.loc[snapshot, g] = outputs[g] - cut
                total_cut += cut

    if hasattr(network.generators_t, "p_set"):
        network.generators_t.p_set = dispatch
    network.lpf(network.snapshots)
    return total_cut, nodes_actually_curtailed


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
# Input validation -- catches a mismatched/stale CSV before it silently
# produces wrong numbers, instead of trusting filenames.
# ---------------------------------------------------------------------------

def validate_inputs(binding_lines_df):
    if "scenario" in binding_lines_df.columns:
        bad = binding_lines_df.loc[binding_lines_df["scenario"] != SCENARIO, "scenario"].unique()
        if len(bad) > 0:
            raise ValueError(
                f"{BINDING_LINES_CSV} contains scenario(s) {list(bad)}, but this "
                f"script is configured for SCENARIO={SCENARIO!r}. Fix the "
                f"mismatch before continuing -- do not proceed on a guess."
            )
    if "scope" in binding_lines_df.columns:
        bad = binding_lines_df.loc[binding_lines_df["scope"] != SCOPE, "scope"].unique()
        if len(bad) > 0:
            raise ValueError(
                f"{BINDING_LINES_CSV} contains scope(s) {list(bad)}, but this "
                f"script is configured for SCOPE={SCOPE!r}. Fix the mismatch "
                f"before continuing."
            )

    selected = binding_lines_df[binding_lines_df["selected"] == True]
    if DLR_LINE in selected["line_id"].values:
        print(
            f"\n  !! WARNING: {DLR_LINE} appears as a SELECTED binding line in "
            f"{BINDING_LINES_CSV}.\n"
            f"     This project's own established finding is that a correctly "
            f"DLR-patched {DLR_LINE}\n"
            f"     (rating {DLR_RATING_MW} MVA) drops OUT of the binding-lines "
            f"list entirely under\n"
            f"     WP2033/all-island. Seeing it here suggests DLR_RATING_MW in "
            f"this script does NOT\n"
            f"     match whatever rating actually produced this CSV. Confirm "
            f"before trusting anything\n"
            f"     below.\n"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(only_line=None, output_results_csv=None, write_summary=True):
    binding_lines_df = pd.read_csv(BINDING_LINES_CSV)
    baseline_flows_df = pd.read_csv(BASELINE_FLOWS_CSV, parse_dates=["snapshot"])
    proposed_groups_df = pd.read_csv(PROPOSED_GROUPS_CSV)
    proposed_groups_df["node_id"] = proposed_groups_df["node_id"].astype(str)

    validate_inputs(binding_lines_df)

    if "method" in proposed_groups_df.columns:
        method_a = proposed_groups_df[proposed_groups_df["method"] == "A"]
    else:
        print(
            "  Note: proposed_groups.csv has no 'method' column -- treating "
            "every row as a Method A candidate row (per your project docs, "
            "this file is described as Method A's candidates only)."
        )
        method_a = proposed_groups_df

    testable_lines = (
        method_a[method_a["has_adverse_tradeoff"] == True]["target_line"]
        .unique()
        .tolist()
    )
    # SUBPROCESS ISOLATION (Track A audit F-10 / EFF-3): this project's own
    # docs claimed each LOPF solve runs in its own subprocess to avoid
    # exhausting memory across ~15-21 solves in one long-lived process -
    # that isolation wasn't actually present in this file (confirmed: ran
    # out of memory and got OOM-killed partway through case 2 on a fresh
    # run). `only_line` lets a driver invoke this script once per testable
    # line, each as a fresh `python` process, so memory is fully released
    # between lines - see run_all_cases_isolated() at the bottom of this
    # file for the actual driver.
    if only_line is not None:
        testable_lines = [only_line] if only_line in testable_lines else []
    print(f"Lines with at least one adverse-tradeoff node (testable): {testable_lines}")

    all_lines = binding_lines_df[binding_lines_df["selected"] == True]["line_id"].tolist()
    non_testable = [l for l in all_lines if l not in testable_lines]
    if non_testable and only_line is None:
        print(f"Skipping (simple == multi-line-aware, nothing to compare): {non_testable}")

    # results_rows carries a couple of extra bookkeeping fields
    # (nodes_curtailed, nodes_flagged_excluded) used to build the
    # comparison table below. They are dropped before validation_results.csv
    # is written, since the brief's schema for that file doesn't include them.
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

        group_a = method_a[method_a["target_line"] == target_line]
        simple_nodes = group_a["node_id"].tolist()
        multiline_nodes = group_a[group_a["has_adverse_tradeoff"] != True]["node_id"].tolist()
        n_flagged_excluded = len(simple_nodes) - len(multiline_nodes)

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
                    "nodes_curtailed": 0,
                    "nodes_flagged_excluded": n_flagged_excluded if method_label == "multiline_aware" else 0,
                })
            continue

        groups = {"simple": simple_nodes, "multiline_aware": multiline_nodes}

        for method_label, node_ids in groups.items():
            print(f"  method={method_label}, group size={len(node_ids)}")
            n = load_fresh_network(relax_line=target_line, relax_to=target_rating * 1000)
            cut_mw, nodes_curtailed = apply_group_cuts(n, snapshot, node_ids, DELTA_MW)
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
                "nodes_curtailed": nodes_curtailed,
                "nodes_flagged_excluded": n_flagged_excluded if method_label == "multiline_aware" else 0,
            })
            print(f"    cut={cut_mw:.2f} MW across {nodes_curtailed} nodes, before={overload_before:.2f}, "
                  f"after={overload_after:.2f}, relief={relief:.2f}, "
                  f"new_overloads={n_over}")

    results_df = pd.DataFrame(results_rows)

    out_path = output_results_csv or OUTPUT_RESULTS_CSV
    if only_line is not None:
        # isolated per-line mode: keep the bookkeeping columns too, since
        # the driver needs them to build the final comparison table after
        # merging every line's isolated output back together.
        results_df.to_csv(out_path, index=False)
    else:
        results_df[REQUIRED_RESULT_COLUMNS].to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(results_df)} rows)")

    if not write_summary:
        return results_df

    summary_rows = []
    for method_label in ("simple", "multiline_aware"):
        sub = results_df[results_df["method"] == method_label]
        summary_rows.append({
            "method": method_label,
            "target_overload_relieved_MW": round(sub["target_relief_MW"].sum(), 2),
            "renewable_MW_reduced": round(sub["renewable_MW_reduced"].sum(), 2),
            "new_monitored_line_overloads": int(sub["new_overloads_count"].sum()),
            "nodes_curtailed": int(sub["nodes_curtailed"].sum()),
            "nodes_flagged_excluded": int(sub["nodes_flagged_excluded"].sum()),
        })
    comparison_df = pd.DataFrame(summary_rows)
    comparison_df.to_csv(OUTPUT_COMPARISON_CSV, index=False)
    print(f"Wrote {OUTPUT_COMPARISON_CSV}")
    print(comparison_df.to_string(index=False))


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_split_node_cut()
    elif "--worker-counterfactual" in sys.argv:
        # ATOMIC WORKER (Track A audit F-10 / EFF-3): does exactly ONE
        # load+solve+lpf+flow-check for ONE candidate hour, then exits.
        # A single all-island solve measured ~2.1 GB peak RSS in this
        # environment - more than half of a typical 4 GB container - so
        # even one testable line's multi-hour search can OOM a long-lived
        # process. Isolating at this level (one subprocess per hour tried,
        # not one subprocess per line) is what actually fits.
        import json
        idx = sys.argv.index("--worker-counterfactual")
        spec_path, out_path = sys.argv[idx + 1], sys.argv[idx + 2]
        with open(spec_path) as f:
            spec = json.load(f)
        n = load_fresh_network(relax_line=spec["target_line"], relax_to=spec["relaxed_rating"])
        flow = float(line_flow_at(n, spec["target_line"], pd.Timestamp(spec["snapshot"])))
        overload = abs(flow) - spec["target_rating"]
        with open(out_path, "w") as f:
            json.dump({"overload": overload}, f)
    elif "--worker-case" in sys.argv:
        # ATOMIC WORKER: does exactly ONE load+relax+cut+reflow+check for
        # ONE (target_line, method) pair at an already-known snapshot,
        # then exits - same memory reasoning as the counterfactual worker.
        import json
        idx = sys.argv.index("--worker-case")
        spec_path, out_path = sys.argv[idx + 1], sys.argv[idx + 2]
        with open(spec_path) as f:
            spec = json.load(f)
        binding_lines_df = pd.read_csv(BINDING_LINES_CSV)
        snapshot = pd.Timestamp(spec["snapshot"])
        n = load_fresh_network(relax_line=spec["target_line"], relax_to=spec["target_rating"] * 1000)
        cut_mw, nodes_curtailed = apply_group_cuts(n, snapshot, spec["node_ids"], DELTA_MW)
        new_flow = line_flow_at(n, spec["target_line"], snapshot)
        overload_after = max(0.0, abs(new_flow) - spec["target_rating"])
        n_over, largest_over = check_new_overloads(n, snapshot, binding_lines_df, spec["target_line"])
        with open(out_path, "w") as f:
            json.dump({
                "cut_mw": cut_mw, "nodes_curtailed": nodes_curtailed,
                "overload_after": overload_after, "n_over": n_over,
                "largest_over": largest_over,
            }, f)
    elif "--isolated" in sys.argv:
        # SUBPROCESS ISOLATION DRIVER (Track A audit F-10 / EFF-3): does
        # NOT call main() at all - re-implements its case loop here, but
        # dispatches every individual LOPF solve to one of the two atomic
        # workers above as its own subprocess, so each ~2.1 GB solve is
        # fully released back to the OS before the next one starts.
        import json
        import subprocess
        import tempfile

        if gridkit is None:
            print("ERROR: gridkit could not be imported in this environment.")
            sys.exit(1)

        def run_worker(mode, spec, tmp):
            spec_path = os.path.join(tmp, "spec.json")
            out_path = os.path.join(tmp, "out.json")
            with open(spec_path, "w") as f:
                json.dump(spec, f, default=str)
            result = subprocess.run(
                [sys.executable, os.path.abspath(__file__), mode, spec_path, out_path],
                cwd=os.getcwd(), capture_output=True, text=True)
            if result.returncode != 0:
                raise SystemExit(
                    f"[isolated driver] worker {mode} exited {result.returncode}\n"
                    f"--- stdout ---\n{result.stdout[-2000:]}\n"
                    f"--- stderr ---\n{result.stderr[-2000:]}")
            with open(out_path) as f:
                return json.load(f)

        binding_lines_df = pd.read_csv(BINDING_LINES_CSV)
        baseline_flows_df = pd.read_csv(BASELINE_FLOWS_CSV, parse_dates=["snapshot"])
        proposed_groups_df = pd.read_csv(PROPOSED_GROUPS_CSV)
        proposed_groups_df["node_id"] = proposed_groups_df["node_id"].astype(str)
        method_a = (proposed_groups_df[proposed_groups_df["method"] == "A"]
                    if "method" in proposed_groups_df.columns else proposed_groups_df)
        testable_lines = (
            method_a[method_a["has_adverse_tradeoff"] == True]["target_line"]
            .unique().tolist()
        )
        # ADDED (environment constraint, not a modelling change): this
        # sandbox reaps background/disowned processes between separate
        # tool invocations, and a full --isolated run (all testable
        # lines, up to N_CANDIDATE_HOURS x 2 methods worker calls each)
        # runs long enough to cross that boundary. --only-line=<line_id>
        # restricts the driver to a single line per invocation, and
        # --append writes/updates the two output CSVs incrementally
        # instead of only at the very end, so a multi-call driven run
        # (one call per line) still produces the exact same final files
        # as a single uninterrupted run would.
        for _arg in sys.argv:
            if _arg.startswith("--only-line="):
                _only = _arg.split("=", 1)[1]
                testable_lines = [l for l in testable_lines if l == _only]
        APPEND_MODE = "--append" in sys.argv
        print(f"[isolated driver] testable lines: {testable_lines}")

        results_rows = []
        with tempfile.TemporaryDirectory() as tmp:
            for case_id, target_line in enumerate(testable_lines, start=1):
                print(f"\n=== Case {case_id}: {target_line} (isolated) ===")
                target_rating = float(binding_lines_df.loc[
                    binding_lines_df["line_id"] == target_line, "rating_MW"].iloc[0])
                line_flows = baseline_flows_df[baseline_flows_df["line_id"] == target_line].copy()
                line_flows["loading"] = line_flows["abs_flow_MW"] / line_flows["rating_MW"]
                candidate_hours = (
                    line_flows.sort_values("loading", ascending=False)
                    ["snapshot"].head(N_CANDIDATE_HOURS).tolist()
                )

                snapshot, overload_before = None, 0.0
                relaxed_rating = target_rating * 1000
                for hr in candidate_hours:
                    print(f"    trying {hr} (isolated worker) ...")
                    out = run_worker("--worker-counterfactual", {
                        "target_line": target_line, "relaxed_rating": relaxed_rating,
                        "snapshot": str(hr), "target_rating": target_rating,
                    }, tmp)
                    if out["overload"] > NOISE_FLOOR_MW:
                        snapshot, overload_before = hr, out["overload"]
                        print(f"    -> genuine counterfactual overload: {overload_before:.2f} MW")
                        break
                    print(f"    -> {out['overload']:.2f} MW, below noise floor, trying next hour")

                group_a = method_a[method_a["target_line"] == target_line]
                simple_nodes = group_a["node_id"].tolist()
                multiline_nodes = group_a[group_a["has_adverse_tradeoff"] != True]["node_id"].tolist()
                n_flagged_excluded = len(simple_nodes) - len(multiline_nodes)

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
                            "nodes_curtailed": 0,
                            "nodes_flagged_excluded": n_flagged_excluded if method_label == "multiline_aware" else 0,
                        })
                    continue

                groups = {"simple": simple_nodes, "multiline_aware": multiline_nodes}
                for method_label, node_ids in groups.items():
                    print(f"  method={method_label}, group size={len(node_ids)} (isolated worker)")
                    out = run_worker("--worker-case", {
                        "target_line": target_line, "target_rating": target_rating,
                        "snapshot": str(snapshot), "node_ids": node_ids,
                    }, tmp)
                    relief = overload_before - out["overload_after"]
                    status = "relieved_clean" if out["overload_after"] <= NOISE_FLOOR_MW else "partial_relief"
                    results_rows.append({
                        "case_id": case_id, "hour": str(snapshot), "target_line": target_line,
                        "method": method_label, "renewable_MW_reduced": round(out["cut_mw"], 2),
                        "target_overload_before_MW": round(overload_before, 2),
                        "target_overload_after_MW": round(out["overload_after"], 2),
                        "target_relief_MW": round(relief, 2),
                        "new_overloads_count": out["n_over"],
                        "largest_new_overload_MW": round(out["largest_over"], 2),
                        "validation_status": status,
                        "nodes_curtailed": out["nodes_curtailed"],
                        "nodes_flagged_excluded": n_flagged_excluded if method_label == "multiline_aware" else 0,
                    })
                    print(f"    cut={out['cut_mw']:.2f} MW across {out['nodes_curtailed']} nodes, "
                          f"before={overload_before:.2f}, after={out['overload_after']:.2f}, "
                          f"relief={relief:.2f}, new_overloads={out['n_over']}")

        results_df = pd.DataFrame(results_rows)
        _FULL_COLS_SIDECAR = OUTPUT_RESULTS_CSV + ".full_columns_sidecar.csv"
        if APPEND_MODE and os.path.isfile(_FULL_COLS_SIDECAR):
            prior_full = pd.read_csv(_FULL_COLS_SIDECAR)
            prior_full = prior_full[~prior_full["target_line"].isin(testable_lines)]
            results_df = pd.concat([prior_full, results_df], ignore_index=True)
        results_df.to_csv(_FULL_COLS_SIDECAR, index=False)  # internal bookkeeping only, keeps nodes_curtailed etc across --only-line calls
        results_df[REQUIRED_RESULT_COLUMNS].to_csv(OUTPUT_RESULTS_CSV, index=False)
        print(f"\n[isolated driver] wrote {OUTPUT_RESULTS_CSV} ({len(results_df)} rows total)")

        summary_rows = []
        for method_label in ("simple", "multiline_aware"):
            sub = results_df[results_df["method"] == method_label]
            summary_rows.append({
                "method": method_label,
                "target_overload_relieved_MW": round(sub["target_relief_MW"].sum(), 2),
                "renewable_MW_reduced": round(sub["renewable_MW_reduced"].sum(), 2),
                "new_monitored_line_overloads": int(sub["new_overloads_count"].sum()),
                "nodes_curtailed": int(sub["nodes_curtailed"].sum()),
                "nodes_flagged_excluded": int(sub["nodes_flagged_excluded"].sum()),
            })
        comparison_df = pd.DataFrame(summary_rows)
        comparison_df.to_csv(OUTPUT_COMPARISON_CSV, index=False)
        print(f"[isolated driver] wrote {OUTPUT_COMPARISON_CSV}")
        print(comparison_df.to_string(index=False))
    else:
        if gridkit is None:
            print(
                "ERROR: gridkit could not be imported in this environment.\n"
                "Activate your project's Python environment (the one with "
                "gridkit.py importable), or run with --test to check just "
                "the curtailment-splitting arithmetic on its own:\n\n"
                "    python p_step4_validation_comparison_v3.py --test\n"
            )
            sys.exit(1)
        print("[note] running all cases in ONE process. A single all-island "
              "solve measured ~2.1 GB peak RSS here - if this gets OOM-killed "
              "partway through, re-run with --isolated instead, which runs "
              "every individual solve in its own short-lived subprocess.")
        main()
