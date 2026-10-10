"""
Step 3B: Candidate group-generation methods
Person 4 — Turns shift_factor_matrix.csv + binding_lines.csv into proposed_groups.csv

=================================================================================
BUILT AGAINST YOUR ACTUAL FILES (step1-binding-lines.zip / step2-shift-factor-matrix.zip)
=================================================================================

Inputs used:
  - binding_lines.csv            (Step 1 output; filtered to selected == True)
  - baseline_hourly_flows.csv    (Step 1 output; used ONLY to work out which
                                   direction each binding line is overloaded in)
  - shift_factor_matrix.csv      (Step 2 output, LONG format — authoritative,
                                   self-describing: node_id, node_name,
                                   monitored_line, shift_factor_signed,
                                   shift_factor_abs, ...)

=================================================================================
METHOD A vs METHOD B — CONCEPTUAL SPLIT (read this before touching the code)
=================================================================================

Method A answers: "Who COULD relieve this constraint?"
    -> builds the actual candidate groups, one per binding line.

Method B answers: "What ELSE happens if we use that node?"
    -> does NOT build a second set of groups. It is a validation/trade-off
       LAYER on top of Method A's candidate rows: for every node already in
       a Method A group, it checks all the OTHER selected binding lines that
       node materially affects, quantifies the estimated side-effect using
       a standard 10 MW hypothetical curtailment, and flags the row for
       manual cross-line validation. It never gets its own group_id.

=================================================================================
TEAM SIGN-OFF ITEMS — flagged the same way your Step 1/2 docs flag theirs
=================================================================================

1. TAU (the "material" threshold) is NOT specified anywhere in your Step 1/2
   files. It's set to a placeholder below (0.05) — this MUST be replaced with
   whatever value your team agrees on. For reference, in your actual
   shift_factor_matrix.csv: median |shift factor| ~= 0.007, 90th percentile
   ~= 0.073, 95th percentile ~= 0.156. NOT a scientifically established value
   — do not present it as one.

2. RELIEF DIRECTION LOGIC:
   Your technical note's sign convention is:
       positive shift_factor_signed = increasing generation at that node
       INCREASES flow in the line's bus0->bus1 direction.
   Combined with baseline_hourly_flows.csv, this script works out, per
   binding line, whether the line is overloaded in the bus0->bus1 (positive
   flow_MW) direction or the bus1->bus0 (negative flow_MW) direction, at the
   snapshots where loading >= LOADING_THRESHOLD (default 99.9%, matching
   your own binding_definition = "loading_ge_99.9pct").

   From that:
     - line overloaded in POSITIVE direction -> relief means REDUCING a node
       whose shift_factor_signed is POSITIVE (its cut lowers flow)
     - line overloaded in NEGATIVE direction -> relief means REDUCING a node
       whose shift_factor_signed is NEGATIVE (its cut raises flow back up)

   All 6 of your currently-selected binding lines had a single, consistent
   overload direction across every near-binding snapshot. If a future run
   produces a line with genuinely mixed-direction overloads, this script
   flags it 'ambiguous' and falls back to magnitude-only screening for that
   line — check the console output for any such warning.

3. THE 10 MW QUANTITATIVE ESTIMATE (new in this version):
   For every Method A candidate row, and for every OTHER selected binding
   line that node materially affects, this script estimates the flow change
   from a hypothetical 10 MW curtailment using the linear shift-factor
   relationship:

       delta_F = SF * delta_P,   with delta_P = -10 MW (a reduction)

   e.g. SF = +0.08  ->  delta_F = 0.08 * -10 = -0.8 MW  (flow decreases 0.8 MW)
        SF = -0.10  ->  delta_F = -0.10 * -10 = +1.0 MW (flow increases 1.0 MW)

   THESE ARE LINEAR SHIFT-FACTOR ESTIMATES, NOT AC POWER-FLOW RESULTS, and
   NOT a claim that 10 MW of headroom is actually available at that node.
   They exist purely to give Person 5 a comparable, consistent screening
   number for "how big is the side-effect relative to the relief".

=================================================================================
WHAT THIS SCRIPT DOES NOT CLAIM
=================================================================================
- These are PROPOSED CANDIDATE groups for screening and validation, not
  optimal groups, and not real-time operational groups.
- The 10 MW figures are linear estimates, not full AC power-flow results.
- Any "low/medium/high" trade-off language is deliberately avoided; only a
  numeric tradeoff_ratio is reported, left for the team to threshold.

=================================================================================
"""

