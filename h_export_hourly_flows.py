"""(h) Export hourly_flows.csv - the shared file everyone else is blocked on.

    python examples/h_export_hourly_flows.py [SCENARIO] [SCOPE]

Solves and flows the network exactly as a_dc_power_flow.py does (solve ->
freeze_dispatch -> lpf), then writes one row per line per snapshot:

    hour, line_id, flow_MW, limit_MW

``flow_MW`` is signed (n.lines_t.p0 as PyPSA returns it - positive means the
flow is from bus0 to bus1); ``limit_MW`` is the line's static s_nom rating
(MVA in the source data, treated as MW under the DC approximation, which is
standard for this kind of study since reactive power is dropped entirely).

Writes hourly_flows.csv into the participant-kit root (next to gridkit.py),
so it's easy to find and share.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gridkit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(scenario="WP2033", scope="north-west"):
    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    flows = n.lines_t.p0                       # hours x lines, signed MW
    limits = n.lines["s_nom"]                   # per line, MW

    long_form = (
        flows.stack()
        .rename("flow_MW")
        .reset_index()
        .rename(columns={"snapshot": "hour", "level_1": "line_id", "Line": "line_id"})
    )
    # stack()'s column-level name depends on the frame; normalise explicitly.
    long_form.columns = ["hour", "line_id", "flow_MW"]
    long_form["limit_MW"] = long_form["line_id"].map(limits).astype(float)
    long_form["flow_MW"] = long_form["flow_MW"].astype(float)
    long_form = long_form.sort_values(["hour", "line_id"]).reset_index(drop=True)

    out_path = os.path.join(ROOT, "hourly_flows.csv")
    long_form.to_csv(out_path, index=False)
    print(f"{len(long_form):,} rows ({len(n.lines)} lines x {len(n.snapshots)} "
          f"hours) -> {out_path}")
    print(long_form.head().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
