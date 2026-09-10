# Step 4 — Validation and comparison (v3, real results, DLR-corrected)

Owner role: Person 5. Checks whether Step 3B's proposed groups (`simple` vs
`multiline_aware`) actually relieve a target line's overload in a REAL
re-solved DC model, without obviously creating a worse problem elsewhere.

**This supersedes the earlier version of this document.** That version was
produced by a script (`p_step4_validation_comparison.py`, then v2) with two
bugs since fixed, and without the DLR patch applied. This is the real,
DLR-corrected v3 run — see below for exactly what changed and why the
numbers moved.

```bash
python p_step4_validation_comparison_v3.py
```

Cases tested: the 3 binding lines (of Step 1's 6) where Step 3B's Method B
found at least one genuine adverse cross-line trade-off —
`3082-3122-1`, `3581-89516-1`, `3691-4041-1` — the only lines where
"multi-line-aware" can differ from "simple" at all.

## What changed since the last version of this document

1. **The DLR patch is now applied on every network load.** Line
   `5041-17010-2` (the project's separately-validated DLR line — see
   `dlr-presentation-summary.md`) is patched to its real winter rating
   (301.8541975480315 MVA, verified directly against
   `baseline_hourly_flows.csv` — not the rounded 301.9 used earlier) before
   every solve, so this script is now validating against the same network
   that actually produced `binding_lines.csv` / `baseline_hourly_flows.csv`,
   not a slightly different one. Confirmed as a hard-fail check: `5041-17010-2`
   does not appear as a selected binding line — consistent with the DLR
   finding that it drops out of the all-island binding-lines list entirely.
2. **The 10 MW curtailment cap is applied per NODE, not per generator**
   (multiple generators can share a bus). This alone changed the total
   curtailed MW by roughly 5-40x versus the original (buggy) run — verified
   with a standalone, gridkit-free unit test (`--test` mode) before trusting
   the full run.
3. **The comparison table now reports all 5 metrics the brief asks for**
   (previously only 3): target overload relieved, renewable MW reduced, new
   monitored-line overloads, nodes curtailed, and adverse-tradeoff nodes
   excluded.
4. **Real files, not filenames assumed correct.** `proposed_groups.csv` was
   directly checked against its actual column headers, `binding_lines.csv`
   is hard-validated against `SCENARIO`/`SCOPE` before anything runs, and the
   DLR rating constant was checked against all 168 real rows for
   `5041-17010-2` in `baseline_hourly_flows.csv` rather than assumed.
5. **This run executes each network solve in its own subprocess.** Pure
   engineering, not methodology — running ~15 full-network LOPF solves
   in one long-lived process exhausted the runtime's memory ceiling twice;
   isolating each solve in a short-lived subprocess (identical arithmetic,
   confirmed against the in-process run before the ceiling was hit) let the
   full run complete without changing a single number.

## Final results (real, v3, DLR-corrected)

| case | target line | hour used | overload before | method | cut applied | overload after | relief | status |
|---|---|---|---|---|---|---|---|---|
| 1 | 3581-89516-1 | 2030-01-17 09:00 | 2.00 MW | simple | 219.54 MW | 0.00 MW | 2.00 MW | relieved_clean |
| 1 | 3581-89516-1 | 2030-01-17 09:00 | 2.00 MW | multiline_aware | 128.23 MW | 0.00 MW | 2.00 MW | relieved_clean |
| 2 | 3082-3122-1 | 2030-01-16 13:00 | 71.06 MW | simple | 521.57 MW | 15.03 MW | 56.02 MW | partial_relief |
| 2 | 3082-3122-1 | 2030-01-16 13:00 | 71.06 MW | multiline_aware | 511.57 MW | 19.76 MW | 51.30 MW | partial_relief |
| 3 | 3691-4041-1 | — | 0.00 MW (no genuine overload across all 5 near-binding hours tried) | both | — | — | — | no_genuine_overload_to_relieve |

Summed comparison table:

| method | overload relieved | renewable MW reduced | new line overloads | nodes curtailed | adverse-tradeoff nodes excluded |
|---|---|---|---|---|---|
| simple | 58.02 MW | 741.11 MW | 0 | 93 | 0 |
| multiline_aware | 53.30 MW | 639.80 MW | 0 | 79 | 15 |

## Reading this honestly — the story changed from the earlier (buggy) version

The old version of this document said avoiding the 15 adverse-tradeoff
nodes cost *extra* curtailment for *less* relief. That was wrong — it was
computed with the per-generator cap bug (point 2 above), not the corrected
per-node cap. With that fixed:

`multiline_aware` relieves 4.72 MW less overload (53.30 vs 58.02 MW) than
`simple`, using **101.31 MW *less*** renewable curtailment (639.80 vs
741.11 MW) from 14 fewer nodes (79 vs 93). Relief-per-MW-curtailed is
actually slightly *better* for `multiline_aware` (0.0833 vs 0.0783 MW
relieved per MW curtailed) — excluding the 15 adverse-tradeoff nodes isn't
a costly trade-off here, it mostly just means a smaller group with somewhat
less total relief capacity, not a less efficient one. Neither method
creates a new overload on another monitored line in either tested case.
`3691-4041-1` contributes nothing to either total — this validation method
found no genuine natural over-limit tendency to relieve for that line
across all 5 near-binding hours tried, and that's reported as a finding,
not hidden by forcing a number.

**Update `step3b-presentation-summary.md`'s "small, quantifiable amount of
relief... rather than being free" framing to match this** — the real,
corrected picture is "avoiding the flagged side-effects costs some absolute
relief, but not extra curtailment; if anything it's a slightly more
curtailment-efficient group," which is a *better* story for the panel, not
a worse one.

## Files

- `p_step4_validation_comparison_v3.py` — the v3 script (DLR patch applied
  every load, per-node cap-and-split with a standalone unit test, full
  5-metric comparison table, hard-fail input validation).
- `validation_results.csv` — 6 rows, 2 per case, exactly the brief's
  required schema.
- `validation_comparison_table.csv` — summed simple vs multiline_aware,
  all 5 metrics.
- Full run log available on request (subprocess-isolated run, ~15 real
  LOPF solves against the actual all-island WP2033 network).