import pandas as pd
import numpy as np

# ============================== CONFIG ==========================================

BINDING_LINES_PATH = "binding_lines.csv"
BASELINE_FLOWS_PATH = "baseline_hourly_flows.csv"
SHIFT_FACTOR_LONG_PATH = "shift_factor_matrix.csv"

OUTPUT_GROUPS_PATH = "proposed_groups.csv"
OUTPUT_SUMMARY_PATH = "group_method_comparison.csv"
OUTPUT_READABLE_MAP_PATH = "group_map_readable.csv"
OUTPUT_TRADEOFF_PATH = "multiline_tradeoff_analysis.csv"

# TEAM SIGN-OFF REQUIRED — see note above. Placeholder only, not a validated value.
TAU = 0.05

# Matches binding_definition = "loading_ge_99.9pct" used in your Step 1 output.
LOADING_THRESHOLD = 0.999

# Standard hypothetical curtailment used for the quantitative screening estimate.
# delta_P is negative because we are modelling a REDUCTION in output.
HYPOTHETICAL_REDUCTION_MW = 10.0
DELTA_P = -HYPOTHETICAL_REDUCTION_MW

# D06 fix: the single source of truth for Method A's output schema. Every
# dict appended to `rows` in method_a_signed_threshold_groups() must use
# exactly these keys. Defining it centrally means that when zero candidates
# are generated, we can still return a correctly-shaped (0-row) DataFrame
# instead of pd.DataFrame([]) — which has NO columns at all and breaks any
# downstream code that accesses e.g. groups["group_id"].
METHOD_A_COLUMNS = [
    "method",
    "group_id",
    "target_line",
    "node_id",
    "node_name",
    "shift_factor_signed",
    "abs_shift_factor",
    "membership_threshold",
    # D09 fix: machine-readable record of how this row was screened —
    # "directional" (signed SF checked against the line's known overload
    # direction) or "magnitude_only_ambiguous" (direction unknown/mixed,
    # fell back to abs(SF) >= tau only). Previously only recoverable by
    # parsing the membership_reason text.
    "screening_mode",
    "target_line_flow_change_10MW_MW",
    "target_line_relief_magnitude_10MW_MW",
    "multi_line_flag",
    "materially_affected_other_lines",
    "other_line_impacts_10MW_MW",
    "worst_case_material_other_line_impact_ratio",
    "worst_case_adverse_tradeoff_ratio",
    "has_adverse_tradeoff",
    "membership_reason",
]

# Same D06 reasoning, applied to Method B's detail table: without this,
# multiline_tradeoff_analysis.csv would have zero columns (not just zero
# rows) whenever Method A produces no candidates at all.
TRADEOFF_DETAIL_COLUMNS = [
    "node_id",
    "node_name",
    "target_line",
    "target_line_flow_change_10MW_MW",
    "target_line_relief_magnitude_10MW_MW",
    "other_line",
    "other_line_shift_factor_signed",
    "other_line_impact_10MW_MW",
    "other_line_overload_direction",
    "classification",
    "impact_to_relief_ratio",
    "impact_to_relief_ratio_note",
]


# ============================== LOAD DATA =======================================

def load_selected_binding_lines():
    df = pd.read_csv(BINDING_LINES_PATH)
    selected = df[df["selected"] == True].copy()
    return selected.sort_values("rank")


