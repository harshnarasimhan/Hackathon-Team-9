"""
l_battery_validation.py — Q2 validation (closes F-09, Track A audit)

The Q2 siting/sizing recommendation in `harshitha-q2-q4-summary.md`
(Drumkeen alone: 42.9 MW / ~101 MWh episodic, or 346.5 MWh conservative;
Drumkeen+Binbane: 48.4 MW / 232.6 MWh episodic) was hand-derived by
reading worst-hour and worst-episode values off
`k_dispatch_down_hourly_WP2033_north-west.csv`. No run actually inserted
a battery of that size at that bus and re-solved to confirm it removes
the constraint-based curtailment it's sized against — the summary's own
"Validation gap" note flags this explicitly. This script does exactly
that, using `gridkit.add_battery()`, and the real result is materially
different from what the hand-derived sizing implied — see RESULTS below,
captured from an actual run of this script.

Network: WP2033, north-west, STATIC 210 MVA rating on 5041-17010-2 —
matches the sizing basis the summary itself specifies (present the
static case as the sizing basis until a DLR-adjusted re-run is agreed;
see k_battery_siting_sizing_DLR-PATCHED.py for that separate case, now
also re-run — 507.8 MWh constraint-based at 213 MVA, vs 588.6 at 210).

Battery sizing is read directly from this repo's own committed
`k_dispatch_down_hourly_WP2033_north-west.csv` — nothing invented or
copied from the summary's prose. Four scenarios, two sites x two
sizing conventions:

  A. Drumkeen alone, EPISODIC sizing     — 42.9 MW / own largest
     contiguous episode (~100.8 MWh, ~2.35 h)
  B. Drumkeen alone, CONSERVATIVE sizing — 42.9 MW / own full-week
     cumulative curtailment (346.5 MWh, ~8.08 h)
  C. Drumkeen + Binbane, EPISODIC sizing — each site sized to its own
     worst hour / own largest episode independently
  D. Drumkeen + Binbane, CONSERVATIVE sizing — each site sized to its
     own worst hour / own full-week total independently

TWO WAYS OF COMPUTING "constraint-based dispatch-down remaining" are
reported for every scenario, and they can disagree once batteries are
in the network (they never disagree without batteries — see RESULTS):

  Method 1 (matches k_battery_siting_sizing.py exactly): for each hour,
  compute (real-ratings dispatch-down) - (ratings-lifted dispatch-down),
  clip that HOURLY difference at zero, then sum over the week.

  Method 2: sum each run's dispatch-down over the whole week first,
  THEN subtract, clipping once.

  These are equal whenever ratings-lifted dispatch-down never exceeds
  real-ratings dispatch-down in any single hour — true for every
  generator-only case in this project. With storage present, that can
  fail: a battery can behave differently in the "no line limit"
  counterfactual than in the real network (e.g. charging more eagerly
  early because there's more free wind to arb, leaving it timed
  differently for a later hour), so in a handful of hours the
  ratings-lifted run can show MORE dispatch-down than the real-ratings
  run. Method 1 (per-hour clip) then floors those hours to zero and
  loses that offsetting information, which inflates its week total
  relative to Method 2. Report both rather than picking one silently.

RESULTS (from an actual run of this script, 2026-09-11, real HiGHS
solves, WP2033 north-west, static 210 MVA):

    Baseline (no battery):                       588.6 MWh constraint-based
    A. Drumkeen only, episodic (100.8 MWh):      557.6 MWh remaining ( 5.3% relieved)
    B. Drumkeen only, conservative (346.5 MWh):  466.2 MWh remaining (20.8% relieved)
    C. Drumkeen+Binbane, episodic:      Method 1: 619.8 MWh (-5.3%) | Method 2: 546.3 MWh (7.2%)
    D. Drumkeen+Binbane, conservative:           399.3 MWh remaining (32.2% relieved)

HEADLINE FINDING: the hand-derived sizing recommendation does NOT
deliver anything close to the 58.9% (Drumkeen alone) / 92.5%
(Drumkeen+Binbane) coverage the summary's worst-hour/worst-episode
reading implied. Even the larger "conservative" sizing only reaches
20.8% / 32.1% real relief once the battery's own charge/discharge
behaviour is allowed to interact with the rest of the network's
dispatch. The episodic sizing the summary recommends leading with in
the deck (the smaller, "realistic, buildable" number) performs worse
still (5.3%, and possibly negative depending on which method you read,
in the two-site case). A battery sized only to its own single worst
episode has no capacity left for the OTHER episodes in the week (there
are several separate congestion episodes per site — see
k_battery_siting_sizing.py's own per-generator, per-hour CSV), and
recharging after one episode can itself interact with the network in
hours the original hand-derived method never looked at.

Practical recommendation: before this goes in front of a panel as a
sizing recommendation, either (a) present it explicitly as a screening
estimate with this validation's real relief numbers alongside it, not
instead of it, or (b) re-run this script with a larger capacity
(hours) at the same power rating and report the capacity actually
needed to hit a target relief percentage — a much more defensible
"how big does it need to be" answer than reading off one episode.

Run:
    python l_battery_validation.py
Requires the participant-kit (gridkit.py) and this repo's own
k_dispatch_down_hourly_WP2033_north-west.csv (already committed).
"""
import sys
sys.path.insert(0, "grid_TF_Wind/participant-kit")
import gridkit
import pandas as pd
import numpy as np

