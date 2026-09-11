# Step 4 — Validation and comparison (v3, real results, DLR-corrected)

Owner role: Person 5. Checks whether Step 3B's proposed groups (`simple` vs
`multiline_aware`) actually relieve a target line's overload in a REAL
re-solved DC model, without obviously creating a worse problem elsewhere.

**This supersedes the earlier version of this document — twice now.** The
first supersession fixed two script bugs (v2) and applied a DLR patch. This
second correction (2026-09-11, Track A audit F-01/F-02/F-10) fixes the DLR
rating itself — the v3 run below had patched `5041-17010-2` to **301.8541975480315
MVA**, a figure Q3 has since **retracted** (29-year weather archive, no
solar term, perpendicular-wind assumption). The current, authoritative
figure is **213.0 MVA** (2024-only real weather, real PVGIS solar, real
wind-direction geometry — see `dlr-2024-real-weather-rewrite.md`). All
numbers below are a fresh re-run at the corrected rating — see "What
changed since the last version" point 1 and the results table for exactly
how much this moved.

```bash
python p_step4_validation_comparison_v3_final.py --isolated
```

Cases tested: the 3 binding lines (of Step 1's 6) where Step 3B's Method B
found at least one genuine adverse cross-line trade-off —
`3082-3122-1`, `3581-89516-1`, `3691-4041-1` — the only lines where
"multi-line-aware" can differ from "simple" at all.

## What changed since the last version of this document

1. **DLR rating corrected: 301.9 MVA → 213.0 MVA.** The previous version of
   this document patched `5041-17010-2` to 301.8541975480315 MVA, verified
   at the time against `baseline_hourly_flows.csv` — but that CSV has since
   been regenerated at the corrected DLR figure, and the constant here has
   been updated to match (`DLR_RATING_MW = 213.0`). This is a real,
   re-verified rating (2024-only weather, PVGIS solar, real wind-direction
   geometry), not a rounding tweak, and it changes the actual numbers below
   — see the DLR discussion under "Reading this honestly."
2. **The 10 MW curtailment cap is applied per NODE, not per generator**
   (multiple generators can share a bus). This alone changed the total
   curtailed MW by roughly 5-40x versus the original (buggy) run — verified
   with a standalone, gridkit-free unit test (`--test` mode) before trusting
   the full run.
3. **The comparison table reports all 5 metrics the brief asks for**
   (previously only 3): target overload relieved, renewable MW reduced, new
   monitored-line overloads, nodes curtailed, and adverse-tradeoff nodes
   excluded.
4. **Real files, not filenames assumed correct.** `proposed_groups.csv` was
   directly checked against its actual column headers, `binding_lines.csv`
   is hard-validated against `SCENARIO`/`SCOPE` before anything runs, and the
   DLR rating constant was checked against all 168 real rows for
   `5041-17010-2` in `baseline_hourly_flows.csv` rather than assumed.
5. **Every network solve runs in its own subprocess — and this run adds a
   second layer of isolation on top of that (2026-09-11).** Running ~15
   full-network LOPF solves in one long-lived process exhausted the
   original runtime's memory ceiling (confirmed directly: a single
   all-island solve peaks at ~2.0-2.1 GB RSS in a ~3.9 GB container). The
   existing `--isolated` mode (one subprocess per individual solve) fixes
   that — verified: each atomic worker call stays under 2.1 GB and releases
   its memory fully on exit. What's new this run: **the environment this
   re-run happened in also reaps orphaned/background processes between
   separate tool invocations**, which a single long `--isolated` run
   (all 3 lines, ~10+ worker calls, several minutes total) can outlive even
   though no individual worker call is heavy. Added `--only-line=<line_id>`
   and `--append` so the driver can be invoked once per testable line
   (each comfortably finishing inside one shorter invocation) while still
   producing exactly the same final `validation_results.csv` /
   `validation_comparison_table.csv` a single uninterrupted run would —
   confirmed by checking the combined comparison table after each
   incremental call.

## Final results (real, re-run 2026-09-11 at the corrected 213.0 MVA DLR rating)