def determine_overload_directions(binding_line_ids):
    """
    For each binding line, look at baseline_hourly_flows.csv snapshots where
    loading (abs_flow_MW / rating_MW) >= LOADING_THRESHOLD, and check the sign
    of flow_MW at those snapshots.

    Returns dict: line_id -> "positive" | "negative" | "ambiguous"
    Also prints a short audit trail so this is checkable, same spirit as the
    audit-response docs already in your Step 1/2 folders.
    """
    flows = pd.read_csv(BASELINE_FLOWS_PATH)
    directions = {}

    print("\n--- Overload direction detection (for relief-direction screening) ---")
    for line_id in binding_line_ids:
        sub = flows[flows["line_id"] == line_id].copy()
        if sub.empty:
            print(f"[WARN] {line_id}: not found in {BASELINE_FLOWS_PATH} — "
                  f"falling back to magnitude-only screening.")
            directions[line_id] = "ambiguous"
            continue

        sub["loading_pct"] = sub["abs_flow_MW"] / sub["rating_MW"]
        near_binding = sub[sub["loading_pct"] >= LOADING_THRESHOLD]

        if near_binding.empty:
            print(f"[WARN] {line_id}: no snapshots >= {LOADING_THRESHOLD:.1%} loading found — "
                  f"falling back to magnitude-only screening.")
            directions[line_id] = "ambiguous"
            continue

        pos = int((near_binding["flow_MW"] > 0).sum())
        neg = int((near_binding["flow_MW"] < 0).sum())

        if pos == 0 and neg == 0:
            # near_binding is non-empty (checked above), but NOT ONE row had
            # a usable signed flow_MW (e.g. all NaN at these snapshots).
            # This is a DIFFERENT situation from "no positive snapshots
            # found" — without this branch, pos > 0 is False and execution
            # falls straight into the final `else` below, which silently
            # mislabels an all-NaN/insufficient-data line as "negative".
            print(f"[WARN] {line_id}: {len(near_binding)} snapshot(s) >= "
                  f"{LOADING_THRESHOLD:.1%} loading found, but NONE had a "
                  f"usable signed flow_MW value (likely all NaN) — "
                  f"insufficient data to determine overload direction. "
                  f"Falling back to magnitude-only screening. Flag this "
                  f"line for manual review.")
            directions[line_id] = "ambiguous"
        elif pos > 0 and neg > 0:
            print(f"[WARN] {line_id}: MIXED overload directions found "
                  f"({pos} positive, {neg} negative snapshots) — treating as "
                  f"ambiguous, falling back to magnitude-only screening. "
                  f"Flag this line for manual review.")
            directions[line_id] = "ambiguous"
        elif pos > 0:
            print(f"{line_id}: overloaded in POSITIVE (bus0->bus1) direction "
                  f"({pos} snapshots >= {LOADING_THRESHOLD:.1%} loading)")
            directions[line_id] = "positive"
        else:
            print(f"{line_id}: overloaded in NEGATIVE (bus1->bus0) direction "
                  f"({neg} snapshots >= {LOADING_THRESHOLD:.1%} loading)")
            directions[line_id] = "negative"

    print("--- End overload direction detection ---\n")
    return directions


def load_shift_factor_long():
    df = pd.read_csv(SHIFT_FACTOR_LONG_PATH)
    return df


# ============================== METHOD A =========================================

