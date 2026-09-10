# Dynamic Line Rating section — presentation summary

> **⚠️ SUPERSEDED — DO NOT QUOTE THE NUMBERS BELOW.** This document's
> 301.9/231.1 MVA (+43.7%/+29.8%) figures came from a 29-year weather
> archive with no solar radiation and an assumption that wind always hits
> the line perfectly perpendicular (the maximum-cooling case). The
> methodology has been redone: 2024-only weather, real PVGIS solar heat
> gain, and the line's real wind-direction geometry. The new, much more
> conservative real result is **213.0 MVA (+1.4%) winter, 184.4 MVA
> (+3.6%) summer** — the winter constraint does NOT disappear this time.
> See `dlr-2024-real-weather-rewrite.md` for the real numbers, what
> changed, and why. Everything below this notice is kept for historical
> reference only.

---

**The question the panel will ask:** *How could Dynamic Line Rating
reduce the amount of wind constraint on your model?*

**One-line answer to lead with:** a real, weather-derived winter rating
on the north-west's own bottleneck line raises its capacity by 43.7%,
and that alone is enough to eliminate the entire winter-week
constraint-based wind curtailment this project modelled — not just
shrink it. Summer is a smaller win (+29.8% capacity, recovers only
around a tenth of the much larger summer curtailment), which is itself
a useful, honest finding: DLR and battery storage turn out to be
complementary, not competing, once you split by season.

---

## The method — why this isn't a hand-waved "add 20%" number

DLR uses the line's actual current weather (wind cooling the conductor,
air temperature) instead of a fixed worst-case rating, since a
conductor's safe carrying capacity rises when wind speed is higher and
falls when it's hotter. This project computed a *real* rating, not an
assumed uplift:

- 29 years of Met Éireann hourly wind-speed and temperature observations
  from the nearest weather station to the target line (Finner Camp, Co.
  Donegal), filtered by season.
- A Hilpert-correlation thermal model converts those weather
  observations into a rating multiplier for every historical hour.
- The **P10** value of that multiplier's distribution (the rating that
  historical weather supports at least 90% of the time — a conservative,
  defensible choice, not the mean) is the representative seasonal rating
  used in the model.
- Cross-validated three independent ways before being trusted (see
  `dlr-cross-team-impact.md` for the detail) — this wasn't taken on
  faith.

Applied to **`5041-17010-2`** — the same Srananagh–Cathaleen's Fall line
Lucy's own Q1 work identified as the north-west's sole real bottleneck
(52 of 168 hours at 100% loading, every other line under 73% all week).

| Season | Static rating | Real-weather P10 rating | Uplift |
|---|---|---|---|
| Winter (WP2033) | 210 MVA | **301.9 MVA** | **+43.7%** |
| Summer (SV2033) | 178 MVA | **231.1 MVA** | **+29.8%** |

## Winter finding — the constraint doesn't shrink, it disappears

Applying the real 301.9 MVA winter rating and re-solving the full model:

- **Total wind dispatch-down across all 14 north-west farms** (the
  measure this project's own Step 1 work established as the honest way
  to quantify curtailment, once the structural finding that a correctly
  solved LOPF can never show `overload_MW > 0` was understood — see the
  next section) drops from **3,660.6 MWh/week to 3,072.0 MWh/week**.
- That 3,072.0 MWh isn't curtailment relief stopping partway — it *is*
  the theoretical floor: the same total you'd get with the line's rating
  removed entirely (lifted ×1000, "no network constraint at all"). In
  other words, real winter weather alone gets this line to behave as if
  it weren't a constraint at all, for this week.
- Concretely, for the specific battery-sizing work built on this line
  (Q2): the 588.6 MWh/week of *network-constraint-based* curtailment
  that battery was being sized against drops to **exactly 0.0 MWh** once
  the real winter rating is applied. The constraint that battery exists
  to solve is gone.