| case | target line | hour used | overload before | method | cut applied | overload after | relief | status |
|---|---|---|---|---|---|---|---|---|
| 1 | 3581-89516-1 | 2030-01-16 16:00 | 2.00 MW | simple | 232.05 MW | 0.00 MW | 2.00 MW | relieved_clean |
| 1 | 3581-89516-1 | 2030-01-16 16:00 | 2.00 MW | multiline_aware | 128.63 MW | 0.00 MW | 2.00 MW | relieved_clean |
| 2 | 3082-3122-1 | 2030-01-18 05:00 | 54.33 MW | simple | 368.97 MW | 16.77 MW | 37.56 MW | partial_relief |
| 2 | 3082-3122-1 | 2030-01-18 05:00 | 54.33 MW | multiline_aware | 358.97 MW | 21.50 MW | 32.83 MW | partial_relief |
| 3 | 3691-4041-1 | — | 0.00 MW (no genuine overload across all 5 near-binding hours tried) | both | — | — | — | no_genuine_overload_to_relieve |

Summed comparison table:

| method | overload relieved | renewable MW reduced | new line overloads | nodes curtailed | adverse-tradeoff nodes excluded |
|---|---|---|---|---|---|
| simple | 39.56 MW | 601.02 MW | 0 | 71 | 0 |
| multiline_aware | 34.83 MW | 487.60 MW | 0 | 57 | 15 |

**Previous (301.9 MVA, retracted) run, kept for comparison only — do not quote:**

| method | overload relieved | renewable MW reduced | nodes curtailed |
|---|---|---|---|
| simple | 58.02 MW | 741.11 MW | 93 |
| multiline_aware | 53.30 MW | 639.80 MW | 79 |

## Reading this honestly — two corrections layered on top of each other

**First correction (v2→v3, already reflected above):** the old version of
this document said avoiding the 15 adverse-tradeoff nodes cost *extra*
curtailment for *less* relief. That was wrong — it was computed with the
per-generator cap bug, not the corrected per-node cap.

**Second correction (this pass, 301.9 MVA→213.0 MVA):** every number
dropped versus the previously-reported v3 table (simple relief 58.02→39.56
MW, multiline_aware 53.30→34.83 MW) — **not because the method changed**,
but because Case 2's own genuine counterfactual overload at its worst hour
came out smaller at the corrected rating (54.33 MW vs the old run's 71.06
MW). This is the same effect Track A's own audit already documented
elsewhere: widening one line's rating (even a different, unrelated line
like `5041-17010-2`) shifts the LOPF's optimal dispatch pattern
network-wide, so a smaller, more realistic DLR uplift genuinely produces a
different — not just rescaled — set of downstream numbers. Case 1 and
Case 3 were essentially unaffected (2.00 MW relief and "no genuine
overload" respectively, in both the old and corrected runs) because
neither depends on dispatch anywhere near `5041-17010-2`.

**The qualitative story holds at the corrected rating, with the numbers
updated:** `multiline_aware` relieves 4.73 MW less overload (34.83 vs
39.56 MW) than `simple`, using **113.42 MW *less*** renewable curtailment
(487.60 vs 601.02 MW) from 14 fewer nodes (57 vs 71). Relief-per-MW-curtailed
is still *better* for `multiline_aware` (0.0714 vs 0.0658 MW relieved per
MW curtailed, both numbers moved from the old 0.0833/0.0783 but the
ordering and the qualitative conclusion are unchanged) — excluding the
adverse-tradeoff nodes still isn't a costly trade-off, it's a smaller group
with somewhat less total relief capacity, not a less efficient one. Neither
method creates a new overload on another monitored line in either tested
case. `3691-4041-1` still contributes nothing to either total — no genuine
natural over-limit tendency to relieve for that line, at either rating,
across all 5 near-binding hours tried.

**`step3b-presentation-summary.md`'s "small, quantifiable amount of
relief... rather than being free" framing still holds** — "avoiding the
flagged side-effects costs some absolute relief, but not extra curtailment;
if anything it's a slightly more curtailment-efficient group" — just update
any slide quoting the specific 58.02/53.30/741.11/639.80 figures to the
corrected 39.56/34.83/601.02/487.60 ones above.

## Files

- `p_step4_validation_comparison_v3_final.py` — the script, now with
  `--isolated` (per-solve subprocess isolation), `--only-line=<line_id>`
  and `--append` (incremental per-line invocation, new this pass), and
  `--test` (arithmetic self-test, no gridkit needed).
- `validation_results.csv` — 6 rows, 2 per case, exactly the brief's
  required schema.
- `validation_comparison_table.csv` — summed simple vs multiline_aware,
  all 5 metrics, at the corrected 213.0 MVA rating.
- Full run log available on request (this pass ran as 3 separate
  `--only-line` invocations rather than one long-lived process, per point
  5 above — same arithmetic, same final files, different execution
  strategy for this environment's constraints).