def method_a_signed_threshold_groups(sf_long: pd.DataFrame, binding_line_ids: list,
                                      directions: dict, tau: float):
    """
    For each binding line, form a group of nodes whose reduction is expected
    to RELIEVE that line by at least tau — using the true relief direction
    where known, falling back to magnitude-only where the direction was
    ambiguous.

    Also computes target_line_relief_10MW_MW here (Method A's own line, not
    the multi-line side-effects — those are added by the Method B enrichment
    step below).
    """
    rows = []

    for line_id in binding_line_ids:
        line_rows = sf_long[sf_long["monitored_line"] == line_id]
        direction = directions.get(line_id, "ambiguous")
        group_id = f"A_{line_id}"

        for r in line_rows.itertuples():
            signed = r.shift_factor_signed
            abs_val = r.shift_factor_abs

            if direction == "positive":
                passes = signed > 0 and abs_val >= tau
                reason_tail = "line overloaded bus0->bus1; node's cut lowers flow (relief)"
                screening_mode = "directional"
            elif direction == "negative":
                passes = signed < 0 and abs_val >= tau
                reason_tail = "line overloaded bus1->bus0; node's cut raises flow back toward rating (relief)"
                screening_mode = "directional"
            else:
                passes = abs_val >= tau
                reason_tail = "overload direction ambiguous/unavailable; screened on magnitude only"
                screening_mode = "magnitude_only_ambiguous"

            if not passes:
                continue

            # ΔF = SF x ΔP, with ΔP = -10 MW (a curtailment). This is the
            # LINEAR ESTIMATE of the signed flow change on the node's OWN
            # target line. It is NOT itself "the relief" — its sign depends
            # on the line's overload direction combined with the SF's sign,
            # so for a positive-direction line it is *always negative* even
            # on a row that correctly passed the relief-direction screen
            # just above (and always positive for a negative-direction
            # line). We keep both: the signed flow change, for anyone
            # tracing the arithmetic end to end, and an explicit,
            # always-positive relief MAGNITUDE — what "X MW of relief"
            # actually means here, now that direction has already been
            # screened for by `passes` above.
            target_line_flow_change_10mw = signed * DELTA_P
            target_line_relief_magnitude_10mw = abs(target_line_flow_change_10mw)

            reason = (
                f"shift_factor_signed={signed:.6f}, abs={abs_val:.6f} >= tau={tau} "
                f"({reason_tail}); estimated relief for a "
                f"{HYPOTHETICAL_REDUCTION_MW:.0f} MW reduction = "
                f"{target_line_relief_magnitude_10mw:.3f} MW (linear shift-factor "
                f"estimate; signed flow change = {target_line_flow_change_10mw:+.3f} MW)"
            )
            rows.append({
                "method": "A",
                "group_id": group_id,
                "target_line": line_id,
                "node_id": r.node_id,
                "node_name": r.node_name,
                "shift_factor_signed": signed,
                "abs_shift_factor": abs_val,
                "membership_threshold": tau,
                "screening_mode": screening_mode,
                # Signed change in the target line's OWN flow — can be
                # negative even for a correctly-screened relief row (see
                # comment above). The always-positive relief size anyone
                # downstream actually wants is the column right after it.
                "target_line_flow_change_10MW_MW": target_line_flow_change_10mw,
                "target_line_relief_magnitude_10MW_MW": target_line_relief_magnitude_10mw,
                # multi-line columns filled in by the Method B enrichment step:
                "multi_line_flag": False,
                "materially_affected_other_lines": "",
                "other_line_impacts_10MW_MW": "",
                # Largest other-line impact relative to this row's relief,
                # regardless of whether that other-line effect helps or
                # hurts — a magnitude comparison only, NOT a trade-off
                # indicator by itself (see the two columns below for that).
                "worst_case_material_other_line_impact_ratio": np.nan,
                # Only set when at least one materially-affected other line
                # is classified "worsens" against ITS OWN overload
                # direction — this is the genuine trade-off signal.
                "worst_case_adverse_tradeoff_ratio": np.nan,
                "has_adverse_tradeoff": False,
                "membership_reason": reason,
            })

    # D06 fix: pd.DataFrame([]) on zero rows has NO columns at all, which
    # breaks any downstream code expecting e.g. groups["group_id"] (a
    # KeyError, not a graceful "0 candidates" result). Zero candidates is a
    # legitimate analytical outcome, not an error — so when that happens,
    # explicitly return an empty DataFrame that still has every expected
    # column, using the single schema defined above. No placeholder rows
    # are manufactured; the analytical result (0 rows) is unchanged.
    if not rows:
        return pd.DataFrame(columns=METHOD_A_COLUMNS)
    return pd.DataFrame(rows)


# ============================== METHOD B (VALIDATION / TRADE-OFF LAYER) =========

def classify_other_line_impact(other_line_direction: str, other_line_impact_mw: float):
    """
    Classifies an estimated side-effect on another binding line as relief,
    worsening, or undetermined, based on THAT line's own detected overload
    direction (not the target line's direction).
    """
    if other_line_direction == "positive":
        return "relieves" if other_line_impact_mw < 0 else "worsens"
    elif other_line_direction == "negative":
        return "relieves" if other_line_impact_mw > 0 else "worsens"
    else:
        return "undetermined (ambiguous overload direction)"


