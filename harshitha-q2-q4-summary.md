# Q2 (Battery siting/sizing) + Q4 (Developer siting narrative) — Harshitha

North-West, WP2033, monitored circuit `5041-17010-2` (Srananagh–Cathaleen's Fall, 210 MVA) — the same target line as Lucy's Q1/Q5 (`TRACK_A_SUMMARY_1.md`) and Chibuikeim's Q3 (`chibuikeim-q3-summary.md`). Script: `k_battery_siting_sizing.py`, reproducible with one command (see header comment). Output: `k_dispatch_down_hourly_WP2033_north-west.csv`.

## One correction to the task brief

The brief says to size from `hourly_flows.csv`'s flow/limit columns ("worst-hour MW reduction," "summed MWh-over-limit"). That doesn't work here: the LOPF that produced those flows already respects the 210 MVA rating, so flow never exceeds `limit_MW` — there's no "excess" to read off the flow column. What's actually lost is wind output withheld to keep the line at its cap, and that only shows up in the generator dispatch, not the line flow. So this re-solves the network directly and reads dispatch-down from there.

## Method, and a bug caught + fixed along the way

Splitting constraint-based vs. surplus-based dispatch-down **per generator** by subtracting (real-ratings run) − (all-ratings-lifted run) is invalid — lifting ratings can shift the whole optimal dispatch pattern, so an individual generator's loss can go *down* when ratings are lifted even though the aggregate is well-behaved. (Caught this directly: one generator showed 0 MW curtailed with real ratings but 88 MW curtailed with ratings lifted, at one hour — a different dispatch pattern, not this constraint.) That's exactly why the kit's own `examples/b_lopf_dispatch.py` only ever reports this split as one number for the whole system.

Fixed by splitting at the aggregate-hourly level (matches the kit's own whole-week method exactly), then allocating each hour's validated total across generators pro-rata by their own share of that hour's real curtailment.

**Corrected total: 588.6 MWh of wind curtailed for this constraint over the 168-hour week.**

## Reconciliation with Chibuikeim's Q3 DLR numbers

`j_dlr_sensitivity_WP2033_north-west.csv` (0% uplift row) reports **3,660.6 MWh/week** via the kit's stock `gridkit.dispatch_down()` — that's *total* dispatch-down (constraint-based + surplus-based combined), not constraint-based alone. Re-running the same real-ratings-vs-ratings-lifted comparison here independently:

- total dispatch-down, real ratings: **3,660.6 MWh** — exact match to Chibuikeim's number
- surplus-based only, ratings lifted: **3,072.0 MWh** — exact match to Chibuikeim's own +30%-uplift row (3,072.0), which makes sense: near-full relief of this line converges to the pure-surplus floor
- **3,660.6 − 3,072.0 = 588.6 MWh — exact match to this doc's constraint-based total**, computed via a completely independent method (aggregate-hourly + pro-rata vs. one single whole-week solve)

No discrepancy — these are the same system, split two consistent ways, cross-checked against a teammate's independently-written script.

## Sign matters more than magnitude — checked against real dispatch, not just the shift-factor sheet

`shift_factors_1.csv` has two groups on this circuit:

| group | members | shift factor |
|---|---|---|
| A | Corderry, Glenree, Sligo | **+0.579** |
| B | Ardnagappary, Tievebrack, Binbane, Cathaleen's Fall, Clogher, Croaghonagh, Drumkeen, Letterkenny, Trillick, Sorne Hill | **−0.238** |
| — | Moy | ~0.000 (not electrically on this corridor) |

Largest magnitude is group A (Corderry, 0.579). But the sign is opposite to group B, and sign — not magnitude — determines whether curtailing a farm relieves this line or worsens it: flow on this circuit is negative every one of the 52 binding hours, so a positive-shift-factor farm structurally cannot relieve it.

**Confirmed against the actual solved dispatch: Corderry, Glenree, and Sligo each show 0.0 MWh of constraint-based curtailment across the entire week** — the optimiser never once curtails them for this constraint, exactly as the sign predicts. Every megawatt-hour of the 588.6 MWh sits in group B.

**Flag for the team — Track A's Q5 section currently states "Corderry wind alone offers 43 MW" of relief at the peak hour.** That's the raw \|shift factor\| × available-MW number, before checking sign against this line's actual flow direction — the same "pick the largest \|shift factor\|" trap this section exists to correct. Worth a one-line caveat there (or a pointer to this doc) before the panel, since a judge who checks the actual dispatch would find Corderry contributes zero real relief on this line. Flagging rather than editing `TRACK_A_SUMMARY_1.md` directly since it's Lucy's file — happy to add the caveat myself if the team's fine with it.

## Where the curtailment actually concentrates

| rank | node | MWh curtailed (week) | cumulative % |
|---|---|---|---|
| 1 | **Drumkeen** | 346.5 | 58.9% |
| 2 | **Binbane** | 197.9 | 92.5% |
| 3 | Letterkenny | 41.1 | 99.5% |
| 4 | Clogher | 3.1 | 100.0% |
| — | Ardnagappary, Tievebrack, Cathaleen's Fall, Croaghonagh, Trillick, Sorne Hill, Moy | 0.0 | — |

Two sites — Drumkeen and Binbane — cover 92.5% of everything, which is a different picture from nameplate capacity (Croaghonagh is the largest group-B generator at 139.2 MW and contributes 0.0 MWh) — impact tracks which farms are actually generating heavily in the hours the corridor is already full, which only the real dispatch run reveals.

## Recommended siting & sizing

**Single site — Drumkeen:** covers 58.9% of all constraint-based curtailment on its own.
- Power rating: **42.9 MW** (worst single hour)
- Energy, conservative (sum of every curtailed hour, no discharge in between): **346.5 MWh**
- Energy, realistic (largest contiguous congestion episode — 10 episodes across the week): **100.8 MWh over a 4-hour episode**

**Two sites — Drumkeen + Binbane:** covers 92.5% combined.
- Power rating: **48.4 MW** (worst combined hour)
- Energy, conservative: **544.4 MWh**
- Energy, realistic (largest contiguous episode): **232.6 MWh over 6 hours**

Two sites gets to 92.5% — very little left to chase after that (Letterkenny only adds 7%). Drumkeen + Binbane is the natural two-site pitch, not Drumkeen + Letterkenny.

**For the deck:** lead with Drumkeen alone (42.9 MW / ~101 MWh episodic — small, realistic, buildable single-site number), show Drumkeen + Binbane as the "92.5% instead of 59%" upsell. State plainly that 346.5 MWh is an upper bound assuming zero discharge between episodes — the 101 MWh episodic figure is the number you'd actually design a battery to.

## Q4 — Developer siting narrative

**One-sentence version:** on this corridor, whether a location is good for a wind developer or a battery developer isn't a matter of degree — it's which side of Srananagh you're on.

**Attractive for new wind (low risk of adding to this constraint):** Corderry, Glenree, Sligo — the positive-shift-factor group. New capacity here sits electrically close to the Srananagh import point; more output there relieves the constraint rather than adding to it. Confirmed against real dispatch: zero curtailment here across the whole week, regardless of how much they generated.

**Attractive for BESS (this is where the real problem lives):** the negative-shift-factor group, but overwhelmingly concentrated at two of its ten members — Drumkeen and Binbane, 92.5% of the total between them. New wind added at these two without storage directly worsens dispatch-down; storage sited here directly relieves it. Shift-factor sign tells a developer which side of the network they're on; it doesn't say which specific farm within that side actually matters — that took running the real dispatch.

**The threshold isn't a number, it's a side, and even the side isn't the whole story.** The group clusters tightly on shift factor alone (−0.238 for ten different farms), so magnitude alone doesn't discriminate within it — but it also doesn't reveal that two farms dominate while eight contribute nothing. That distinction only came from the real dispatch run: shift factors tell you the mechanism, not the answer.

**Honest caveats for this slide:** WP2033 is a synthetic weather week (Ornstein–Uhlenbeck / Gaussian-field wind, not historical or forecast) — MWh figures are indicative of the mechanism, not a real-world forecast for these specific farms. Costs anywhere in the model are round-number placeholders (wind bids −1 EUR/MWh to make curtailment a last resort, not a real market price). This is a DC linear approximation — no voltage, no reactive power, no N-1 — a screening result, not an operational recommendation.

---
*Reproducible with `python k_battery_siting_sizing.py` from the repo root (needs `grid_TF_Wind/participant-kit` on the path, as in the script header). Re-run and cross-checked against this repo's own copy of the kit before this commit — see reconciliation section above.*
