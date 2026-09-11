# Q6: Priority vs Non-Priority Wind Farms

## What question this answers

Some wind farms in Ireland hold legal "priority dispatch" status, meaning
they're protected from being switched off first when the grid gets
congested. The dataset for this hackathon has no such flag on any
generator. This analysis asks: **if we invented a priority/non-priority
split, would it create unfairness — where a "protected" farm keeps
running despite genuinely causing congestion, while an "unprotected" farm
gets cut despite barely contributing?**

## The assumption we made (stated explicitly, as required)

The dataset has no priority/non-priority flag. We invented one, based on
a real-world stand-in: Ireland's grid connection policy historically
split generators into pre-2004 "priority dispatch" (older, established
connections) and later "non-priority" connections. As a proxy for
"older/established capacity," **we treat the 7 largest wind farms (by
installed capacity, `p_nom`) out of 14 in the North-West region as
priority, and the remaining 7 as non-priority.**

This is an illustrative choice, not something derived from the data.
A different cutoff or logic (e.g. by connection date, by owner) would
be equally defensible — we picked farm size because it was the cleanest
proxy available with no extra data required.

## How the model actually enforces "priority" (the mechanism)

The simulation dispatches generators by minimising total system cost.
Wind normally costs €0/MWh to run, so the optimiser has no reason to
prefer one wind farm over another when a line is congested — ties are
broken arbitrarily.

To simulate priority protection without changing how the solver itself
works, we give priority farms a **small negative marginal cost (-0.5)**
in the priority scenario, while non-priority farms stay at €0. This
tells the optimiser: "if wind must be cut somewhere, cut the €0 farms
first, since keeping the artificially-cheaper priority farms running
minimises total cost." The perturbation is small enough not to
meaningfully distort overall system cost.

We run the model **twice** — once with everyone at cost 0 (baseline),
once with priority farms nudged to -0.5 (priority scenario) — and
compare curtailment per farm between the two runs.

## The headline finding