def method_b_multiline_validation_layer(sf_long: pd.DataFrame, binding_line_ids: list,
                                         directions: dict, tau: float,
                                         method_a_groups: pd.DataFrame):
    """
    METHOD B — validation / trade-off layer, NOT a second group-generation
    method. Does not add rows to proposed_groups.csv. Instead:

      1. For every node already in a Method A candidate row, checks that
         node's shift factor against ALL selected binding lines.
      2. Any OTHER binding line where abs(shift_factor_signed) >= tau is a
         "materially affected other line" — flagged, never silently dropped
         or used to remove the node from its Method A group.
      3. Quantifies the estimated 10 MW side-effect on each such other line,
         classifies it (relieves / worsens / undetermined) against that
         line's own overload direction, and computes a worst-case
         tradeoff_ratio.

    Returns:
        enriched_groups: method_a_groups with multi-line columns filled in
        tradeoff_detail: long-format DataFrame, one row per
                          (node, target_line, other_line) — the full detail
                          behind the summarized strings in proposed_groups.csv
    """
    # index shift factors by node_id for fast per-node lookup across all lines
    sf_by_node = {
        node_id: grp.set_index("monitored_line")["shift_factor_signed"]
        for node_id, grp in sf_long[sf_long["monitored_line"].isin(binding_line_ids)].groupby("node_id")
    }

    enriched_groups = method_a_groups.copy()
    detail_rows = []

    for idx, row in enriched_groups.iterrows():
        node_id = row["node_id"]
        target_line = row["target_line"]
        target_relief = row["target_line_relief_magnitude_10MW_MW"]

        node_sfs = sf_by_node.get(node_id)
        if node_sfs is None:
            continue  # shouldn't happen, but handle missing node safely

        # every OTHER selected binding line this node materially affects
        other_lines = [
            line_id for line_id in binding_line_ids
            if line_id != target_line
            and line_id in node_sfs.index
            and abs(node_sfs[line_id]) >= tau
        ]

        if not other_lines:
            continue  # nothing to flag — row stays as Method A left it

        enriched_groups.at[idx, "multi_line_flag"] = True

        impact_strs = []
        worst_case_any_ratio = np.nan
        worst_case_adverse_ratio = np.nan
        has_adverse = False

        for other_line in other_lines:
            other_sf = node_sfs[other_line]
            other_impact = other_sf * DELTA_P  # linear 10 MW estimate on the OTHER line
            other_direction = directions.get(other_line, "ambiguous")
            classification = classify_other_line_impact(other_direction, other_impact)

            impact_strs.append(f"{other_line}: {other_impact:+.2f} MW ({classification})")

            # How big is this side-effect relative to the relief we're
            # getting on the target line? Handled safely for zero/near-zero
            # target relief (avoid divide-by-zero). Tracked TWO ways:
            #   - "any" ratio: every materially-affected other line,
            #     whatever its classification — a magnitude comparison only.
            #   - "adverse" ratio: restricted to other lines actually
            #     classified "worsens" here. This is the genuine trade-off
            #     signal — a node that only ever RELIEVES other lines has
            #     no trade-off, even though it can still produce a large
            #     "any" ratio (that was the bug: the old single
            #     tradeoff_ratio field mixed the two together).
            if target_relief is not None and abs(target_relief) > 1e-9:
                ratio = abs(other_impact) / abs(target_relief)
                if np.isnan(worst_case_any_ratio) or ratio > worst_case_any_ratio:
                    worst_case_any_ratio = ratio
                if classification == "worsens":
                    has_adverse = True
                    if np.isnan(worst_case_adverse_ratio) or ratio > worst_case_adverse_ratio:
                        worst_case_adverse_ratio = ratio

            detail_rows.append({
                "node_id": node_id,
                "node_name": row["node_name"],
                "target_line": target_line,
                "target_line_flow_change_10MW_MW": row["target_line_flow_change_10MW_MW"],
                "target_line_relief_magnitude_10MW_MW": target_relief,
                "other_line": other_line,
                "other_line_shift_factor_signed": other_sf,
                "other_line_impact_10MW_MW": other_impact,
                "other_line_overload_direction": other_direction,
                "classification": classification,
                "impact_to_relief_ratio": (
                    abs(other_impact) / abs(target_relief)
                    if abs(target_relief) > 1e-9 else np.nan
                ),
                "impact_to_relief_ratio_note": (
                    "" if abs(target_relief) > 1e-9
                    else "target-line relief ~0 MW; ratio undefined, review manually"
                ),
            })

        enriched_groups.at[idx, "materially_affected_other_lines"] = "; ".join(other_lines)
        enriched_groups.at[idx, "other_line_impacts_10MW_MW"] = "; ".join(impact_strs)
        enriched_groups.at[idx, "worst_case_material_other_line_impact_ratio"] = worst_case_any_ratio
        enriched_groups.at[idx, "worst_case_adverse_tradeoff_ratio"] = worst_case_adverse_ratio
        enriched_groups.at[idx, "has_adverse_tradeoff"] = has_adverse

        # extend the membership_reason with a pointer to the trade-off, so
        # the reason column alone still tells the full story
        adverse_note = (
            f"worst-case ADVERSE ratio {worst_case_adverse_ratio:.2f}x"
            if has_adverse else "no adverse (worsening) effect among them"
        )
        enriched_groups.at[idx, "membership_reason"] += (
            f"; MULTI-LINE FLAG: also materially affects "
            f"{len(other_lines)} other binding line(s) — {adverse_note}; see "
            f"materially_affected_other_lines / other_line_impacts_10MW_MW "
            f"columns; requires manual cross-line validation before acceptance."
        )

    if not detail_rows:
        tradeoff_detail = pd.DataFrame(columns=TRADEOFF_DETAIL_COLUMNS)
    else:
        tradeoff_detail = pd.DataFrame(detail_rows)
    return enriched_groups, tradeoff_detail


