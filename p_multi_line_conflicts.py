"""(p) Step 3A - Multi-line conflict analysis - Harshitha

Goal: find the renewable nodes whose changes influence more than one
monitored (binding) line, and classify each as a multi-line worsening
node, a multi-line relief node, a trade-off node, or low-influence -
per the team's Step 3A spec.

INPUTS (must already exist - Steps 0-2's hand-offs):
  binding_lines.csv           - from Person 1 (3.2-p1-binding-lines)
  shift_factor_matrix.csv     - from Person 2 (3.2-P2-Shift-Factor-Matrix)
  baseline_hourly_flows.csv   - from Person 1, needed here for one extra
                                 thing Person 1's own file doesn't carry:
                                 which flow DIRECTION each monitored line
                                 binds in (signed flow, not just |flow|).

WHY THE DIRECTION CHECK MATTERS (read this before trusting the output):
A shift factor's SIGN says whether more generation at a node increases or
decreases flow on a line in PyPSA's bus0->bus1 direction. That is not the
same as "increases or decreases the line's overload." Overload depends on
which direction the line is ACTUALLY loaded in during its binding hours -
a node whose shift factor pushes flow the OPPOSITE way from the binding
direction is a genuine relief candidate, not a "less bad" worsening one,
no matter how large its |shift factor| is. This is the identical trap
already flagged in Track A (Q5's unsigned "43 MW" claim) and in Alex's Q6
(ranking by abs_shift_factor alone): magnitude tells you how strongly a
node is coupled to a line, sign tells you which way. Both are needed.
So before classifying anything, this script checks the ACTUAL signed flow
on every monitored line during its own binding hours (loading >= 99.9%,
the same definition binding_lines.csv itself uses) and refuses to
continue if a line's binding-hour flow isn't consistently one direction -
that would mean "worsening vs relieving" isn't even well-defined for it
without a more careful per-hour treatment.

MATERIALITY THRESHOLD: per-line top 10% of |shift factor|, not a single
fixed threshold across all six lines - the brief itself flags that
absolute shift-factor scale can differ by line (topology/impedance
dependent), and this matrix bears that out (line-by-line mean |SF| here
ranges from 0.0046 to 0.060, over 10x apart) - a fixed cutoff would just
be measuring which lines happen to have larger shift factors, not which
nodes matter for each one.

WEIGHTING CAVEAT: binding_lines.csv's total_overload_MWh and
max_overload_MW columns are ~0 for every line (down to solver floating-
point noise, 1e-10 to 1e-13 MW) - not a data error, this is a structural
property of a network with no unserved load: n.optimize()/n.lpf() cannot
produce |flow| > rating, so "MW over the limit" never has anything to
read (the same trap flagged in this project's earlier Q2/Q4 work, where
hourly_flows.csv's flow/limit columns had the same property). So the
per-line weight used below for the influence score is overload_hours
(how often the line actually binds), the only one of the three ranking
metrics in binding_lines.csv that is actually nonzero and meaningful here
- stated explicitly since Step 3A's spec allows weighting by "total
overload or number of overload hours," and only one of those two options
is usable with this data.

Run from the root of the repo, with binding_lines.csv,
shift_factor_matrix.csv and baseline_hourly_flows.csv all present
(fetch/checkout the 3.2-p1-binding-lines and 3.2-P2-Shift-Factor-Matrix
branches, or copy the three files locally), via:
    python p_multi_line_conflicts.py
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MATERIALITY_QUANTILE = 0.90  # top 10% of |SF| within each monitored line

# ---------------------------------------------------------------------
# Load the three prerequisite files
# ---------------------------------------------------------------------
binding = pd.read_csv("binding_lines.csv")
matrix = pd.read_csv("shift_factor_matrix.csv")
flows = pd.read_csv("baseline_hourly_flows.csv")

lines = binding.loc[binding["selected"] == True, "line_id"].tolist()
ratings = dict(zip(binding.line_id, binding.rating_MW))
print(f"Monitored lines ({len(lines)}): {lines}")

# ---------------------------------------------------------------------
# STEP A: determine each monitored line's binding-hour flow direction
# ---------------------------------------------------------------------
binding_sign = {}
for line in lines:
    sub = flows[flows.line_id == line].copy()
    sub["loading"] = sub["abs_flow_MW"] / ratings[line]
    bind_hours = sub[sub["loading"] >= 0.999]
    if len(bind_hours) == 0:
        raise RuntimeError(f"{line}: 0 binding hours found in baseline_hourly_flows.csv "
                            f"- inconsistent with binding_lines.csv, stop and check.")
    signs = np.sign(bind_hours["flow_MW"])
    if signs.nunique() != 1:
        raise RuntimeError(
            f"{line}: binding-hour flow is NOT one-directional "
            f"({(signs > 0).sum()} positive, {(signs < 0).sum()} negative) - "
            f"'worsening vs relieving' is not well-defined for this line without "
            f"a per-hour treatment. Stop and handle this line separately before "
            f"trusting its classification below."
        )
    binding_sign[line] = int(signs.iloc[0])  # +1 or -1
    print(f"  {line}: {len(bind_hours)} binding hours, all flow sign "
          f"{'positive' if binding_sign[line] > 0 else 'negative'} "
          f"(bus0->bus1 convention)")

# ---------------------------------------------------------------------
# STEP B: materiality + worsen/relieve per (node, line)
# ---------------------------------------------------------------------
mat = matrix.copy()
mat["material_threshold"] = mat.groupby("monitored_line")["shift_factor_abs"].transform(
    lambda s: s.quantile(MATERIALITY_QUANTILE)
)
mat["material"] = mat["shift_factor_abs"] >= mat["material_threshold"]
mat["binding_sign"] = mat["monitored_line"].map(binding_sign)
# worsening = shift factor pushes flow the SAME way the line already binds;
# relieving = OPPOSITE way. Only meaningful where material; store as string.
mat["effect"] = np.where(
    ~mat["material"], "not_material",
    np.where(np.sign(mat["shift_factor_signed"]) == mat["binding_sign"], "worsens", "relieves")
)

n_material_pairs = int(mat["material"].sum())
print(f"\nMaterial (node, line) pairs: {n_material_pairs} of {len(mat)} "
      f"({n_material_pairs/len(mat)*100:.1f}%) at the {MATERIALITY_QUANTILE:.0%} "
      f"per-line quantile threshold")

# ---------------------------------------------------------------------
# STEP C: per-node classification
# ---------------------------------------------------------------------
overload_hours = dict(zip(binding.line_id, binding.overload_hours))
total_weight = sum(overload_hours[l] for l in lines)

records = []
for node_id, g in mat.groupby("node_id"):
    node_name = g["node_name"].iloc[0]
    g_mat = g[g["material"]]
    worsened = sorted(g_mat.loc[g_mat.effect == "worsens", "monitored_line"].tolist())
    relieved = sorted(g_mat.loc[g_mat.effect == "relieves", "monitored_line"].tolist())
    material_line_count = len(g_mat)
    tradeoff = len(worsened) >= 1 and len(relieved) >= 1

    if material_line_count == 0:
        classification = "low-influence node"
    elif tradeoff:
        classification = "trade-off node"
    elif len(worsened) >= 2:
        classification = "multi-line worsening node"
    elif len(relieved) >= 2:
        classification = "multi-line relief node"
    elif len(worsened) == 1:
        classification = "single-line worsening node"
    else:
        classification = "single-line relief node"

    # weighted influence score: sum over ALL 6 lines (not just material ones -
    # a node can be a large but sub-threshold contributor on several lines
    # and that's worth surfacing in the score even if it misses the material
    # cutoff on any single one), weighted by how often each line binds.
    score = sum(
        (overload_hours[row.monitored_line] / total_weight) * row.shift_factor_abs
        for row in g.itertuples()
    )

    records.append({
        "node_id": node_id,
        "node_name": node_name,
        "material_line_count": material_line_count,
        "lines_worsened": ";".join(worsened),
        "lines_relieved": ";".join(relieved),
        "tradeoff_flag": tradeoff,
        "weighted_influence_score": round(score, 6),
        "classification": classification,
    })

conflicts = pd.DataFrame(records).sort_values(
    ["material_line_count", "weighted_influence_score"], ascending=[False, False]
).reset_index(drop=True)

conflicts.to_csv("multi_line_conflicts.csv", index=False)
print(f"\nWrote multi_line_conflicts.csv ({len(conflicts)} nodes)")
print("\nClassification counts:")
print(conflicts["classification"].value_counts().to_string())

print("\nTop 15 by weighted influence score:")
print(conflicts.head(15).to_string(index=False))

trade = conflicts[conflicts.tradeoff_flag]
print(f"\n{len(trade)} genuine trade-off nodes (material AND opposite-effect "
      f"on at least two DIFFERENT monitored lines):")
if len(trade):
    print(trade[["node_id", "node_name", "lines_worsened", "lines_relieved"]].to_string(index=False))
else:
    print("  none - every node with material influence on >=2 lines pushes the "
          "same direction (worsens or relieves) on all of them, in this dataset.")

# ---------------------------------------------------------------------
# STEP D: quality gate - sanity checks before trusting the figures
# ---------------------------------------------------------------------
print("\n--- quality gate ---")
dup_nodes = matrix["node_id"].duplicated().any()
print(f"duplicate node_id rows within a single line (should be False): {matrix.groupby(['node_id','monitored_line']).size().gt(1).any()}")
assert conflicts["node_id"].is_unique, "duplicate node_id in output - stop"
print(f"node_id unique in output: True ({len(conflicts)} nodes)")
print(f"every monitored line's binding hours are single-direction: True (checked above, "
      f"script would have raised otherwise)")
row_sum_check = mat.groupby("node_id").size()
assert (row_sum_check == len(lines)).all(), "not every node has a row for every line - stop"
print(f"every node has exactly {len(lines)} rows (one per monitored line): True")

# ---------------------------------------------------------------------
# FIGURE 1: signed shift-factor heatmap, material nodes only
# ---------------------------------------------------------------------
# Palette: documented diverging pair (blue <-> red, neutral gray midpoint),
# from this project's dataviz reference palette - not picked ad hoc.
BLUE, GRAY, RED = "#2a78d6", "#f0efec", "#e34948"
cmap = matplotlib.colors.LinearSegmentedColormap.from_list("diverging_blue_red", [BLUE, GRAY, RED])

heat_nodes = conflicts[conflicts.material_line_count > 0].sort_values(
    "weighted_influence_score", ascending=False
)
# cap the heatmap to a readable number of rows; the full table is in the CSV
TOP_N_HEATMAP = 40
heat_ids = heat_nodes.head(TOP_N_HEATMAP)["node_id"].tolist()
pivot = mat[mat.node_id.isin(heat_ids)].pivot(
    index="node_id", columns="monitored_line", values="shift_factor_signed"
).reindex(heat_ids)
names = mat.drop_duplicates("node_id").set_index("node_id")["node_name"]
pivot.index = [f"{names[i]} ({i})" for i in pivot.index]
pivot = pivot[lines]  # column order = binding_lines.csv rank order

vmax = float(np.abs(pivot.values).max())
fig, ax = plt.subplots(figsize=(8, max(6, 0.28 * len(pivot))))
im = ax.imshow(pivot.values, cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto")
ax.set_xticks(range(len(lines)))
ax.set_xticklabels([f"{l}\n(binds {'+' if binding_sign[l]>0 else '-'})" for l in lines],
                    rotation=30, ha="right", fontsize=8)
ax.set_yticks(range(len(pivot)))
ax.set_yticklabels(pivot.index, fontsize=7)
cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
cbar.set_label("signed shift factor\n(red = same sign as this line's binding-hour\n"
               "flow, i.e. worsens it; blue = opposite sign, relieves it)", fontsize=7)
ax.set_title(f"Signed shift factors, top {len(pivot)} nodes by weighted influence "
             f"score\nWP2033 all-island, {len(lines)} monitored lines "
             f"(material threshold: top {(1-MATERIALITY_QUANTILE)*100:.0f}% |SF| per line)",
             fontsize=9)
plt.tight_layout()
os.makedirs("figures", exist_ok=True)
fig.savefig("p_multi_line_conflicts_heatmap_WP2033_all-island.png", dpi=150)
plt.close(fig)
print("\nWrote p_multi_line_conflicts_heatmap_WP2033_all-island.png")

# ---------------------------------------------------------------------
# FIGURE 2: ranked bar chart, top multi-line-influence nodes
# ---------------------------------------------------------------------
top20 = conflicts[conflicts.material_line_count >= 1].sort_values(
    "weighted_influence_score", ascending=False
).head(20)
colors = top20["classification"].map({
    "multi-line worsening node": RED,
    "multi-line relief node": BLUE,
    "trade-off node": "#8a5a00",       # distinct from both poles - not decorative
    "single-line worsening node": "#f3a9a8",
    "single-line relief node": "#a9c8ef",
})
fig2, ax2 = plt.subplots(figsize=(7, 6))
labels = [f"{r.node_name} ({r.material_line_count} lines)" for r in top20.itertuples()]
ax2.barh(range(len(top20)), top20["weighted_influence_score"], color=colors)
ax2.set_yticks(range(len(top20)))
ax2.set_yticklabels(labels, fontsize=8)
ax2.invert_yaxis()
ax2.set_xlabel("weighted influence score (overload-hours-weighted mean |SF|)")
ax2.set_title("Top 20 nodes by multi-line influence\nWP2033 all-island", fontsize=10)
handles = [matplotlib.patches.Patch(color=c, label=l) for l, c in {
    "multi-line worsening": RED, "multi-line relief": BLUE, "trade-off": "#8a5a00",
    "single-line worsening": "#f3a9a8", "single-line relief": "#a9c8ef",
}.items()]
ax2.legend(handles=handles, fontsize=7, loc="lower right")
plt.tight_layout()
fig2.savefig("p_multi_line_conflicts_top20_WP2033_all-island.png", dpi=150)
plt.close(fig2)
print("Wrote p_multi_line_conflicts_top20_WP2033_all-island.png")

print("\nDone. Language note for the deck: nodes are described as having "
      "'high modelled sensitivity' or 'strong influence' on a line, never as "
      "'responsible' or 'bad' - this is a screening classification, not a "
      "judgment.")
