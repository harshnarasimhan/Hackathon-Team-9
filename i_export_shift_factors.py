"""(i) Export shift_factors.csv - Q5, and the shared file Harshitha and
Kanyisola need for their own target lines.

    python examples/i_export_shift_factors.py [SCENARIO] [SCOPE] LINE [LINE ...]

For each monitored circuit given on the command line, computes the
load-weighted shift factor per generator (wind farm) - the same calculation
f_shift_factors.py prints - and writes one CSV with:

    generator, bus, carrier, p_nom, shift_factor_<line1>, shift_factor_<line2>, ...

``bus`` is each generator's own bus, which is its nearest substation (that is
how each generator was wired into the network in the source data - no extra
mapping step needed, per the task brief). The load-weighted reference is used
throughout (spread the balancing MW over every load in proportion to size -
the "rest of the system absorbs the difference" convention, and the one a
system operator actually means). f_shift_factors.py's own printout is the
place to see the uniform/single-bus comparison as a robustness check; it is
not repeated in this CSV.

Rows are restricted to carrier == "wind" (or "solar", where present) - this
is a shift factor *per wind farm*, and the north-west network's generator
list is not only wind farms. Filtered out, and not in this CSV:

  * "load shedding" - the VOLL modelling device at every load bus, not
    real plant (same as f_shift_factors.py drops).
  * "boundary ..." - equivalencing injections that stand in for the rest
    of the island at the north-west scope's 15-node boundary. There are
    10 of these in north-west and their names look like line names
    ("boundary Corderry - ARIGNA_T 1"), which makes them easy to mistake
    for real generators if this filter is removed - they are a modelling
    artifact of the region cut, not a wind farm or any other plant.
  * "hydro" and "unknown" (mostly conventional thermal) - real plant, but
    not wind, so out of scope for a Q5 "per wind farm" answer.

Pass --all-generators to keep every non-load-shedding row (with its
carrier column) if a later question needs the full generator set, e.g. to
reason about the boundary injections themselves.

Writes shift_factors.csv into the participant-kit root.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import flowmath
import gridkit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Carriers that actually are "a wind farm" in this kit's generator data.
#: Everything else in a non-load-shedding row (boundary equivalencing
#: injections, hydro, unknown/thermal) is real network content but is not
#: a wind farm and does not belong in a Q5 answer.
WIND_CARRIERS = ("wind", "solar")


def main(scenario="WP2033", scope="north-west", *args):
    all_generators = "--all-generators" in args
    lines = [a for a in args if a != "--all-generators"]
    if not lines:
        raise SystemExit(
            "usage: i_export_shift_factors.py SCENARIO SCOPE LINE [LINE ...] "
            "[--all-generators]")

    gridkit.quiet()
    n = gridkit.load(scenario, scope)
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)

    frame = flowmath.branches(n)
    not_shed = n.generators["carrier"] != "load shedding"
    if all_generators:
        real = n.generators.index[not_shed]
    else:
        real = n.generators.index[not_shed & n.generators["carrier"].isin(WIND_CARRIERS)]
        dropped = n.generators.index[not_shed & ~n.generators["carrier"].isin(WIND_CARRIERS)]
        if len(dropped):
            counts = n.generators.loc[dropped, "carrier"].value_counts()
            print(f"excluded {len(dropped)} non-wind generator(s) from the "
                  f"per-wind-farm export ({counts.to_dict()}); "
                  f"rerun with --all-generators to keep them")

    table = n.generators.loc[real, ["bus", "carrier", "p_nom"]].copy()
    table.index.name = "generator"

    for line in lines:
        factors = flowmath.shift_factors(n, line, reference="load",
                                          branch_frame=frame).reindex(real)
        table[f"shift_factor_{line}"] = factors["shift_factor"]

    table = table.reset_index()
    out_path = os.path.join(ROOT, "shift_factors.csv")
    table.to_csv(out_path, index=False)
    print(f"{len(table)} generators x {len(lines)} monitored line(s) -> {out_path}")
    print(table.head(10).round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