# ============================== SUMMARY ==========================================

def build_comparison_summary(enriched_groups: pd.DataFrame, sf_long: pd.DataFrame,
                              binding_line_ids: list, tau: float, directions: dict):
    """
    Method A row = the real candidate groups.
    Method B row = the validation layer's flag counts — explicitly NOT
    reported as "groups", per the requirement not to produce misleading
    statistics like "Method B produced N groups".

    Also surfaces, in the PERSISTED summary CSV (not just the console
    output), two data-quality states that would otherwise be
    indistinguishable from "everything is fine": a selected binding line
    that ended up with zero Method A candidates (it simply doesn't appear
    anywhere in proposed_groups.csv), and a selected line whose overload
    direction couldn't be determined (ambiguous / insufficient data).
    """
    summary_rows = []
    all_node_ids = set(sf_long["node_id"].unique())

    # Method A row (the actual groups)
    a = enriched_groups[enriched_groups["method"] == "A"]
    n_groups = a["group_id"].nunique()
    group_sizes = a.groupby("group_id")["node_id"].nunique()
    mean_group_size = round(group_sizes.mean(), 2) if len(group_sizes) else 0
    node_group_counts = a.groupby("node_id")["group_id"].nunique()
    overlap_count = int((node_group_counts > 1).sum())
    multi_line_node_count_a = a.loc[a["multi_line_flag"], "node_id"].nunique()

    sub = sf_long[sf_long["monitored_line"].isin(binding_line_ids)]
    max_abs_by_node = sub.groupby("node_id")["shift_factor_abs"].max()
    included_nodes = set(a["node_id"])
    excluded_nodes = all_node_ids - included_nodes
    low_influence = int(sum(
        1 for n in excluded_nodes
        if n in max_abs_by_node.index and max_abs_by_node[n] < tau
    ))

    # Selected binding lines with NO Method A candidates — otherwise these
    # would simply be absent from proposed_groups.csv, which looks
    # identical to "the line was accidentally dropped".
    lines_with_groups = set(a["target_line"].unique())
    zero_candidate_lines = [l for l in binding_line_ids if l not in lines_with_groups]

    ambiguous_direction_lines = [
        l for l in binding_line_ids if directions.get(l) == "ambiguous"
    ]

    summary_rows.append({
        "method": "A",
        "number_of_groups": n_groups,
        "mean_group_size": mean_group_size,
        "overlap_count": overlap_count,
        "multi_line_node_count": multi_line_node_count_a,
        "low_influence_nodes_excluded": low_influence,
        "selected_lines_with_zero_candidates": len(zero_candidate_lines),
        "selected_lines_with_zero_candidates_ids": "; ".join(zero_candidate_lines),
        "selected_lines_with_ambiguous_direction": len(ambiguous_direction_lines),
        "selected_lines_with_ambiguous_direction_ids": "; ".join(ambiguous_direction_lines),
        "notes": "Method A = actual candidate groups, one per binding line.",
    })

    # Method B row — deliberately zero groups; it is a validation layer on
    # top of Method A, not a second group-generation method.
    summary_rows.append({
        "method": "B",
        "number_of_groups": 0,
        "mean_group_size": np.nan,
        "overlap_count": np.nan,
        "multi_line_node_count": multi_line_node_count_a,
        "low_influence_nodes_excluded": np.nan,
        "selected_lines_with_zero_candidates": np.nan,
        "selected_lines_with_zero_candidates_ids": "",
        "selected_lines_with_ambiguous_direction": np.nan,
        "selected_lines_with_ambiguous_direction_ids": "",
        "notes": (
            "Method B does NOT produce groups. It is a validation/trade-off "
            "layer that flags and quantifies multi-line side-effects on "
            "Method A's existing candidate rows. multi_line_node_count here "
            "is the number of distinct nodes flagged for manual cross-line "
            "validation, not a group count."
        ),
    })

    return pd.DataFrame(summary_rows)


