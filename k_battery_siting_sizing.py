"""
Q2 (battery siting/sizing) + Q4 (developer siting narrative) — Harshitha

Network: WP2033 (2033 winter peak), scope: north-west. Target line: the
Q1 target line, 5041-17010-2 (confirmed the only line that ever binds in
this scope — cross-checked against Track A's own Q1 ranking, which shows
zero other north-west lines reaching 100% loading at any hour).

Why this doesn't just read `hourly_flows.csv`'s flow/limit columns:
the LOPF that produced that file already respects the 210 MVA rating, so
flow never exceeds limit_MW — there is no "MW over limit" to sum. What's
actually lost is wind output withheld to keep the line at its cap, and
that lives in the generator dispatch, not the line flow. So this script
re-solves the network directly with gridkit and reads dispatch-down from
there, split into constraint-based (this line) vs. surplus-based (no
network could have absorbed it) — see the method note below.

METHOD NOTE (important - a bug was caught and fixed here):
Splitting constraint-based vs. surplus-based dispatch-down PER GENERATOR
by directly subtracting (real-rating run) minus (all-ratings-lifted run)
is invalid: lifting ratings can shift the whole optimal dispatch pattern,
so an individual generator's "lost" can go DOWN when ratings are lifted,
even though the aggregate total is always well-behaved. (Confirmed: one
generator showed 0 MW curtailed with real ratings but 88 MW curtailed
with ratings lifted, at one hour - an artifact of a different dispatch
pattern, not this constraint.) The kit's own reference script
(examples/b_lopf_dispatch.py) only ever reports this split as ONE number
for the whole system, for exactly this reason.

Fixed here by doing the split at the aggregate-hourly level only (which
matches the kit's own whole-week aggregate method exactly - verified:
588.6 MWh either way), then allocating each hour's validated total across
generators pro-rata by each generator's own share of that hour's real
curtailment. That gives a valid per-generator, per-hour breakdown without
the invalid subtraction.

Reconciliation with Chibuikeim's Q3 DLR numbers (examples/j_dlr_rating_
sensitivity.py / j_dlr_sensitivity_WP2033_north-west.csv): that script
reports TOTAL dispatch-down (constraint-based + surplus-based combined)
via the kit's stock gridkit.dispatch_down(), at 0% uplift = 3,660.6
MWh/week. This script's constraint-based-ONLY total is 588.6 MWh/week.
These are consistent, not conflicting: re-running the stock method here
gives total(3,660.6) - free(3,072.0) = 588.6 - an exact match to the
corrected per-generator pipeline below, confirmed independently.

Run:
    python k_battery_siting_sizing.py
Requires the participant-kit (gridkit.py) on the Python path.
"""
import sys
sys.path.insert(0, "grid_TF_Wind/participant-kit")
import gridkit
import pandas as pd
import numpy as np

gridkit.quiet()

LINE = "5041-17010-2"

# --- real ratings run ---
n = gridkit.load("WP2033", "north-west")
gridkit.solve(n)
gridkit.freeze_dispatch(n)
n.lpf(n.snapshots)

avail = n.generators_t.p_max_pu
cols = [c for c in avail.columns if c in n.generators_t.p]
offered = avail[cols] * n.generators.loc[cols, "p_nom"]
taken = n.generators_t.p[cols].clip(lower=0.0)
lost = (offered - taken).clip(lower=0.0)

# --- ratings-lifted run (isolates surplus-based dispatch-down) ---
m = gridkit.load("WP2033", "north-west")
m.lines["s_nom"] = m.lines["s_nom"] * 1000
gridkit.solve(m)
gridkit.freeze_dispatch(m)
m.lpf(m.snapshots)

avail_m = m.generators_t.p_max_pu
cols_m = [c for c in avail_m.columns if c in m.generators_t.p]
offered_m = avail_m[cols_m] * m.generators.loc[cols_m, "p_nom"]
taken_m = m.generators_t.p[cols_m].clip(lower=0.0)
lost_nolimit = (offered_m - taken_m).clip(lower=0.0).reindex(columns=lost.columns).fillna(0)

# --- aggregate-hourly split, then pro-rata allocation back to generators ---
total_hour = lost.sum(axis=1)
free_hour = lost_nolimit.sum(axis=1)
network_hour = (total_hour - free_hour).clip(lower=0.0)
share = lost.div(total_hour.replace(0, np.nan), axis=0).fillna(0.0)
constraint_based = share.mul(network_hour, axis=0)  # generator x hour

# sanity check: aggregate-hourly split must equal the kit's own whole-week method
whole_week_check = max(0.0, lost.sum().sum() - lost_nolimit.sum().sum())
assert abs(constraint_based.sum().sum() - whole_week_check) < 1e-6, "aggregate mismatch"

rows = []
for gen in cols:
    bus = n.generators.at[gen, "bus"]
    carrier = n.generators.at[gen, "carrier"]
    for hr in n.snapshots:
        rows.append({
            "hour": hr,
            "generator": gen,
            "bus": bus,
            "carrier": carrier,
            "offered_MW": round(offered.at[hr, gen], 3),
            "dispatched_MW": round(taken.at[hr, gen], 3),
            "curtailed_MW": round(lost.at[hr, gen], 3),
            "constraint_based_MW": round(constraint_based.at[hr, gen], 3),
            "surplus_based_MW": round(lost.at[hr, gen] - constraint_based.at[hr, gen], 3),
        })
out = pd.DataFrame(rows)
out.to_csv("k_dispatch_down_hourly_WP2033_north-west.csv", index=False)

print(f"corrected total constraint-based MWh (week): {constraint_based.sum().sum():.1f}")
print(f"reconciliation check - total dispatch-down (all causes): {lost.sum().sum():.1f} MWh")
print(f"reconciliation check - surplus-based only (ratings lifted): {lost_nolimit.sum().sum():.1f} MWh")

by_gen = constraint_based.sum().sort_values(ascending=False)
by_gen_pct = (by_gen / by_gen.sum() * 100).round(1)
print("\nranking (MWh curtailed for this constraint, week total):")
cum = 0
for gen, mwh in by_gen[by_gen > 0].items():
    cum += mwh
    print(f"  {gen:30s} {mwh:8.1f} MWh  ({cum/by_gen.sum()*100:5.1f}% cum)")

# shift-factor sign check (Q4 narrative basis)
sf = pd.read_csv("shift_factors_1.csv")
sf_col = [c for c in sf.columns if c.startswith("shift_factor_")][0]
print(f"\nsign check against {sf_col}:")
for _, r in sf.iterrows():
    curt = by_gen.get(r["generator"], 0.0)
    print(f"  {r['generator']:30s} shift_factor={r[sf_col]:+.3f}  constraint_based_MWh={curt:8.1f}")