gridkit.quiet()

LINE = "5041-17010-2"
DISPATCH_CSV = "k_dispatch_down_hourly_WP2033_north-west.csv"


def dispatch_down_matrix(network):
    """Per-generator, per-hour offered-minus-taken, same as
    k_battery_siting_sizing.py — duplicated (not imported) so this script
    runs standalone."""
    avail = network.generators_t.p_max_pu
    cols = [c for c in avail.columns if c in network.generators_t.p]
    offered = avail[cols] * network.generators.loc[cols, "p_nom"]
    taken = network.generators_t.p[cols].clip(lower=0.0)
    return (offered - taken).clip(lower=0.0)


def site_sizing_from_csv(gen_name):
    """Own worst hour (MW), own largest contiguous episode (MWh, hours),
    and own full-week total (MWh) for one generator — read from this
    repo's real committed output, nothing invented."""
    df = pd.read_csv(DISPATCH_CSV, parse_dates=["hour"])
    s = df[df.generator == gen_name].set_index("hour")["constraint_based_MW"]
    p_nom = float(s.max())
    week_total = float(s.sum())
    nz = s[s > 0.01].sort_index()
    if len(nz) == 0:
        return p_nom, 0.0, 0, week_total
    groups, cur = [], [nz.index[0]]
    for h in nz.index[1:]:
        if (h - cur[-1]).total_seconds() == 3600:
            cur.append(h)
        else:
            groups.append(cur)
            cur = [h]
    groups.append(cur)
    episodes = [(g, float(s[g].sum()), len(g)) for g in groups]
    episodes.sort(key=lambda x: -x[1])
    _, mwh, hrs = episodes[0]
    return p_nom, mwh, hrs, week_total