# ============================== MAIN =============================================

def main():
    binding_lines_df = load_selected_binding_lines()
    binding_line_ids = binding_lines_df["line_id"].tolist()
    print(f"Selected binding lines ({len(binding_line_ids)}): {binding_line_ids}")
    print(f"Using tau (material threshold) = {TAU}  <-- TEAM SIGN-OFF PLACEHOLDER, replace with agreed value")
    print(f"Hypothetical reduction for quantitative screening = {HYPOTHETICAL_REDUCTION_MW:.0f} MW "
          f"(linear shift-factor estimate, not an AC power-flow result)")

    directions = determine_overload_directions(binding_line_ids)

    sf_long = load_shift_factor_long()
    print(f"Loaded shift factor matrix (long): {len(sf_long)} rows, "
          f"{sf_long['node_id'].nunique()} nodes x {sf_long['monitored_line'].nunique()} lines")

    # --- Method A: build the actual candidate groups ---
    method_a_groups = method_a_signed_threshold_groups(sf_long, binding_line_ids, directions, TAU)
    print(f"\nMethod A: built {method_a_groups['group_id'].nunique()} groups, "
          f"{len(method_a_groups)} node-membership rows.")

    # --- Method B: enrich those rows with multi-line trade-off info (no new groups) ---
    enriched_groups, tradeoff_detail = method_b_multiline_validation_layer(
        sf_long, binding_line_ids, directions, TAU, method_a_groups
    )
    n_flagged = int(enriched_groups["multi_line_flag"].sum())
    print(f"Method B: flagged {n_flagged} of {len(enriched_groups)} Method A rows "
          f"({enriched_groups.loc[enriched_groups['multi_line_flag'], 'node_id'].nunique()} unique nodes) "
          f"as requiring manual cross-line validation. No new groups created.")

    # --- Save proposed_groups.csv (Method A rows only, now enriched) ---
    enriched_groups.to_csv(OUTPUT_GROUPS_PATH, index=False)
    print(f"\nSaved: {OUTPUT_GROUPS_PATH} ({len(enriched_groups)} rows, all method='A')")

    # --- Save multiline_tradeoff_analysis.csv (full detail behind the flags) ---
    tradeoff_detail.to_csv(OUTPUT_TRADEOFF_PATH, index=False)
    print(f"Saved: {OUTPUT_TRADEOFF_PATH} ({len(tradeoff_detail)} rows — one per "
          f"node x target_line x other_line trade-off)")

    # --- Comparison summary ---
    summary = build_comparison_summary(enriched_groups, sf_long, binding_line_ids, TAU, directions)
    summary.to_csv(OUTPUT_SUMMARY_PATH, index=False)
    print(f"Saved: {OUTPUT_SUMMARY_PATH}")
    print(summary.to_string(index=False))

    # --- Plain-English group map for non-technical judges ---
    readable_rows = []
    for line_id in binding_line_ids:
        line_nodes = enriched_groups[enriched_groups["target_line"] == line_id]
        entries = []
        for r in line_nodes.itertuples():
            if r.multi_line_flag:
                tradeoff_note = (
                    f"ADVERSE tradeoff, worst-case {r.worst_case_adverse_tradeoff_ratio:.2f}x"
                    if r.has_adverse_tradeoff else "no adverse effect among them"
                )
                entries.append(
                    f"{r.node_name} [multi-line, {tradeoff_note}] — {HYPOTHETICAL_REDUCTION_MW:.0f} MW "
                    f"reduction estimated to give {r.target_line_relief_magnitude_10MW_MW:.2f} MW relief "
                    f"on this line, but also affects: {r.other_line_impacts_10MW_MW}"
                )
            else:
                entries.append(
                    f"{r.node_name} — {r.target_line_relief_magnitude_10MW_MW:.2f} MW estimated relief, "
                    f"no other binding line materially affected"
                )
        readable_rows.append({
            "binding_line": line_id,
            "overload_direction": directions.get(line_id, "ambiguous"),
            "proposed_turn_down_group": " | ".join(entries) if entries else "(none above threshold)",
        })
    readable_df = pd.DataFrame(readable_rows)
    readable_df.to_csv(OUTPUT_READABLE_MAP_PATH, index=False)
    print(f"Saved: {OUTPUT_READABLE_MAP_PATH}")


if __name__ == "__main__":
    main()
