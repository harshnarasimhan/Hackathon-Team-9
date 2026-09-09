"""
Q6: Priority vs non-priority wind farms
========================================
This script:
  1. Loads the WP2033 north-west network
  2. Picks a subset of wind farms to call "priority" (THIS IS AN ASSUMPTION —
     see the note below, and say so explicitly in your presentation)
  3. Runs the model TWICE: once normally (baseline), once with priority
     farms protected (priority scenario)
  4. Compares how much each generator got curtailed in each run
  5. Cross-references against shift factors to find the "protected but
     guilty" vs "curtailed but innocent" mismatch — this is your headline
     finding

Run this from the root of the repo, after activating your virtual
environment, with:
    python q6_priority_analysis.py
"""

import pandas as pd
import gridkit          # the repo's helper module for loading/solving networks
import flowmath          # the repo's helper module for shift factors / PTDF

# ---------------------------------------------------------------------------
# STEP 1: Load the network
# ---------------------------------------------------------------------------
# "WP2033" = winter peak, 2033 network (the stressed, high-headroom case
# where constraint is most likely to bite). "north-west" = the 15-node
# regional subnetwork built for problem 3.1.
network_name = "WP2033"
scope = "north-west"

n_baseline = gridkit.load(network_name, scope)

# ---------------------------------------------------------------------------
# STEP 2: Decide which wind farms are "priority" — THIS IS YOUR ASSUMPTION
# ---------------------------------------------------------------------------
# The dataset has no priority/non-priority flag at all. We are inventing
# one. A defensible real-world basis: Ireland's grid connection policy
# historically split generators into pre-2004 "priority dispatch" (older,
# established connections) and later "non-priority" connections. As a
# stand-in for "older/established capacity", we treat the largest wind
# farms by installed capacity (p_nom) as priority.
#
# STATE THIS ASSUMPTION EXPLICITLY IN YOUR PRESENTATION. It is invented,
# not derived from the data.

wind_generators = n_baseline.generators[n_baseline.generators.carrier == "wind"]

# Sort wind farms by installed capacity (p_nom), biggest first
wind_sorted = wind_generators.sort_values("p_nom", ascending=False)

# Take the top half as "priority" — you can change this fraction/logic and
# just document whatever you choose
n_priority = len(wind_sorted) // 2
priority_farms = wind_sorted.index[:n_priority].tolist()
non_priority_farms = wind_sorted.index[n_priority:].tolist()

print("Priority wind farms (assumed):", priority_farms)
print("Non-priority wind farms (assumed):", non_priority_farms)

# ---------------------------------------------------------------------------
# STEP 3: Run the BASELINE (no priority effect — everyone at marginal_cost=0)
# ---------------------------------------------------------------------------
gridkit.solve(n_baseline)
gridkit.freeze_dispatch(n_baseline)
n_baseline.lpf(n_baseline.snapshots)

baseline_curtailment = gridkit.dispatch_down(n_baseline)
# This should be a table/series of MWh curtailed per generator

# ---------------------------------------------------------------------------
# STEP 4: Run the PRIORITY scenario
# ---------------------------------------------------------------------------
# Reload a fresh copy of the network so we don't carry over the solved
# state from the baseline run
n_priority_scenario = gridkit.load(network_name, scope)

# Give priority farms a tiny negative cost. This is small enough not to
# meaningfully distort total system cost, but tells the optimiser:
# "if you must cut wind somewhere, cut the non-priority farms first,
# because keeping the artificially-cheaper priority farms running
# minimises total cost."
n_priority_scenario.generators.loc[priority_farms, "marginal_cost"] = -0.5
# non-priority wind farms are left at their original cost (0.0)

gridkit.solve(n_priority_scenario)
gridkit.freeze_dispatch(n_priority_scenario)
n_priority_scenario.lpf(n_priority_scenario.snapshots)

priority_curtailment = gridkit.dispatch_down(n_priority_scenario)

# ---------------------------------------------------------------------------
# STEP 5: Compare the two runs
# ---------------------------------------------------------------------------
comparison = pd.DataFrame({
    "baseline_curtailed_MWh": baseline_curtailment["dispatch_down_mwh"],
    "priority_scenario_curtailed_MWh": priority_curtailment["dispatch_down_mwh"],
})
comparison["difference_MWh"] = (
    comparison["priority_scenario_curtailed_MWh"]
    - comparison["baseline_curtailed_MWh"]
)
comparison["status"] = comparison.index.map(
    lambda g: "priority" if g in priority_farms
    else ("non-priority" if g in non_priority_farms else "other")
)

comparison.to_csv("q6_curtailment_comparison.csv")
print("\nSaved comparison table to q6_curtailment_comparison.csv")
print(comparison.sort_values("difference_MWh"))

# ---------------------------------------------------------------------------
# STEP 6: Cross-reference against shift factors — THE HEADLINE FINDING
# ---------------------------------------------------------------------------
# You need Lucy's shift_factors.csv for this step. Once you have it,
# load it here. It should have one row per generator/node and one column
# per monitored circuit (the "binding" or congested lines).
try:
    # Lucy's file is "long" format: one row per generator, with columns
    # generator, bus, carrier, p_nom, shift_factor — NOT one column per
    # power line. The "_1" in the filename suggests this is the shift
    # factor table for ONE specific binding line (line/circuit #1).
    # If she sends more files (shift_factors_2.csv, etc.) for other
    # binding lines, repeat this whole block for each one.
    shift_factors = pd.read_csv("shift_factors_1.csv")

    # Use the generator name as the index so we can join it against our
    # curtailment comparison table (which is also indexed by generator name)
    shift_factors = shift_factors.set_index(shift_factors.columns[0])

    # The column is named after the specific line/circuit it measures —
    # in this case line 5041-17010-2. If Lucy sends more files for other
    # binding lines, the column name will differ each time.
    shift_factor_column = "shift_factor_5041-17010-2"

    mismatch_table = comparison.join(shift_factors[[shift_factor_column]])
    mismatch_table = mismatch_table.rename(
        columns={shift_factor_column: "shift_factor_on_binding_line"}
    )

    # The finding to look for:
    #   - non-priority farms that got curtailed (positive curtailment)
    #     despite a LOW shift factor (they weren't the real problem)
    #   - priority farms that kept running (low/no curtailment) despite
    #     a HIGH shift factor (they WERE the real problem, but protected)
    print("\n--- Mismatch table (curtailment vs actual contribution) ---")
    print(mismatch_table.sort_values("shift_factor_on_binding_line", ascending=False))

    mismatch_table.to_csv("q6_mismatch_table.csv")
    print("\nSaved to q6_mismatch_table.csv")

except FileNotFoundError:
    print(
        "\nshift_factors_1.csv not found in this folder — make sure it's "
        "sitting next to this script (in participant-kit/), then re-run."
    )

# ---------------------------------------------------------------------------
# IMPORTANT CAVEAT FOR YOUR PRESENTATION
# ---------------------------------------------------------------------------
# gridkit.dispatch_down()'s docstring states this model has NO SNSP or
# inertia constraint. So this is plain economic (cost-based) dispatch-down,
# NOT a reproduction of EirGrid's real curtailment mechanism, which
# operates through the SNSP limit. Say this clearly up front — this is
# an illustrative analogy to the real policy question, not a simulation
# of the actual rules.