We cross-referenced each farm's curtailment against its **shift factor**
(how much its output affects flow on the binding/congested line —
EirGrid's own metric for "how responsible is this farm for this
congestion"). The result:

**Ten of the fourteen farms share nearly identical shift factors on the
binding line — meaning they are, by EirGrid's own methodology, equally
responsible for the congestion.** After adding priority status, curtailment
moved almost entirely off the priority-labelled farms in that group and
onto the non-priority ones with the *identical* shift factor.

Concretely: **~2,400-2,600 MWh of curtailment landed on non-priority
farms that could instead have come from an equally-or-more culpable
priority farm** (see the corrected numbers below — this used to say
"~3,000+ MWh" before the sign-correction removed two wrongly-implicated
farms). The unfairness isn't that one farm caused more congestion than
another — it's that **physically indistinguishable contributors to the
same constraint were treated completely differently, purely because of
a label.**

## Two versions of this result (robustness check)

**CORRECTED 2026-09-11 (Track A audit F-02 and F-04) — both the rating
and the culpability logic below have changed. Do not quote the old
301.9 MVA / 3,062.4 MWh / six-farm numbers; they are superseded.**

Two separate fixes landed at once, so the numbers below aren't
comparable to any earlier version of this table:

1. **Rating corrected: 301.9 MVA -> 213.0 MVA.** The 301.9 MVA figure
   this section used to call "team standard" has been retracted by Q3
   (29-year weather archive, no solar term, perpendicular-wind
   assumption — see `dlr-2024-real-weather-rewrite.md`). The current,
   authoritative winter figure is 213.0 MVA.
2. **Culpability logic corrected: abs(shift factor) -> signed, same-side
   comparison.** The old logic ranked "culpability" by `|shift factor|`
   alone. This line binds at NEGATIVE flow (confirmed empirically by the
   script itself, not assumed), so a POSITIVE-shift-factor farm being
   curtailed makes the constraint worse, not better — it was never a
   legitimate "equally-or-more culpable" substitute. Corderry (the
   single largest farm, +0.579 shift factor, and therefore "priority" by
   this analysis's own size-based rule) had the largest `|shift factor|`
   of any farm on the line, so the old logic let it anchor part of the
   "unfair" claim even though curtailing Corderry cannot relieve this
   constraint at all. Fixed: only same-side (same-sign) farms compete
   for "most culpable."

Both fixes actually run end-to-end (not reasoned through):

| Scenario | Line rating used | Total baseline curtailment | "Unfair" MWh (sign-corrected) |
|---|---|---|---|
| **Dynamic Line Rating (current, corrected)** | **213.0 MVA** | **3,579.8 MWh** | **2,427.2 MWh** |
| Static rating (robustness check) | 210 MVA | 3,660.6 MWh | 2,555.3 MWh |

**The pattern still holds under both ratings** — same three non-priority
farms (`Cathaleen's Fall, Sorne Hill, Trillick`) are flagged as unfairly
curtailed in both scenarios, so the rating correction alone doesn't
change which farms the finding is about. What DID change is the set
itself: the old (uncorrected-sign) analysis named **six** farms —
`Ardnagappary, Cathaleen's Fall, Sligo, Sorne Hill, Tievebrack,
Trillick`. Two of those six (`Ardnagappary`, `Tievebrack`) only appeared
because the old logic let Corderry or Glenree (both positive-shift-
factor, wrong side of this constraint) count as their "more culpable"
priority farm. Correctly excluded now — the script prints exactly this
substitution so it's auditable, not asserted.

*Note: the DLR figure is Q3's derived value from real 2024 weather at
the nearest station; we have not independently re-derived it ourselves,
only re-run the model with it substituted in.*

## Important caveats — read before quoting this anywhere

- **This is not real EirGrid curtailment.** The model has no SNSP or
  inertia constraint (confirmed directly in `gridkit.py`'s own
  docstring). What it produces is plain economic (cost-based)
  dispatch-down. Real priority-dispatch rules operate specifically
  within EirGrid's SNSP curtailment mechanism, which this model does not
  represent. Treat this as an **illustrative analogy** to the real
  policy question, not a reproduction of the actual mechanism.
- **The priority/non-priority split is invented**, not derived from any
  real designation in the data (see above).
- **Shift factor sign is now checked, not ignored** (see the correction
  above) — computed in-script via `flowmath.shift_factors()` directly
  against the solved network, rather than read from an external
  `shift_factors_1.csv` that wasn't committed on this branch. The line's
  own binding-flow direction is determined empirically from the solved
  network each run, not assumed.
- **This analysis covers one binding line only** (`5041-17010-2`). If
  other congested lines exist in the North-West region, this same method
  would need repeating for each to give a full picture.
- **Small numerical differences between re-runs are expected.** Wind
  farms priced at or near €0 marginal cost can produce "tied" optimal
  solutions (LP degeneracy) — a different machine or solver version may
  distribute curtailment slightly differently between equally-costed
  farms, even though the total and the overall pattern stay the same.

## Files in this folder

- `q6_priority_analysis_bugfix.py` — the corrected script (213.0 MVA DLR
  rating, in-script shift factors, sign-corrected culpability logic).
  Change the two `gridkit.set_rating(..., 213.0)` calls to `210.0` to
  reproduce the static-rating robustness-check row above.
- `q6_curtailment_comparison.csv` — per-farm curtailment, baseline vs priority scenario
- `q6_mismatch_table.csv` — curtailment cross-referenced against signed shift factor, with the fairness mismatch flagged

## How to reproduce

From `participant-kit/`, with the virtual environment activated and
`shift_factors_1.csv` present in the same folder:

```
python q6_priority_analysis.py       # static rating version
python q6_priority_analysis_dlr.py   # DLR-adjusted rating version
```

Each prints the comparison table, the mismatch table, and the final
headline number to the terminal, and saves the CSVs listed above.
