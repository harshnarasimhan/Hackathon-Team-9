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

--- DLR PATCH, CORRECTED (2026-09-11, Track A audit F-02) ---
Both network builds below (n_baseline AND n_priority_scenario) get a
real winter-weather rating for 5041-17010-2, replacing the shipped
210 MVA static value. Both need the patch (not just one) since they
represent the same physical network under two different cost policies,
not a "real vs. no-constraint" comparison like Harshitha's Q2 script.

CORRECTED VALUE: 213.0 MVA, not the 301.9 MVA this docstring previously
quoted. That figure has been RETRACTED by Q3 - it came from a 29-year
weather archive with no solar term and a perpendicular-wind assumption,
both of which overstate the rating. The current, authoritative figure
(213.0 MVA winter) comes from 2024-only real weather, real PVGIS solar
heat gain, and the line's real wind-direction geometry - see
dlr-2024-real-weather-rewrite.md. The "VERIFIED... 3,062.4 MWh" claim
this docstring previously made was computed at the retracted 301.9 MVA
rating and has been removed - it does not carry over to 213.0 MVA
un-checked. Re-run this script to get the current number; don't restate
the old one.

--- SHIFT FACTOR SOURCE, CORRECTED (Track A audit F-06) ---
The original script read a pre-computed shift_factors_1.csv from disk.
That file isn't committed on this branch, so a fresh checkout fails at
this step with FileNotFoundError. Shift factors are now computed
in-script via flowmath.shift_factors(), directly against whichever
network this script just solved - self-contained, and automatically
consistent with whatever DLR rating is set above (shift factors don't
depend on line rating anyway, only topology/reactance, so this changes
nothing numerically versus reading a correct external file - it just
removes a fragile cross-branch file dependency).