def run_scenario(name, batteries):
    """batteries: list of (bus, p_nom_MW, hours) tuples; [] for baseline.
    Returns (method1_total, method2_total) constraint-based dispatch-down
    for the whole network, with the same batteries present in BOTH the
    real-rating and ratings-lifted runs."""
    n = gridkit.load("WP2033", "north-west")
    for bus, p_nom, hours in batteries:
        gridkit.add_battery(n, bus=bus, p_nom=round(p_nom, 1), hours=round(hours, 2))
    gridkit.solve(n)
    gridkit.freeze_dispatch(n)
    n.lpf(n.snapshots)
    lost = dispatch_down_matrix(n)

    m = gridkit.load("WP2033", "north-west")
    m.lines["s_nom"] = m.lines["s_nom"] * 1000
    for bus, p_nom, hours in batteries:
        gridkit.add_battery(m, bus=bus, p_nom=round(p_nom, 1), hours=round(hours, 2))
    gridkit.solve(m)
    gridkit.freeze_dispatch(m)
    m.lpf(m.snapshots)
    lost_nolimit = dispatch_down_matrix(m).reindex(columns=lost.columns).fillna(0)

    total_hour = lost.sum(axis=1)
    free_hour = lost_nolimit.sum(axis=1)

    method1 = float((total_hour - free_hour).clip(lower=0.0).sum())
    method2 = max(0.0, float(total_hour.sum() - free_hour.sum()))
    negative_hours = int((total_hour - free_hour < -0.01).sum())

    print(f"\n=== {name} ===")
    for bus, p_nom, hours in batteries:
        print(f"  battery at {bus}: {p_nom:.1f} MW / {hours:.2f} h "
              f"({p_nom * hours:.1f} MWh capacity)")
    print(f"  total dispatch-down (all causes):       {lost.sum().sum():.1f} MWh")
    print(f"  surplus-based only (ratings lifted):     {lost_nolimit.sum().sum():.1f} MWh")
    print(f"  constraint-based, Method 1 (per-hour clip): {method1:.1f} MWh")
    print(f"  constraint-based, Method 2 (scalar subtract): {method2:.1f} MWh")
    if negative_hours:
        print(f"  [!] {negative_hours} hour(s) where ratings-lifted run curtailed "
              f"MORE than the real-ratings run — see docstring note on why "
              f"Method 1 and 2 can diverge with storage present")
    return method1, method2


if __name__ == "__main__":
    drum_p, drum_ep_mwh, drum_ep_hrs, drum_week = site_sizing_from_csv("Drumkeen wind")
    bin_p, bin_ep_mwh, bin_ep_hrs, bin_week = site_sizing_from_csv("Binbane wind")

    print(f"Battery sizing derived from this repo's own {DISPATCH_CSV}:")
    print(f"  Drumkeen: p_nom={drum_p:.2f} MW, episode={drum_ep_mwh:.1f} MWh/{drum_ep_hrs}h, "
          f"full-week total={drum_week:.1f} MWh")
    print(f"  Binbane:  p_nom={bin_p:.2f} MW, episode={bin_ep_mwh:.1f} MWh/{bin_ep_hrs}h, "
          f"full-week total={bin_week:.1f} MWh")

    _, baseline = run_scenario("Baseline (no battery)", [])

    _, a2 = run_scenario(
        "A: Drumkeen only, EPISODIC sizing",
        [("Drumkeen", drum_p, drum_ep_mwh / drum_p)],
    )
    _, b2 = run_scenario(
        "B: Drumkeen only, CONSERVATIVE sizing",
        [("Drumkeen", drum_p, drum_week / drum_p)],
    )
    c1, c2 = run_scenario(
        "C: Drumkeen + Binbane, EPISODIC sizing (each site independently)",
        [("Drumkeen", drum_p, drum_ep_mwh / drum_p),
         ("Binbane", bin_p, bin_ep_mwh / bin_p)],
    )
    _, d2 = run_scenario(
        "D: Drumkeen + Binbane, CONSERVATIVE sizing (each site independently)",
        [("Drumkeen", drum_p, drum_week / drum_p),
         ("Binbane", bin_p, bin_week / bin_p)],
    )

    print("\n=== Summary (Method 2 / scalar, comparable across scenarios) ===")
    print(f"  Baseline:                          {baseline:8.1f} MWh")
    print(f"  A. Drumkeen only, episodic:         {a2:8.1f} MWh ({(1 - a2/baseline)*100:5.1f}% relieved)")
    print(f"  B. Drumkeen only, conservative:     {b2:8.1f} MWh ({(1 - b2/baseline)*100:5.1f}% relieved)")
    print(f"  C. Drumkeen+Binbane, episodic:      {c2:8.1f} MWh ({(1 - c2/baseline)*100:5.1f}% relieved)"
          f"  [Method 1 gave {c1:.1f} MWh instead — see note above]")
    print(f"  D. Drumkeen+Binbane, conservative:  {d2:8.1f} MWh ({(1 - d2/baseline)*100:5.1f}% relieved)")