- At national (all-island) scale, this shows up as a structural result,
  not just a magnitude change: with the real winter DLR rating applied,
  `5041-17010-2` **doesn't appear in the all-island binding-lines list
  at all** — it no longer binds at any hour of the week, nationally or
  regionally.

## Summer finding — DLR helps, but doesn't solve it alone

Same method, summer P10 rating (231.1 MVA, +29.8% — a smaller uplift
than winter, because cooler, windier weather that helps conductor
cooling is itself a winter phenomenon):

- Total dispatch-down drops from **21,813.6 MWh/week to 19,701.3
  MWh/week** — a real reduction (~2,100 MWh), but the summer constraint
  starts roughly 6x larger than winter's, and DLR alone recovers only
  about a tenth of it.

## The framing this supports: DLR and batteries are complements, not rivals

This is the strongest panel-ready synthesis across the two mitigation
strategies this project modelled:

> **DLR does essentially all the work in winter; the battery earns its
> keep in summer.**

That's not a hedge — it's a genuinely earned, season-specific
conclusion, not "both help somewhat." It also reframes the battery
story: rather than a battery sized to solve a fixed 588.6 MWh/week
year-round problem, the honest picture is a battery whose real job is
covering the *much larger* summer gap that weather-based rating can't
reach, while DLR quietly handles winter for free.

## Robustness — why the panel should trust this number

- **Cross-validated three independent ways** before being adopted as the
  project's real DLR figure (method detail in `dlr-cross-team-impact.md`).
- **Independently reproduced by a completely different, earlier method**:
  the original arbitrary-uplift proxy (+0/10/20/30% on the static
  rating, run before the real-weather work existed) gives hours-at-rating
  of 52/39/19/13 and dispatch-down of 3,661/3,233/3,077/3,072 MWh — the
  30%-uplift proxy case lands on **3,072 MWh, matching the real-weather
  winter result to rounding**, despite being computed a completely
  different way by a different person. That's a strong, unplanned
  consistency check, worth stating explicitly if asked "how do you know
  this number is right."
- **Verified by actually re-running the model**, not estimated: the
  301.9/231.1 MVA ratings were patched into three separate teammates'
  scripts (Step 1's all-island baseline, the Q2 battery-siting model, the
  Q6 priority-curtailment model) and each was re-run end-to-end against
  the real network and solver — every one converges on the same 3,072.0
  MWh winter floor independently.

## Caveats worth naming up front, not waiting to be asked

- This is currently a **single-line** result. Real weather-derived DLR
  only exists for `5041-17010-2` so far — no weather station has been
  mapped to any of the project's other lines yet. Framed honestly: "this
  is one line, proven; the method generalises, extending it to more
  lines is the natural next step," not "the whole grid's constraint is
  solved."
- The **P10 threshold is a conservative choice, not the best case** — it
  represents what the weather supports at least 90% of the time, so an
  operational DLR scheme could plausibly do even better in practice; this
  project didn't chase that upside, it picked the defensible number.
- **Winter's dramatic result is specific to this modelled week**, not a
  claim that winter curtailment is solved everywhere, always — it's the
  real result for the WP2033 stress week this project modelled throughout.

---

### Quick-reference numbers for slides

| Metric | Value |
|---|---|
| Line DLR was applied to | `5041-17010-2` (the project's own identified bottleneck line) |
| Winter static → real rating | 210 → **301.9 MVA** (+43.7%) |
| Summer static → real rating | 178 → **231.1 MVA** (+29.8%) |
| Winter dispatch-down, static → DLR | 3,660.6 → **3,072.0 MWh/week** |
| Summer dispatch-down, static → DLR | 21,813.6 → **19,701.3 MWh/week** |
| Winter constraint-based curtailment (the number the battery was sized against) | 588.6 → **0.0 MWh/week** |
| All-island binding-lines list, with winter DLR applied | line **drops out entirely** |
| Independent cross-check | Arbitrary +30% uplift proxy (different method, different person) lands on 3,072 MWh — matches to rounding |
| Headline framing | DLR ≈ solves winter; battery earns its keep in summer — complements, not competitors |