--- CULPABILITY LOGIC, FIXED (Track A audit F-04) ---
The original "unfair curtailment" check compared farms by
abs(shift_factor) only, ignoring sign. Sign is not cosmetic here: this
line binds at NEGATIVE flow (this script confirms that empirically
below, rather than assuming it), so only NEGATIVE-shift-factor farms
can be curtailed to relieve it - a positive-shift-factor farm being
curtailed makes the flow MORE negative and worsens the constraint, it
doesn't compete for blame. Corderry (the single largest farm, shift
factor +0.579, and therefore in the "priority" set by this script's own
size-based rule) had the largest |shift factor| of anyone, so the old
abs()-based check treated it as the most "culpable" farm on the line -
exactly backwards, since curtailing Corderry cannot relieve this
constraint at all. Fixed by restricting the "equally-or-more culpable"
comparison to farms on the SAME SIDE of the constraint (same sign as
the line's actual binding flow), ranked by signed magnitude within that
group. See STEP 6-7 below for the corrected logic.
"""

import os
import sys

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(_HERE, "grid_TF_Wind", "participant-kit"),           # this file at repo root
    os.path.join(os.path.dirname(_HERE), "grid_TF_Wind", "participant-kit"),  # this file one dir down (e.g. "Alex's Work 3.1/")
):
    if os.path.isfile(os.path.join(_candidate, "gridkit.py")):
        sys.path.insert(0, _candidate)
        break
else:
    raise ModuleNotFoundError(
        "could not find gridkit.py - run this from the repo root or check "
        "your checkout layout")
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

MONITORED_LINE = "5041-17010-2"

n_baseline = gridkit.load(network_name, scope)
gridkit.set_rating(n_baseline, MONITORED_LINE, 213.0)  # DLR PATCH (corrected): real-weather winter figure (was 210.0 static / 301.9 retracted)

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
gridkit.set_rating(n_priority_scenario, MONITORED_LINE, 213.0)  # DLR PATCH (corrected): real-weather winter figure (was 210.0 static / 301.9 retracted)

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
# FIXED (Track A audit F-06): computed in-script via flowmath instead of
# reading an external shift_factors_1.csv that isn't committed on this
# branch. Uses n_baseline (shift factors are topology/reactance-only, so
# it makes no difference which of the two solved networks this is read
# from - they share the same topology).
sf_table = flowmath.shift_factors(n_baseline, MONITORED_LINE, reference="load")
shift_factors_by_gen = sf_table["shift_factor"]  # indexed by generator name

mismatch_table = comparison.join(shift_factors_by_gen.rename("shift_factor_on_binding_line"))

# FIXED (Track A audit F-04): determine which flow DIRECTION this line
# actually binds in, empirically, rather than assuming - a sign-blind
# abs(shift_factor) comparison is not just less precise than a signed
# one, it can name the wrong farm as "culpable" (see docstring above).
binding_hours = gridkit.binding(n_baseline)
if MONITORED_LINE not in binding_hours.index:
    raise SystemExit(
        f"{MONITORED_LINE} does not bind at all in this run (rating may be "
        f"too wide) - the culpability comparison below has nothing to check")
flows_at_line = n_baseline.lines_t.p0[MONITORED_LINE]
rating = n_baseline.lines.at[MONITORED_LINE, "s_nom"]
near_binding = flows_at_line[flows_at_line.abs() >= 0.999 * rating]
binding_flow_sign = 1 if (near_binding > 0).sum() >= (near_binding < 0).sum() else -1
print(f"\n{MONITORED_LINE} binds at {'positive' if binding_flow_sign > 0 else 'negative'} "
      f"flow in {len(near_binding)}/{len(flows_at_line)} near-binding hours checked - "
      f"only shift factors with this same sign can relieve this constraint.")

# The finding to look for:
#   - non-priority farms that got curtailed (positive curtailment)
#     despite NOT being on the culpable side of this constraint
#   - priority farms that kept running (low/no curtailment) despite
#     BEING on the culpable side (they WERE the real problem, but
#     protected)
print("\n--- Mismatch table (curtailment vs actual contribution) ---")
print(mismatch_table.sort_values("shift_factor_on_binding_line", ascending=False))

mismatch_table.to_csv("q6_mismatch_table.csv")
print("\nSaved to q6_mismatch_table.csv")

# -----------------------------------------------------------------------
# STEP 7: The headline number
# -----------------------------------------------------------------------
# We want ONE figure to say out loud to judges, not just "look at the
# table." Logic: for every non-priority farm that got curtailed, check
# whether there's a priority farm on the SAME SIDE of the constraint
# (same sign of shift factor as the line's actual binding flow) that is
# equally-or-more culpable (equal-or-more-extreme signed shift factor in
# the culpable direction) but was curtailed LESS. If so, that
# non-priority farm's curtailment counts as "unfair" — it took a hit
# that could instead have come from a farm that was contributing at
# least as much to the SAME constraint, but was protected by its
# priority label instead.
#
# A farm on the OTHER side of the constraint (opposite sign) is never a
# candidate "equally-or-more culpable" substitute, no matter how large
# its |shift factor| is — curtailing it doesn't relieve this line, it
# worsens it (see docstring). This is the actual fix for F-04: the old
# version used abs(shift_factor) here, which let Corderry (the largest
# single farm, priority by this script's own rule, shift factor +0.579
# on a line that binds negative) count as the "most culpable" farm on
# the whole line - backwards, since curtailing Corderry cannot relieve
# this constraint at all.
mismatch_table["signed_culpability"] = mismatch_table["shift_factor_on_binding_line"] * binding_flow_sign
# signed_culpability is now POSITIVE for any farm on the culpable side
# (same sign as the binding flow), regardless of which raw sign that
# was - so "more culpable" is simply "larger signed_culpability" from
# here on, uniformly.

priority_rows = mismatch_table[mismatch_table["status"] == "priority"]
non_priority_rows = mismatch_table[mismatch_table["status"] == "non-priority"]

unfair_mwh_total = 0.0
unfair_farms = []
excluded_wrong_side = []  # priority farms that would have "won" under the old abs() logic but are on the wrong side

for name, row in non_priority_rows.iterrows():
    curtailed = row["priority_scenario_curtailed_MWh"]
    culpability = row["signed_culpability"]

    if curtailed <= 0:
        continue  # nothing curtailed here, nothing to count as unfair
    if culpability <= 0:
        continue  # this non-priority farm isn't even on the culpable side itself

    # any priority farm that is ALSO on the culpable side, equally-or-more
    # responsible (equal-or-higher signed_culpability), but curtailed less?
    protected_despite_culpability = priority_rows[
        (priority_rows["signed_culpability"] >= culpability)
        & (priority_rows["priority_scenario_curtailed_MWh"] < curtailed)
    ]
    wrong_side_would_have_matched = priority_rows[
        (priority_rows["shift_factor_on_binding_line"].abs() >= abs(row["shift_factor_on_binding_line"]))
        & (priority_rows["signed_culpability"] <= 0)
        & (priority_rows["priority_scenario_curtailed_MWh"] < curtailed)
    ]
    if len(wrong_side_would_have_matched) and not len(protected_despite_culpability):
        excluded_wrong_side.append((name, list(wrong_side_would_have_matched.index)))

    if len(protected_despite_culpability) > 0:
        unfair_mwh_total += curtailed
        unfair_farms.append(name)

print("\n=== HEADLINE FINDING (sign-corrected) ===")
print(
    f"{unfair_mwh_total:.1f} MWh of curtailment landed on non-priority "
    f"farms that could instead have come from an equally-or-more "
    f"culpable priority farm ON THE SAME SIDE of this constraint."
)
print(f"Farms affected: {unfair_farms}")
if excluded_wrong_side:
    print(f"\n[info] {len(excluded_wrong_side)} farm(s) would have been counted "
          f"'unfair' under the old abs(shift_factor) logic, but the only "
          f"'more culpable' priority farm found was on the WRONG side of "
          f"the constraint (curtailing it would worsen, not relieve, this "
          f"line) - correctly excluded now:")
    for name, wrong_side_farms in excluded_wrong_side:
        print(f"    {name}: would have pointed at {wrong_side_farms}")

# ---------------------------------------------------------------------------
# IMPORTANT CAVEAT FOR YOUR PRESENTATION
# ---------------------------------------------------------------------------
# gridkit.dispatch_down()'s docstring states this model has NO SNSP or
# inertia constraint. So this is plain economic (cost-based) dispatch-down,
# NOT a reproduction of EirGrid's real curtailment mechanism, which
# operates through the SNSP limit. Say this clearly up front — this is
# an illustrative analogy to the real policy question, not a simulation
# of the actual rules.
