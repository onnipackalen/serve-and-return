# HANDOFF — read this first

Tennis match pricing model. Point-based (Barnett–Clarke) with opponent-adjusted
serve/return ratings, per-player surface and volatility weights, walk-forward
validated, and measured against the bookmaker's closing line.

**New session: read this, then `data_plan.md`.** `data_plan.md` is the running
lab notebook — every finding, every dead end, in order.

**State on handover (2026-09-16).** **The model did not change today.** No
refit chain was run; `weights.json`, the `fitted_params` ladder, the
`fitted_curves` values and `data/market_check.json` are exactly as
2026-09-15 left them, and the headline is unchanged at **0.60885 on 22,427
test matches**. What changed is the **confidence band**, the two caches
underneath it, the tooling around them and the app's trust panel. The band
was being fitted on inputs a live price never sees: the residual cache
carried no service-point count, so `confidence.fit` **substituted a
recent-match count** for "how well measured is this player" and **pinned
the volatility term to the constant 1**. The score could not reach its own
top band — HIGH was unreachable, `n = 0` in `confidence_model.json` — and
the band being measured was not the band a live price computes, which is
rule 19 one level below where it was written. The **same bug sat one level
down** in `tools/odds/disagree.py`, whose cache read service points out of
the shipped `weights.json` — today's numbers, for a match played two years
ago. Both caches now carry their real inputs (`backtest.walk_forward` takes
a `book_out` dict; `tools/curves.py build` stores `den` and `form_sd` on
every row) and **both were rebuilt** — 56,910 rows and 4,966 joined
matches — with the eight curve values verified **byte-identical**
afterwards. The band was then re-derived against **surprise** (the loss
minus the entropy of the model's own price) and came out at **three levels,
not four**: GOOD / FAIR / LOW are monotone in surprise on both halves of
the residual cache (**+0.0007 / +0.0068 / +0.0198** out of sample on 14,228
matches) and, independently, on the closing line (**+0.0132 / +0.0201 /
+0.0314**) — so the band now sorts both its own target and the market
deficit, which the band it replaced did not. `thin`, `form_sd` and
`best_of` were dropped, each with its measured numbers. One finding is
**measured and ready but NOT shipped**: the model is systematically
**under-confident over five sets** (−0.0212 surprise against +0.0112 for
best-of-three), and a per-format `form_scale` (0.70 for best-of-three, 0.50
for best-of-five) is worth **−0.00028 at t +2.14** on 21,584 held-out
matches and −0.00144 on the 4,209 best-of-five among them — `form_scale` is
a scalar on the live pricing path, so it wants its own pass
(`bo5_scale_note` in `fitted_params.json`). The 2026-09-15 state this
paragraph used to describe (the age-dependent prior at −0.00175 t +6.94,
the whole chain rebuilt on it, rules 32 and 33) is in its own section
below. **Start at Next steps item 0.**

---

## The headline, and it is not flattering

**The model does NOT beat the market.** Re-run 2026-09-15 on the
shipped path in its final configuration — 7-day refit cadence, carry cap
0.08, age multipliers (0.50, 0.85), the age-dependent prior (`prior_mode`
age, `prior_age` (2, 0)), on the archive refreshed 2026-09-14 —
walk-forward, nothing tuned on odds, before the curve layer:

| season | matches | model | Pinnacle closing (devig) | gap |
|---|---|---|---|---|
| 2025 | 2,388 | 0.62230 | **0.60373** | +0.01857 (was +0.02027 with the flat own prior, +0.02159 with the tour-average prior, +0.02252 at 21 days, +0.02201 at 14, +0.0248 at 91) |
| 2024 | 2,512 | 0.60568 | **0.58556** | +0.02012 (was +0.02230 with the flat own prior, +0.02228 with the tour-average one — flat; +0.02382 at 21 days, +0.02325 at 14, +0.0293 at 91) |

**The age-dependent prior improved both seasons**, where the flat own
prior had helped 2025 and left 2024 where it was. The paired walk-forward
number ((2, 0) vs (1, 1) −0.00175 at t +6.94 on 43,075 identical matches,
and −0.00181 at t +7.17 on the ratings when the two residual caches are
paired) is the measurement; the market checks are two seasons
of it, and they are taken **before** the curve layer, which is exactly
where the gain is not hidden (rule 33). The eight-curve layer, applied
downstream, is worth −0.0054 on the walk-forward set, so the live gap is
roughly **+0.013** in 2025. `tools/odds/m4.py` writes
`data/market_check.json` (per season: n, model, closing, gap, the buckets
below), which is what the app's "the model" tab shows; re-run `python3
tools/odds/m4.py 2025` before quoting.

**The gap is ORDERING, not calibration**, and it lives in confident
disagreement. By how far the model departs from the market, 2025 / 2024:

| split | n | deficit 2025 | deficit 2024 |
|---|---|---|---|
| within 2% of the market | 510 / 555 | +0.0005 | −0.0019 |
| 2–5% | 697 / 718 | +0.0058 | +0.0043 |
| 5–10% | 686 / 742 | +0.0196 | +0.0173 |
| **10%+** | 495 / 497 | **+0.0537** | **+0.0718** |

The 10%+ bucket, where the whole gap lives, shrank again under the
age-dependent prior — **555 → 495** matches in 2025 and **540 → 497** in
2024 (under the flat own prior it had gone 602 → 555 and 597 → 540). (With
the flat own prior, 2026-09-14: within 2% 488 / 507 at +0.0004 / −0.0001;
2–5% 666 / 704 at +0.0078 / +0.0012; 5–10% 679 / 761 at +0.0211 / +0.0164;
10%+ 555 / 540 at +0.0516 / +0.0791. With the tour-average prior,
2026-09-12 late: within 2% 480 / 475 at −0.0003 / −0.0001; 2–5% 629 / 672
at +0.0096 / −0.0001; 5–10% 677 / 768 at +0.0244 / +0.0176; 10%+ 602 / 597
at +0.0484 / +0.0712.) Where the model agrees with the market it *is* the
market — in 2024 the within-2% bucket is now a shade *ahead* of the
closing line (−0.0019 on 555 matches). An
optimal rescaling of the log-odds closes 2% of the gap (measured at M4); do
not spend time on calibration layers.

---

## Current state

Data runs through the **2026 US Open** (dated 2026-08-31 — the archive
dates a match by its tournament, rule 14; refreshed 2026-09-14 from
tennisabstract: 969 reconstructed rows, 782 with full serve stats): 80,150
main-tour matches plus 104,806 qualifying and Challenger matches that
supplement the rating fit. The model prices **43,075** of them walk-forward
at the 7-day refit cadence (on the archive before the refresh: 42,997 at 7
days, 43,003 at 3, 42,901 at 14, 42,838 at 21, 42,169 at 91 — the scorable
set moves with the archive and the cadence, as it moved from 43,514 to
42,169 with the age multipliers: a scoring artefact, not a model cost) and
rates **2,742** players on the five-year window (`weights.json` `overall`,
rebuilt 2026-09-15; it was 4,555 on the ten-year window `weights.build`
used to load; the harness always used five, and now both do).

**Official backtest, shipped path end to end** (one walk at the 7-day
cadence with the age-dependent prior, on the refreshed archive; 20,648
train / **22,427 test** matches, 43,075 scorable; 634 refits in the walk;
the train half fitted `form_scale`, `dens_w`, calibration):

| model | log loss | vs above | paired t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo, K=4 (results only) | 0.66280 | | |
| tour-wide single rating (form_sd 0.040) | 0.61418 | | |
| + calibration | 0.61425 | +0.00007 | −2.70 |
| per-player surface + form (scale 0.70) | 0.61066 | | |
| + in-event update (w=2) | 0.60893 | −0.00173 | +5.67 |
| + air density (w=0.40) | **0.60885** | −0.00009 | +4.04 |
| + calibration (slope 1.009 measured) — **off, by its own test** | 0.60891 | +0.00007 | −3.09 |
| three-stage serve ON (measured, not shipped) | 0.61499 | +0.00615 vs shipped | −8.85 |

The headline is **0.60885**. Calibration measured slope 1.009 and is
**off**: applying it costs +0.00007 at t −3.09 on the shipped path and
+0.00007 (t −2.70, 0.61418 → 0.61425) on the tour-wide single rating.
(With the flat own prior the slope was 1.007 and off, +0.00007 at t −3.68;
with the tour-average prior at 7 days it was 1.012 and off; at 21 days
0.997, identity, and the switch was on; at 91 days 1.012 had hurt and it
was off.) It follows the model; leave the switch alone. The model beats
Elo by **0.0540** on the same 22,427 matches. `form_scale` stays at
**0.70** and the tour-wide `form_sd` at 0.040 under the age-dependent
prior, as under the flat own prior (0.50 / 0.030 under the tour-average
prior, where 0.50 held at every cadence from 21 days down and 0.60 at 91).
The curve layer is scored separately (below): **−0.00541**, 4 folds of 4.

⚠️ **0.60885 is not comparable to any earlier headline** (**0.61059** was
the same 22,427 test matches on the same archive with the **flat own
prior**; **0.61140** was 22,420 test matches on the archive **before the
refresh**, with the tour-average prior; 0.61295 was 22,344 at the 21-day
cadence; 0.61227 was 22,385 at 14 days; 0.61720 was 22,012 at 91; before
that 0.61797, 0.61929, 0.61400, 0.61791 …). The scorable set moves with
the archive and the cadence. The honest numbers for the prior are the
paired ones — **age (2, 0) vs the flat own prior −0.00175 at t +6.94 on
43,075 identical matches** (`tools/knobsweep.py run prior_age`, fourteen
walks) and, on the residual caches, **−0.00181 at t +7.17 on the ratings
and +0.00016 at t −0.80 after the curves** (rule 33); before it, **own vs
tour −0.00091 at t +2.92 on the same 43,075** (`tools/knobsweep.py run
prior_mode own`, two walks on the refreshed archive) — and for the cadence
the paired steps — **14 vs 21 −0.00074 at t +2.74, 7 vs 14 −0.00080 at t
+3.72, 3 vs 7 −0.00023 at t +5.38** (`tools/knobsweep.py compare
refit_days`, each on ~41,800 common matches of the old archive) — with the
full ladder against 7 on 41,801 common (the cadence table below). Judge
any change with a paired tool, never with two headline numbers.

Current fitted state, all in `fitted_params.json`. The values are current.
The writeback carries `carry_cap`, `surface_half_life_days`, `refit_days`,
since 2026-09-14 `prior_mode` and since 2026-09-15 `prior_age`, so a swept
value survives the next refit (rule 7), and since 2026-09-12 (late) also
`test_matches` (22,427) and `elo_log_loss` (0.66280), which the app's "the
model" tab reads. `prior_age_note` is new (2026-09-15) and carries the
whole fourteen-value sweep, the both-halves guard and the both-ways
result; `test_log_loss_note`, `three_stage_note`, `event_update_note` and
`surface_carry_note` were rewritten on 2026-09-15 for the age-dependent
prior and keep the flat-own-prior, tour-prior, 21-day and 91-day numbers
as history; `prior_mode_note` and `trait_k_note` are 2026-09-14 and still
the record; **`curves_note` (and `fitted_curves.json`'s `_note`) still
read −0.00738 on the 2026-09-14 cache** — the backtest writeback runs
before `curves.py` in the chain, so they need the hand edit rule 7 asks
for; the curve numbers below come from `chain_age.log`. `refit_days_note`
and `knob_sweep_note` still describe the 2026-09-12 sweeps on the old
archive (untouched); `carry_cap_note`, `age_hl_note` and `qc_note` record
91-day-era sweeps that were not re-run and are still the record; the
weight sweep inside `event_update_note` (w = 0.5 … 4) is the 2026-09-11
sweep at (0.70, 0.85), never re-run. Refresh a note — re-run `tennis.py
backtest`, then edit by hand whatever it does not rewrite — before quoting
it:

| | |
|---|---|
| `half_life_days` / `prior_weight` / `train_years` / `long_years` | 270 / 150 (re-swept 2026-09-14 under the own prior: stays) / 5 / 12 |
| `prior_mode` | **age** (adopted 2026-09-15: the prior is the player's own long-window rating blended back toward the tour average at the ends of a career; was `own`, the flat player-specific prior, from 2026-09-14, and `tour`, the tour average, before that) |
| `prior_age` | **(2, 0)** (adopted 2026-09-15: double the deviation at 22 and under, own level at 28, tour average at 34+; (1, 1) is exactly `prior_mode` own; −0.00175 at t +6.94 on 43,075 identical matches, −0.00181 at t +7.17 on the ratings and +0.00016 at t −0.80 after the curves) |
| `age_m_young` / `age_m_old` | 0.50 / 0.85 (adopted 2026-09-11; was 0.70 / 0.85) |
| `qc_supplement` / `qc_level_k` | on / 1.0 |
| `surface_carry` / `carry_cap` | on / **0.08** (adopted 2026-09-12; was 0.05, chosen not fitted) |
| `surface_half_life_days` | 1095 (swept 2026-09-12, flat, stays) |
| `refit_days` | **7** (adopted 2026-09-12, late, via 21 and 14 — each measured paired and rebuilt; was 91 by convenience; 3 measured and not adopted, rule 30) |
| `event_update_w` | 2.0 |
| `three_stage_serve` | **off** (rejected in company, see below) |
| `form_scale` / `form_sd` (tour-wide) | **0.70** / 0.040 (unchanged by the age-dependent prior; refit from 0.50 / 0.030 under the flat own prior; 0.50 / 0.030 under the tour-average prior at every cadence from 21 days down, 0.60 at 91) |
| `dens_w` | 0.40 |
| `calibration_b` | **1.0 = off** (measured **1.009**; applying it costs +0.00007 at t −3.09; with the flat own prior 1.007, +0.00007 at t −3.68, off; with the tour-average prior at 7 days 1.012 was off too; at 21 days the measured 0.997 was identity and on; the 91-day run's 1.012 had hurt and was off on 2026-09-11) |
| `news_w` | 1.0 (a prior, not a fit) |
| `test_matches` / `elo_log_loss` | 22,427 / 0.66280 (writeback since 2026-09-12 late, for the app's model tab) |
| `scorable_matches` | 43,075 (the walk prices these; 22,427 of them are the test half) |

Eight residual curves: `age`, `resid_prior`, `matches_28d`, `event_gwp`,
`entry`, `form_spw`, `event_sets_lost`, `home`.

---

## What happened on 2026-09-16

Five things, in order. **The model did not change**: no refit chain was
run, and `weights.json`, the `fitted_params` ladder, the `fitted_curves`
values and `data/market_check.json` are all as the day before left them.

1. **Two caches were lying about their inputs.** The band's job is "how far
   to trust this price", and it was fitted by `confidence.fit` on the
   residual cache — which carried no service-point count, so the fit
   **substituted a recent-match count** for "how well measured is this
   player" and **pinned the volatility term to the constant 1**. The
   resulting score could not reach its own top band: HIGH was unreachable,
   `n = 0` in `confidence_model.json`, and the band being measured was not
   the band a live price computes — rule 19, one level below where it was
   written. FIX: `backtest.walk_forward` takes an optional `book_out` dict
   and sets it to the block each match was priced from, so a caller can
   read the service points behind each rating **as of that match**;
   `tools/curves.py build` now stores `den` and `form_sd` on every cache
   row. Cache rebuilt (**56,910 rows**), and the eight curve values are
   **byte-identical** afterwards, verified. The SAME bug sat one level down
   in `tools/odds/disagree.py`, whose cache read service points out of the
   shipped `weights.json` — today's numbers, for a match played two years
   ago — which put well-measured players in the thin bucket. Same fix,
   cache rebuilt (**4,966 joined matches**).
2. **The derivation, with the target chosen first.** SURPRISE: the loss
   minus the entropy of the model's own price. Raw log loss cannot be the
   target (rule 16 — a coin flip scores badly for everyone) and the market
   deficit cannot be either, because it is a difference between two models
   and the band describes only one of them, which is exactly how the old
   ordering broke; the deficit is kept as the out-of-sample **check**. Its
   blind spot is stated in the docs: surprise does not punish
   under-confidence. `comeback` survived and is now the **count** rather
   than a flag; `cold` survived, weak and monotone; `thin`, `form_sd` and
   `best_of` were dropped with their numbers (the Confidence bands section
   has the table). Scratchpad `bandfit_final.py` is the derivation.
3. **Three levels, not four.** `score = cold + 2*comeback + 2*unmeasured`,
   `BANDS = [(0,0,"GOOD"), (1,2,"FAIR"), (3,99,"LOW")]`. The fourth level
   claimed a resolution the data does not support — on the test half the
   old top two bands sat within 0.004 nats of each other and in the wrong
   order. Out of sample on 14,228 matches the three sort in surprise
   (**+0.0007 / +0.0068 / +0.0198**) and, independently, on the closing
   line (**+0.0132 / +0.0201 / +0.0314**, re-measured by
   `tools/odds/disagree.py bands` on the rebuilt cache, n 996 / 3,518 /
   452). The raw log loss is **flat** across them (0.6088 / 0.6084 /
   0.6136), which is rule 16 in one line. What is left of `thin` is a
   **floor, not a fit**: below 1,500 points the harness never scores a
   match, so a live price there gets +2 on the score and is labelled
   unmeasured.
4. **A finding worth more than the band: best-of-five.** Five-setters carry
   **−0.0212** surprise against **+0.0112** for best-of-three, and it
   survives conditioning on how well measured the players are (within the
   thinnest bucket: best-of-three +0.0225, best-of-five −0.0177). The model
   is systematically **under-confident over five sets** — a calibration
   error to fix in the model, not a trust level to report in a band, so it
   was kept out of the band and tested directly on the shipped walk's
   cached predictions (no new walk). `form_scale` fitted per format on the
   train half: **best of 3 → 0.70, best of 5 → 0.50**. On 21,584 held-out
   matches, paired: one scale 0.60927, scale per format **0.60899**
   (**−0.00028 at t +2.14**); best of 3 (17,375) unchanged at −0.00000, t
   +0.00; best of 5 (4,209) 0.53321 → 0.53177, **−0.00144 at t +2.14**.
   **NOT SHIPPED**: `form_scale` is a scalar read by `price.scaled_form_sd`
   and `backtest.price_player`, so a format-dependent one touches the live
   pricing path and wants its own pass — plumbing, writeback, refit chain
   and the both-ways check of rule 33. Recorded in `fitted_params.json` as
   `bo5_scale_note`, and it is Next steps item 0.
5. **The app.** The band panel now **leads with the surprise** ("on 1,217
   held-out matches this band came out +0.0198 nats worse than the model's
   own confidence implied"), because raw log loss does not sort across
   bands; the deficit against closing is printed underneath, described as
   the **independent check** rather than the target; and the "thinner side"
   row says plainly that above 1,500 points it no longer moves the band and
   below it the band assumes the worst. **All six gates pass**; the app was
   restarted and verified.

---

## What happened on 2026-09-15

Seven things, in order — all of them one knob, measured from every side.

1. **The idea** (Next steps item 1 of the previous list). On 2026-09-14
   the 270-day rating started being shrunk toward the player's **own**
   long-window rating instead of the tour average (`prior_mode` own),
   which won −0.00091 at t +2.92. It also made the age curve **bigger**
   (youngest minus oldest +0.075 → +0.085), and the mechanism was plain:
   the 12-year window holds a declining player's peak and a rising
   player's junior years, and the prior bites hardest exactly where the
   270-day window is thin. At the shipped as-of day, **263 of the 292
   rated players past 34** are under 1,500 service points, and **421 of
   the 436 under 22**. So blend the own prior back toward the tour average
   at the ends of a career, and leave the prime alone.
2. **The knob, and its self-check.** `weights.PRIOR_AGE = (young, old)`:
   how much of a player's own **deviation** from the tour average survives
   into the prior at each end of a career — `prior = tour + w(age) · (own
   − tour)`. The ramp between them is `ratings.age_multiplier` with
   `AGE_KNOTS` (22, 28, 34), **pinned to 1.0 at the prime**, so the knob
   only ever changes the ends and there is ONE definition of young /
   prime / old in the project (rule 19). A player with no birthday keeps
   the own prior, the same fallback the age-dependent half-life makes.
   **(1, 1) is exactly `prior_mode` own — verified to 0.0 before any walk
   ran**, which is rule 31 made a habit: the baseline of a nested sweep
   must reproduce the shipped model bit for bit, or the sweep is measuring
   the wiring. Env override `TENNIS_PRIOR_AGE`; written back by
   `backtest.py` (rule 7); swept by `tools/knobsweep.py run prior_age`.
3. **The sweep** (fourteen values, one walk each, paired on 43,075
   identical matches, test 22,427, against the shipped (1, 1)):

   | value (young, old) | vs (1, 1) | t |
   |---|---|---|
   | 0, 0 | +0.00083 | −3.42 |
   | 0.5, 0.5 | +0.00033 | −2.90 |
   | 0.5, 0 | −0.00007 | +0.36 |
   | 1, −1 | −0.00094 | +2.62 |
   | 1, −0.5 | −0.00095 | +3.63 |
   | 1, 0.5 | −0.00032 | +3.06 |
   | 1, 0 | −0.00075 | +4.31 |
   | **1, 1** | shipped until today | |
   | 1.5, 0 | −0.00121 | +5.76 |
   | 2, −0.5 | −0.00174 | +5.20 |
   | **2, 0** | **−0.00175** | **+6.94** ← adopted |
   | 2.5, 0 | −0.00191 | +5.97 |
   | 3, 0 | −0.00189 | +4.73 |
   | 4, 0 | −0.00198 | +3.84 |

   Damping the **old** end helps; damping the **young** end hurts, and the
   young end wants **amplification** — the opposite of what "shrink the
   ends" would have guessed.
4. **Both edges probed until they turned over (rule 26).** A grid optimum
   on the edge is a flag, not a result, so the young end was walked out to
   4 and the old end past zero to −1. The loss flattens from 2 upward
   while the t falls away and `form_scale` starts climbing (0.85 at
   (4, 0), against 0.70 at (2, 0)) — the sign of a rating layer being
   compensated elsewhere. The plateau therefore begins at 2, and **the
   smallest change with the highest t ships**, exactly as `carry_cap` did
   on 2026-09-12. **Adopted (2, 0)**: double the deviation at 22 and
   under, own level at 28, tour average at 34 and over.
5. **The guard — both halves, now automatic (rule 32, new).** Fourteen
   values chosen by held-out log loss is fourteen draws from one test
   half. `tools/knobsweep.py compare` now scores every value on **both**
   halves and flags a value that wins only on test. Every value that won
   on test also won on train, **in the same order**; the only "TEST ONLY"
   row was (0.5, 0) at −0.00007 (train +0.00021 at t −1.60), which is
   noise and not a candidate. The sweep's choice is not read off the half
   it is scored on.
6. **The honest result — measured BOTH ways (rule 33, new).** The curves
   are fitted on the residuals of whatever rating layer ships, so they
   correct what it gets wrong; improve the ratings and the curves have
   less to do, not the price. Measured on the two residual caches,
   22,759 identical matches (scratchpad `curvepair.py`):

   | | own prior | age prior | vs | t |
   |---|---|---|---|---|
   | ratings alone | 0.61068 | 0.60887 | **−0.00181** | **+7.17** |
   | + the eight curves | 0.60330 | 0.60346 | **+0.00016** | **−0.80** |

   The curves were already correcting most of what the prior fixes, so the
   moneyline price barely moves. "The price moved" would have been false.
7. **It ships anyway, and the chain was rebuilt.** For what the curves do
   not cover: the **market gap** improved on both seasons (2025 +0.02027 →
   +0.01857, 2024 +0.02230 → +0.02012) and the 10%+ disagreement bucket
   shrank in both (555 → 495, 540 → 497); the **totals path** takes the
   serve probabilities directly and never sees the curves; the
   **correction layer shrank** from −0.00738 to −0.00541, so less of the
   answer is a fitted residual shape; and the **age curve** — the thing
   that prompted this — fell from a +0.085 spread costing +0.00227 to
   drop, to +0.056 costing +0.00091. A model that needs less correction is
   the point. `tools/refit_chain.sh` (log `chain_age.log`): headline
   **0.60885 on 22,427 test matches** (train 20,648; 43,075 scorable; 634
   refits in the walk, 445 s for the path-sweep walk), Elo 0.66280 (the
   model beats it by 0.0540), `form_scale` 0.70 / tour `form_sd` 0.040,
   calibration off (slope 1.009); the flip-one-knob table, the eight
   curves (**−0.00541** on 56,910 player-rows), the confidence bands and
   the market check re-measured (their sections below); **all six gates
   PASS, `== DONE`**. Rebuilt, in order: `weights.json`,
   `fitted_params.json` (+ `prior_age_note`, and the `test_log_loss`,
   `three_stage`, `event_update` and `surface_carry` notes),
   `tools/_pathsweep/all.json`, `tools/residuals.json`,
   `fitted_curves.json` + `data/player_traits.json`,
   `confidence_model.json`, `data/market_check.json`.

## What happened on 2026-09-14

Seven things, in order.

1. **The weekly refresh (rule 30, item 0).** `python3 update.py` at 21:57:
   the Sackmann mirror is still dead ("nothing new upstream" — a no-op);
   `tools/ta/refresh.py` fetched 427 player pages from tennisabstract.com
   and rebuilt `data/manual_matches.csv`: **969 rows** (was 965), **782
   with full serve stats** (was 701 — the 2026 US Open now has 127 rows, 91
   with stats), dated 2026-05-25 .. 2026-08-31 (the US Open is dated by its
   start, rule 14). The weather cache was extended to 2026-09-14.
   Provenance re-verified: 80,150 matches, 91.1% pass the arithmetic
   identities, tour average serve 0.6320, **VERIFY PASS**. Then the whole
   refit chain (`tools/refit_chain.sh`) on the refreshed archive — item 6.
2. **Entry codes now come from the feed.** Tennis Abstract prints each
   player's draw prefix in the result cell exactly as the archive records
   it — "(10)Jacquet", "(Q)Jacquet", "(WC)Gabriel Diallo [CAN]", "(LL)",
   "(Alt)" — and `tools/ta/build.py` had been stripping it. Now
   `build.prefix_of()` reads it (digits → seed; letters → entry code, `Alt`
   kept as the archive spells it), `split_result_full()` carries both
   sides' prefixes, `build.main()` stores seed / entry / opp_seed /
   opp_entry per side, and `emit.py` fills `winner_seed` / `winner_entry` /
   `loser_seed` / `loser_entry` (a player's own page first, else what the
   opponent's page printed about them). Re-emitted (`refresh.py
   --rebuild-only`): **341 of 969 rows carry an entry code** on at least
   one side (Q on 196 sides, WC 112, LL 51, PR 14, SE 3), **579 rows carry a seed**;
   `load.py` reads them unchanged (same column names) and
   `features.live_workload` returns entry Q for the 2026 US Open
   qualifiers from their archive rows at the event. Consequence: the
   `entry` curve no longer needs the flag for any player who has already
   played a match at the event — only for a player's **first** match there
   (the draw is not in the archive until it is played). The `--entry`
   flags, the prompt commands and the app selects stay for that case. The
   curves cache (`features.build` → `tools/curves.py build`) now sees entry
   codes on the reconstructed rows too.
3. **`TRAIT_K` / `TRAIT_MIN` swept — flat, stays (40, 15)** (item 4 of the
   previous list). `tools/traitsweep.py` (new) re-annotates the cached
   residual rows in memory per (K, MIN), refits the eight curves per fold
   and scores the shipped antisymmetric log-odds application at k=1,
   paired per-match t on 22,697 identical matches (56,754 player-rows, the
   7-day cache before the refresh; ~10 s a value, no walk). K in {10, 20,
   40, 80, 160, 320} × MIN in {5, 10, 15, 25, 40}: everything within noise
   of the shipped (40, 15); best cell (40, 10) −0.00007 at t +1.07; MIN =
   40 costs +0.0002 .. +0.0003 at t −1 .. −1.5 for every K; K = 320 costs
   +0.00013 .. +0.00032. Recorded in `trait_k_note`; the grid is in the
   constants section. The last chosen constants of the correction layer
   are now measured.
4. **A player-specific prior — measured and adopted** (item 1 of the
   previous list, "per-player prior weight"). `prior_mode` in `weights.py`
   (`TENNIS_PRIOR_MODE` / `fitted_params` `prior_mode`; `tour` shipped):
   with `own`, the 270-day rating is shrunk (by the same `prior_weight`
   150) toward the player's **own** long-window rating — the 12-year,
   1,095-day-half-life fit that already exists for the surface carry-over
   — instead of the tour average, so a player back from a layoff is pulled
   toward who they were, not toward the middle of the tour.
   `ratings.fit_iterative` and `fit_iterative_reference` take an optional
   `priors={pid: (serve, ret)}`; the vectorised-equals-reference gate now
   includes a priors case (max diff 1.5e-11, PASS). The long fit moved
   before the main fit inside `weights.derive` (same numbers; the harness
   == `weights.json` gate is in the chain). `backtest.py` writes
   `prior_mode` back (rule 7); `tools/knobsweep.py` sweeps it. **Result**
   (`tools/knobsweep.py run prior_mode own`; two walks on the refreshed
   archive at the shipped 7-day cadence, cap 0.08, 43,075 identical
   matches, train 20,648 / test 22,427): **own −0.00091 at t +2.92**
   against tour; `form_scale` refits from 0.50 to 0.70 under the own
   prior. **Adopted** (`prior_mode` "own" in `fitted_params.json`).
   Follow-up: `prior_weight` (150, fitted against the tour-average prior)
   re-swept under the own prior (`TENNIS_PRIOR_MODE=own tools/knobsweep.py
   run prior_weight 100 300 600`): 100 −0.00002 (t +0.39); 150 shipped;
   300 +0.00053 (t −4.71); 600 +0.00118 (t −5.58) — **150 stays** (all
   four on the same 43,075 matches, own prior).
5. **A mistake found on the way — the harness had its own prior weight
   (rule 31).** `backtest.py` read `PRIOR_W` (and `HALF_LIFE`) from
   `fitted_params` itself instead of from `weights.py`, so the new
   `TENNIS_PRIOR_WEIGHT` override moved the live derivation and not the
   harness: the first `prior_weight` sweep returned four **identical**
   walks (0.61059, t 0.00 for 100 / 150 / 300 / 600). Fixed the same day:
   `backtest.HALF_LIFE = weights.HALF_LIFE` and `backtest.PRIOR_W =
   weights.PRIOR_WEIGHT` — one source for the rating-layer constants (rule
   19); the harness == `weights.json` gate (`backtest.py --gate`) still
   passes. Rule 31 (new): a sweep whose values all score identically is a
   broken knob, not a flat one — check that the override reaches the code
   that fits.
6. **The chain rebuilt on the refreshed archive with the own prior**
   (`tools/refit_chain.sh`, 2026-09-14, log `chain_own.log`): headline
   **0.61059 on 22,427 test matches** (train 20,648; 43,075 scorable), Elo
   0.66280 (the model beats it by 0.0522), `form_scale` 0.70 / tour
   `form_sd` 0.040, calibration off (slope 1.007); 634 refits in the walk;
   the flip-one-knob table, the eight curves (**−0.00738** on 56,910
   player-rows), the confidence bands and the market check re-measured
   (their sections below); **all six gates PASS, `== DONE`**. Rebuilt, in
   order: `weights.json`, `fitted_params.json` (+ notes: `prior_mode_note`
   and `trait_k_note` new; `test_log_loss_note`, `three_stage_note`,
   `event_update_note`, `surface_carry_note`, `curves_note` rewritten;
   `knob_sweep_note` and `refit_days_note` untouched),
   `tools/_pathsweep/all.json`, `tools/residuals.json`,
   `fitted_curves.json` + `data/player_traits.json`,
   `confidence_model.json`, `data/market_check.json`.
7. **The app names entry codes.** Restarted on the final model; the match
   view says "entered as qualifier" and the player page's "entered as" row
   reads the code from the archive's rows at the event ("the results feed
   carries the draw prefix since 2026-09-14") — `ENTRY_NAMES` in
   `web/app.js`: main draw, qualifier, wild card, lucky loser, protected
   ranking, special exempt — or says it is unknown until they have played
   here, or until you say.

## What happened on 2026-09-12

Eight things, in order.

1. **Entry type went live and became the eighth curve** (the curves
   section has the numbers and the plumbing).
2. **Two trend-shaped traits were measured and rejected** as substitutes
   for `resid_prior`: `resid_365` (the player's residual over the last 365
   days only, K=20, min 8) is −0.00131 alone but **+0.00092** when added to
   the seven; `resid_surface` (the residual on this row's surface only) is
   −0.00038 alone, **+0.00119** added. Both are still computed into
   `data/player_traits.json` (`resid_365`, `surf`) and supplied live, so
   they can be re-measured.
3. **The constants that had been chosen rather than fitted were swept**
   (the next section): the refit cadence moved from 91 to 21 days
   (−0.00413 at t +7.06) and the carry cap from 0.05 to 0.08 (−0.00047 at
   t +2.17); surface half-life, long window, age knots and the curve
   magnitude k stayed. The chain was rebuilt at 21 days: headline 0.61295
   on 22,344 test matches.
4. **The cadence was walked below 21, one step at a time**, each step
   paired (`tools/knobsweep.py`) against the value that had just shipped:
   **14 vs 21 −0.00074 at t +2.74** (41,816 common / 21,902 test; cap
   0.08), **7 vs 14 −0.00080 at t +3.72** (41,803 / 21,899), **3 vs 7
   −0.00023 at t +5.38** (41,801 / 21,898). 14 was adopted and the chain
   rebuilt (for the record, superseded the same day: headline 0.61227 on
   22,385 test, train 20,516; Elo 0.66292; calibration off, 0.61227
   uncalibrated vs 0.61230 calibrated; m4 2025 2,386 matches 0.62606 vs
   0.60405, gap +0.02201; 2024 2,500 matches 0.60912 vs 0.58587, gap
   +0.02325; all six gates passed). Then 7 was adopted and the chain
   rebuilt again — headline 0.61140 on 22,420 test matches with the tour-average prior, superseded on 2026-09-14 by the rebuild on the refreshed archive with the own prior (0.61059), and that in turn on 2026-09-15 by the age-dependent prior (0.60885 — the state this document describes).
5. **7 ships; 3 is measured and not adopted — rule 30.** The 3-day gain is
   real (t 5.4) and 0.0002 nats. The cadence is a promise: the measured
   headline assumes the live ratings are never staler than the cadence,
   i.e. `update.py` at that rhythm, and the results mirror has been frozen
   (847 rows since), so weekly is the cadence the tool can actually keep.
   Switching is one refit chain (`refit_days` in `fitted_params.json` or
   `TENNIS_REFIT_DAYS=3`).
6. **The app (`app.py` + `web/`) was rebuilt around "type a name, Enter,
   twice"**:
   - the search box: Enter puts the highlighted match into the next empty
     slot, ↑↓ move the highlight, Esc clears; a typed name searches
     *everyone* (the data filter no longer hides the player you asked for;
     thin ratings are marked "thin data"); the slot that will be filled
     next is marked "next";
   - a guided empty state with a "show me an example" button (the two
     highest-rated players);
   - a one-line reading under the call ("Sinner 60.7%, a lean — fair odds
     1.65; confidence LOW") with "copy the call";
   - naming a tournament sets surface and best-of from the archive's most
     recent edition at that venue (`State._venue_hints`, keyed like the
     venue list), with a note saying so; both can be changed;
   - bookmaker odds A/B inputs: `price.market_view()` (new, in `price.py`)
     removes the margin proportionally — the same devig as
     `tools/odds/m4.py` — and the page shows market vs model and the
     difference in points, with the measured caveat (the model is ~0.02
     nats behind closing; a disagreement is a question, not an edge).
     Compared with the call, never used in it;
   - the address bar carries the match
     (`#a=&b=&surface=&best_of=&at=&entry_a=&entry_b=&odds_a=&odds_b=`),
     restored on load;
   - a phone layout (≤ 760px): the index sits above the match and folds
     away once both players are in; "change players" brings it back;
   - a "the model" tab that reads `test_log_loss` / `elo_log_loss` /
     `test_matches` / `refit_days` / `carry_cap` from `fitted_params.json`
     and the market check from `data/market_check.json`. The typed-in
     numbers the tab used to carry were stale within a day;
   - stale CSS variable names in `app.js` fixed (`--a` / `--warn` /
     `--dimmer` never existed); the player page shows the player's own
     residual against the point model (`resid_prior`) and the entry code
     when the archive has it;
   - `.claude/launch.json` added so the app can be previewed; the stray
     `app.py` on :8765 (old model) was killed and the server restarted on
     the final model after the refit.
7. **`tools/odds/m4.py` now writes `data/market_check.json`** (per season:
   n, model, closing, gap, buckets by |model − closing|), which is what the
   app's model tab shows instead of typed-in copies.
8. **`backtest.py`'s writeback now also carries `test_matches` and
   `elo_log_loss`** in `fitted_params.json`, for the same tab.

## Constants that were chosen, now measured

`tools/knobsweep.py` runs one full walk-forward per value in its own
subprocess (the constants are module-level, read once at import, so a
process per value is the honest way to vary them), scores every value on
the intersection of what they all price, fits `form_scale` on the train half
per value, and pairs each against the shipped value with a per-match t
(rule 1), and, since 2026-09-15, prints **both halves** so that a value
winning on test must also win on train, in the same order — a wide sweep
read off one half is a wide set of chances to be lucky (rule 32). The
`TENNIS_*` environment overrides — `TENNIS_SURFACE_HL`,
`TENNIS_LONG_YEARS`, `TENNIS_CARRY_CAP`, `TENNIS_REFIT_DAYS`,
`TENNIS_AGE_KNOTS`, `TENNIS_TRAIT_K`, `TENNIS_TRAIT_MIN`, since
2026-09-14 `TENNIS_PRIOR_MODE` and `TENNIS_PRIOR_WEIGHT`, and since
2026-09-15 `TENNIS_PRIOR_AGE` — exist for it (an override must reach the
code that fits, rule 31), and the backtest writeback now carries
`carry_cap`, `surface_half_life_days`, `refit_days`, `prior_mode` and
`prior_age`, so a swept value survives the next refit (rule 7). The
four constant sweeps below ran at the 91-day cadence, before it changed;
the cadence itself was then walked down one step at a time; the prior and its
weight were swept on 2026-09-14 (7-day cadence, refreshed archive), the
age ramp of the prior on 2026-09-15 on the same archive, and
the trait constants on 2026-09-14 on the 7-day residual cache from before
the refresh (56,754 player-rows). "vs shipped" is the cost (negative is better); t is
signed for the candidate.

**Surface half-life** (`surface_half_life_days`; 42,169 common matches):

| value | vs shipped | t |
|---|---|---|
| 730 | +0.00015 | −0.74 |
| **1095** | shipped | |
| 1460 | −0.00006 | +0.84 |
| 2190 | +0.00006 | −0.39 |

Flat. Stays.

**Long window** (`long_years`; 42,169):

| value | vs shipped | t |
|---|---|---|
| 8 | +0.00004 | −0.45 |
| **12** | shipped | |
| 16 | +0.00004 | −0.95 |

Flat. Stays.

**Age knots** (`AGE_KNOTS`; 40,960 common):

| value | vs shipped | t |
|---|---|---|
| (20, 26, 32) | +0.00044 | −2.94 |
| **(22, 28, 34)** | shipped | |
| (24, 30, 36) | +0.00005 | −0.42 |

Stays.

**Carry cap** (`carry_cap`; 42,169):

| value | vs 0.05 | t |
|---|---|---|
| 0.03 | +0.00157 | −3.98 |
| 0.05 | shipped until 2026-09-12 | |
| **0.08** | **−0.00047** | **+2.17** ← adopted |
| 0.10 | −0.00049 | +2.01 |
| 0.12 | −0.00051 | +1.96 |
| no cap | −0.00053 | +1.90 |

A plateau from 0.08 up; the smallest change with the highest t ships.

**Refit cadence** (`refit_days`). First the sweep against 91 (40,374
common / 21,378 test), then, below 21, one step at a time with each value
paired against the one that had just shipped (`form_scale` fitted per value
on the train half; cap 0.08 throughout the steps):

| value | paired against | delta | t | common / test |
|---|---|---|---|---|
| 182 | 91 | +0.00410 | −5.38 | 40,374 / 21,378 |
| 91 | shipped until 2026-09-12 | | | |
| 45 | 91 | −0.00135 | +2.61 | 40,374 / 21,378 |
| 30 | 91 | −0.00252 | +4.54 | 40,374 / 21,378 |
| 21 | 91 | −0.00413 | +7.06 | 40,374 / 21,378 |
| 14 | 21 | −0.00074 | +2.74 | 41,816 / 21,902 |
| **7** | 14 | **−0.00080** | **+3.72** | 41,803 / 21,899 |
| 3 | 7 | −0.00023 | +5.38 | 41,801 / 21,898 |

21 was adopted, then 14, then 7, each with the chain rebuilt; **7 ships**;
3 is measured and not adopted. The full ladder against the shipped 7
(`tools/knobsweep.py compare refit_days`, 2026-09-12 on the archive before
the refresh with the tour-average prior — the 7 row's 0.61112 / 0.50 /
42,997 are that run's values, not today's 0.60885 / 0.70 / 43,075; 41,801
common matches, train 19,903 / test 21,898):

| value | form_scale | test log loss | vs 7 | t | prices alone |
|---|---|---|---|---|---|
| 3 | 0.50 | 0.61089 | −0.00023 | +5.38 | 43,003 |
| **7** | 0.50 | **0.61112** | shipped | | 42,997 |
| 14 | 0.50 | 0.61192 | +0.00080 | −3.72 | 42,901 |
| 21 | 0.50 | 0.61266 | +0.00154 | −5.49 | 42,838 |
| 91 | 0.60 | 0.61672 | +0.00560 | −9.30 | 42,169 |

Monotone all the way down: 91 → 21 was −0.00413 (the largest single gain
of the day), 21 → 7 another −0.00154, 7 → 3 −0.00023 more — the smallest
step measured. `form_scale` was 0.50 at every cadence from 21 days down
(0.60 at 91) under the tour-average prior — fresher ratings need less
volatility; it refits to 0.70 under the own prior. Cost: a refit lands on the first tournament day at or past the due date,
and tournaments start weekly, so the counts are what the logs show — 72
refits at 91 days, 258 at 21, 372 at 14, 633 at 7 (392 s contended; 634 on
the archive refreshed 2026-09-14, 389 s), 708 at 3 (598 s); a 3-day
cadence buys only the mid-week starts, which is why
it costs half again as much as 7 rather than twice, and gains a fifth as
much. The cadence is a model parameter, not a convenience — it
decides how stale every rating is between refits (rule 29).

**Why 3 does not ship (rule 30).** The 3-day gain is real (t 5.4) and
worth 0.0002 nats, and the cadence is also a commitment: the measured
headline assumes the shipped ratings are never staler than the cadence, so
the number only holds if the live ratings are refreshed at that rhythm
(`update.py`). The results mirror has been frozen (969 reconstructed rows since, as of the 2026-09-14 refresh), and
weekly is the cadence the tool can actually keep. Ship the cadence you will
refresh at. Switching is one refit chain: set `refit_days` in
`fitted_params.json` (or `TENNIS_REFIT_DAYS=3`) and rebuild in order.

**Prior mode** (`prior_mode`; 2026-09-14, `tools/knobsweep.py run
prior_mode own`: two walks at the 7-day cadence on the refreshed archive,
cap 0.08, 452 s each; 43,075 common matches, train 20,648 / test 22,427).
What the 270-day rating is shrunk toward by `prior_weight`: `tour`, the
tour average, or `own`, the player's own long-window rating — the 12-year,
1,095-day-half-life fit that already exists for the surface carry-over —
so a player back from a layoff is pulled toward who they were rather than
toward the middle of the tour:

| value | form_scale | test log loss | vs shipped (tour) | t |
|---|---|---|---|---|
| **own** | 0.70 | **0.61059** | **−0.00091** | **+2.92** ← adopted |
| tour | 0.50 | 0.61151 | shipped until 2026-09-14 | |

Adopted, and the chain rebuilt on it (the state of 2026-09-14, superseded
on 2026-09-15 by the age-dependent prior below, which keeps `own` as its
prime and blends it back toward `tour` at the ends of a career).
`form_scale` refits from 0.50 to 0.70 under the own prior.

**Prior weight, re-swept under the own prior** (`prior_weight`, fitted at
150 against the tour-average prior; `TENNIS_PRIOR_MODE=own
tools/knobsweep.py run prior_weight 100 300 600`; the same 43,075 matches):

| value | form_scale | test log loss | vs 150 | t |
|---|---|---|---|---|
| 100 | 0.70 | 0.61057 | −0.00002 | +0.39 |
| **150** | 0.70 | **0.61059** | shipped | |
| 300 | 0.60 | 0.61112 | +0.00053 | −4.71 |
| 600 | 0.60 | 0.61177 | +0.00118 | −5.58 |

100 is within noise; heavier shrinkage costs. **150 stays.** The first run
of this sweep returned four identical walks at 0.61059 — the harness was
reading `PRIOR_W` from `fitted_params` itself, so the override never
reached it (rule 31); fixed, re-run, this is the re-run.

**Prior age — the ramp on the prior** (`prior_age`; 2026-09-15,
`tools/knobsweep.py run prior_age`, fourteen values, one walk each at the
7-day cadence on the refreshed archive; 43,075 common matches, train
20,648 / test 22,427, paired against the shipped (1, 1)). `PRIOR_AGE =
(young, old)` is how much of a player's own **deviation** from the tour
average survives into the prior at each end of a career — `prior = tour +
w(age) · (own − tour)` — ramped by `ratings.age_multiplier` with
`AGE_KNOTS` (22, 28, 34) and **pinned to 1.0 through the prime**, so the
knob only ever moves the ends and `prior_mode` own is exactly (1, 1)
(verified to 0.0 before any walk ran, rule 31). So **(2, 0) reads: double
the player's deviation at 22 and under, their own level at 28, the tour
average at 34 and over** — and no setting turns the prior into `tour` for
everyone. A player with no birthday keeps the own prior, the same fallback
the age-dependent half-life makes. The train column is the rule 32 guard,
not a second measurement:

| value | form_scale | test log loss | vs (1, 1) | t | on train | t |
|---|---|---|---|---|---|---|
| 0, 0 | 0.60 | 0.61142 | +0.00083 | −3.42 | +0.00087 | −4.98 |
| 0.5, 0.5 | 0.60 | 0.61092 | +0.00033 | −2.90 | +0.00034 | −3.24 |
| 0.5, 0 | 0.60 | 0.61052 | −0.00007 | +0.36 | +0.00021 | −1.60 ← **test only, flagged** |
| 1, −1 | 0.60 | 0.60966 | −0.00094 | +2.62 | −0.00026 | +1.08 |
| 1, −0.5 | 0.60 | 0.60964 | −0.00095 | +3.63 | −0.00033 | +1.82 |
| 1, 0.5 | 0.60 | 0.61027 | −0.00032 | +3.06 | −0.00017 | +1.46 |
| 1, 0 | 0.60 | 0.60984 | −0.00075 | +4.31 | −0.00030 | +2.21 |
| **1, 1** | 0.70 | **0.61059** | shipped until 2026-09-15 | | | |
| 1.5, 0 | 0.60 | 0.60938 | −0.00121 | +5.76 | −0.00067 | +3.70 |
| 2, −0.5 | 0.60 | 0.60886 | −0.00174 | +5.20 | −0.00096 | +3.52 |
| **2, 0** | **0.70** | **0.60885** | **−0.00175** | **+6.94** ← adopted | **−0.00096** | **+4.85** |
| 2.5, 0 | 0.70 | 0.60868 | −0.00191 | +5.97 | −0.00116 | +4.41 |
| 3, 0 | 0.70 | 0.60870 | −0.00189 | +4.73 | −0.00122 | +3.68 |
| 4, 0 | 0.85 | 0.60861 | −0.00198 | +3.84 | −0.00107 | +2.47 |

Damping the **old** end helps; damping the **young** end hurts, and the
young end wants **amplification**. Both edges were probed until they
turned over (rule 26): out to 4 on the young side, past zero to −1 on the
old. **Why (2, 0) and not (4, 0)**, which scores 0.00023 better: the loss
flattens from 2 upward while the t falls away (+6.94 → +5.97 → +4.73 →
+3.84) and `form_scale` starts climbing (0.70 at 2, 0.85 at 4) — a rating
layer being compensated by more volatility is not a better rating layer.
The plateau begins at 2, and the smallest change with the highest t ships,
exactly as `carry_cap` did. **Adopted (2, 0)**, and the chain rebuilt on
it (the state this document describes). `form_scale` stays at 0.70, where
the flat own prior had put it.

**The guard (rule 32).** Fourteen values chosen by held-out log loss is
fourteen draws from one test half, so `tools/knobsweep.py compare` now
scores every value on **both** halves and flags a value that wins only on
test. Every value that won on test also won on train, in the same order;
the only **TEST ONLY** row was (0.5, 0), −0.00007 on test at t +0.36 and
+0.00021 on train at t −1.60 — noise, and not a candidate.

**And the honest result (rule 33).** Against the flat own prior on the two
residual caches, 22,759 identical matches (scratchpad `curvepair.py`): the
age-dependent prior is **−0.00181 at t +7.17 on the ratings** and
**+0.00016 at t −0.80 once the eight curves are applied**. It ships for
what the curves do not cover — the market gap, the totals path, a smaller
correction layer, a halved age curve — and the session section above says
why in full.

**`TRAIT_K` / `TRAIT_MIN`** (`resid_prior`'s shrinkage n/(n+K) and its
floor, fewer prior rows than MIN → no read; `tools/traitsweep.py`,
2026-09-14, on the 7-day cache before the refresh — 56,754 player-rows.
Each (K, MIN) re-annotates the cached rows in memory, refits the eight
curves on each fold's train half and scores the shipped antisymmetric
log-odds application at k=1; paired per-match t on 22,697 identical
matches; ~10 s a value, no walk). Cells are vs the shipped (40, 15), t in
brackets:

| K ↓ / MIN → | 5 | 10 | 15 | 25 | 40 |
|---|---|---|---|---|---|
| 10 | +0.00001 (−0.08) | −0.00002 (+0.18) | +0.00001 (−0.12) | +0.00001 (−0.04) | +0.00015 (−0.78) |
| 20 | +0.00005 (−0.37) | +0.00002 (−0.12) | +0.00005 (−0.44) | +0.00001 (−0.06) | +0.00017 (−0.94) |
| **40** | −0.00002 (+0.17) | −0.00007 (+1.07) | **shipped** (0.60431) | −0.00000 (+0.04) | +0.00018 (−1.15) |
| 80 | +0.00007 (−0.44) | +0.00008 (−0.51) | +0.00011 (−0.77) | +0.00012 (−0.72) | +0.00031 (−1.54) |
| 160 | −0.00003 (+0.18) | −0.00005 (+0.30) | +0.00001 (−0.07) | +0.00004 (−0.23) | +0.00023 (−1.08) |
| 320 | +0.00016 (−0.91) | +0.00013 (−0.73) | +0.00015 (−0.86) | +0.00018 (−0.94) | +0.00032 (−1.48) |

Flat. The best cell, (40, 10), is −0.00007 at t +1.07; MIN = 40 costs
+0.0002 .. +0.0003 at t −1 .. −1.5 for every K (a 15-row floor reads
49,533 rows, a 40-row floor 41,434); K = 320 costs +0.00013 .. +0.00032.
**(40, 15) stays.** The last chosen constants of the correction layer are
measured (`trait_k_note`).

Adopted: `refit_days` 7 (via 21 and 14) and `carry_cap` 0.08 on
2026-09-12; `prior_mode` own on 2026-09-14; `prior_mode` age with
`prior_age` (2, 0) on 2026-09-15; everything else stays.
Nothing in the rating or correction layer is now chosen rather than
measured. `MIN_PTS = 1500` is a scoring threshold, not a model parameter.

---

## What happened on 2026-09-11 — item 0, and what it exposed

That day's Next steps item 0 was: `backtest.price_player` and `price.price` had
diverged. Closing that gap meant one derivation and one pricing function,
and the gate that now enforces it found **six** divergences, three of which
nobody had recorded:

| divergence | harness had | CLI had | fixed by |
|---|---|---|---|
| three-stage serve | no | yes | one `serve_probs`; measured; **switched off** |
| in-event rating update | no | yes | one `event_bank` / `event_shift`; harness banks after pricing |
| player news | no | yes | cannot be modelled historically; documented |
| **surface carry-over** | yes (t +4.54) | **no** | `Book.rating` carries the recent shift; worth **0.015** |
| form volatility half-life | 1,095 d on 12 y | 270 d on 10 y | `weights.derive`, one window |
| surface path with one player unsplit | both or neither | mixed | `serve_probs` falls back for both |

**The mechanism.** `weights.derive` is the one derivation (main fit with the
supplement, age-decayed; long-window overall; surface contrast; form
volatility; the stage fits). `weights.build` calls it for `weights.json`;
`backtest._fit_block` calls it at every refit and wraps the result in the
same `Book` the CLI reads. `price.serve_probs` is the one matchup function
(surface → news → event → stages); `price.match_prob` is density + the
recursion. `backtest.walk_forward` prices every historical match through
both, and `python3 backtest.py --gate` derives one block through the harness
as of `weights.json`'s day and asserts every quantity agrees (it does, to
1e-15). It is the sixth gate in `tennis.py gates`.

**Bugs the unification surfaced, all fixed:**

1. **The birthday table depended on which files were loaded last.**
   `fill_ages` rebuilt `BIRTHDAYS` from whatever `load()` had just parsed, and
   the last call won — `weights.build` ended up with the 2013+ *qualifying*
   files' birthdays, the harness with 2005+; a player missing from the table
   silently got the base half-life instead of the age-decayed one. Decayed
   point counts disagreed by hundreds. `load.birthdays()` now derives the
   table once from every row in the archive (26,300 players), cached to
   `data/birthdays.json` keyed on the files' sizes and mtimes.
2. **Rounds inside a tournament are not in file order.** Some seasons of the
   archive list rounds alphabetically — F, QF, R128, R16 … — and
   `tools/inevent.py` / `tools/combo.py` banked matches in file order, so an
   early-round price had the final folded in. The published in-event gain
   (−0.00267) was leak-inflated; re-measured clean it is −0.00130.
   `backtest.records` orders every event by `ROUND_ORDER`.
3. **The stage fits saw different records from the main fit.** Stages were
   fitted on main-tour matches; the overall rating had the supplement; ~2,000
   players rated from Challenger points had no stage rating and
   `stage_serve` priced them at the tour average — +0.0068 nats of damage
   hidden inside the shipped CLI. The supplement rows now carry stage
   counts, the stages fit on the same records, and a missing stage rating
   falls back to the single path.
4. **`tools/agehl.py`'s "(1.0, 1.0) baseline" was the shipped config.** With
   `half_life_fn=None` meaning "what ships", the baseline silently ran
   (0.70, 0.85) and matched itself bit for bit. It now passes an explicit
   global-half-life function.
5. **One refit block took 15 minutes.** The pure-Python estimator needed
   ~3,000 sweeps on a poorly connected early block. `ratings.fit_iterative`
   is now two `numpy.bincount` products per sweep; the loop is kept as
   `fit_iterative_reference` and the estimator gate asserts they agree to
   1e-9. A full walk-forward became **~90 s** at the 91-day cadence (was
   ~6 min per config), which is what made the rest of that session — and
   the constant sweeps of the next — possible. At 21 days a walk is 258
   refits, a few minutes; at the shipped 7 days 633 refits, ~6.5 min
   contended (634 on the archive refreshed 2026-09-14, 389 s).
6. **`price.price` defaulted `stages=True` regardless of the parameter
   file.** Now every switch — stages, carry — defaults to `fitted_params`.

**The three-stage serve, measured in company, does not earn its place.**
Alone, on the single-number model, it was −0.00195 at t +12.32. Inside the
shipped path — surface split, carry-over, in-event update — it costs
**+0.00505 at t −8.54** (`tools/pathsweep.py all`, final configuration at
the 7-day cadence with the age-dependent prior on the refreshed archive;
+0.00315 at t −5.81 with the flat own prior, +0.00209 at t −8.92 with the
tour-average prior, +0.00206 at t −8.65 at 21 days, +0.00200 at t −8.76 at
91). Same pattern as `home_km` against `home` and
`rank_change` against
`age`: a near-substitute for something the surface layer already carries.
It ships off; the code stays as a knob.

**Every knob of the shipped path, measured paired** (`tools/pathsweep.py
all`, final configuration, re-run 2026-09-15 at the 7-day cadence with
the age-dependent prior on the refreshed archive; 43,075 scorable matches,
22,427 test; one walk, six configs, 445 s):

| flip one knob | cost | t | (was, flat own prior) |
|---|---|---|---|
| three-stage serve ON | +0.00505 | −8.54 | +0.00315, t −5.81 |
| in-event update OFF | +0.00170 | −5.60 | +0.00194, t −6.25 |
| both of those flipped | +0.00621 | −9.92 | +0.00446, t −7.81 |
| **surface carry-over OFF** | **+0.01789** | **−14.00** | +0.01584, t −13.29 |
| no surface split at all | +0.00400 | −4.75 | +0.00398, t −4.69 |

The surface carry-over is still the largest layer in the model, and
**every layer costs more to remove than it did**: a better rating layer
makes the structure around it matter more, which is the same reading as
the curve layer shrinking. The in-event update is the one row that moved
the other way — +0.00194 → +0.00170 to switch off — and its weight has not
been re-swept since 2026-09-11. (With the
tour-average prior at 7 days on the archive before the refresh, 22,420
test, 3,711 s contended, the same rows read +0.00209 / +0.00159 / +0.00359
/ +0.01508 / +0.00329; at the 21-day cadence, 22,344 test, +0.00206 /
+0.00164 / +0.00355 / +0.01531 / +0.00314; at 91 days, 22,012 test,
+0.00200 / +0.00170 / +0.00363 / +0.01522 / +0.00257.)

In-event weight sweep (measured 2026-09-11 at (0.70, 0.85), not re-run
after the age change or the cadence change): w=0.5 −0.00048 (t 7.0), w=1
−0.00075 (t 5.3), **w=2 −0.00130 (t 4.9)**, w=4 −0.00093 (t 1.7). Interior.

**Age half-life, re-fitted with the complete birthday table and a real
baseline** (`tools/agehl.py`, nine configs, 40,181 common test matches,
paired vs one global half-life):

| m_young | m_old | vs baseline | t |
|---|---|---|---|
| 0.40 | 0.70 | −0.00163 | +3.86 |
| 0.40 | 0.85 | −0.00161 | +4.11 |
| 0.50 | 0.70 | −0.00163 | +4.75 |
| **0.50** | **0.85** | **−0.00183** | **+6.32** ← adopted, shipped |
| 0.50 | 1.00 | −0.00171 | +6.28 |
| 0.60 | 0.70 | −0.00143 | +5.06 |
| 0.70 | 0.85 | −0.00129 | +7.88 ← previously shipped |
| 0.85 | 1.00 | −0.00060 | +9.09 |
| 1.00 | 1.00 | baseline | |

Head to head against the previously shipped (0.70, 0.85), same 40,181
matches: **(0.50, 0.85) −0.00053 at t +3.95** ← adopted; (0.50, 1.00)
−0.00042 (t 2.84); (0.50, 0.70) −0.00034 (t 1.77); (0.40, 0.70) −0.00034
(t 1.25); (0.40, 0.85) −0.00032 (t 1.27); (0.60, 0.70) −0.00013 (t 0.96).
Interior in both directions: 0.40 is no better than 0.50 at lower t, and
0.70 on the old side is worse than 0.85. The adopted pair prices 42,169
matches instead of 43,514 at the 91-day cadence — a shorter young memory
qualifies fewer players.

**Challenger supplement**, re-measured in the shipped path at MIN_PTS 300
(2026-09-11 at (0.70, 0.85); not re-run since): **−0.00450 at t +4.48**.

**Curves**, refitted on residuals from the shipped path with (0.50, 0.85):
a seventh curve, `resid_prior`, was adopted. The set of seven was worth
**−0.00941** at k=1, 4 folds of 4, on the 91-day cache (the six-curve set
on the same cache: −0.00775). The eight-curve set is −0.00807 on the
21-day cache, −0.00735 on the 7-day cache with the tour-average prior,
−0.00738 with the flat own prior and **−0.00541** on the shipped 7-day
cache with the age-dependent prior on the refreshed
archive (see the curves section); the magnitude stays at k=1 on all of
them.

---

## How it works

```
data/sackmann/atp/*.csv + data/manual_matches.csv (tools/ta/: results, seeds, entry codes)
        │  load.py            parse + arithmetic validation; birthdays() once
        │
   weights.derive(records, asof, supplement)      ONE derivation
        │   long-window overall (12 y) — since 2026-09-14 the prior the main fit shrinks toward,
        │                                 since 2026-09-15 blended toward the tour average by age
        │   main fit (+ qual/Challenger, age-decayed)  ratings.fit_iterative(priors=…)
        │   surface contrast, form volatility, stages
        ├── weights.build  → weights.json           ← what the CLI reads
        └── backtest._fit_block → Book(weights=…)    ← every refit
        │
   price.serve_probs(book, a, b, surface, ev, nws)  ONE matchup function
   price.match_prob(pa, pb, bo, fa, fb, dens)       density + recursion
        ├── price.price  → curves → calibration      the CLI, app, simulator
        └── backtest.walk_forward → price_player     the harness, m4, curves
```

### File map

| file | role |
|---|---|
| `tennis.py` | front door — `app`, `price`, `sim`, `find`, `weights`, `workload`, `vars`, `update`, `fit`, `backtest`, `gates` |
| `price.py` | `Book`, `serve_probs`, `match_prob`, `event_bank`/`event_shift`, `price`, the prompt; `market_view` (devigs a bookmaker's pair of odds proportionally, the same as `tools/odds/m4.py` — the app's odds check, never in the price) |
| `weights.py` | **`derive` — the one derivation** (the long fit runs first and, with `prior_mode` own or age, is what the main fit is shrunk toward); `HALF_LIFE` / `PRIOR_WEIGHT` / `PRIOR_MODE` / `PRIOR_AGE`, the one source of the rating-layer constants (`TENNIS_PRIOR_MODE` / `TENNIS_PRIOR_WEIGHT` / `TENNIS_PRIOR_AGE` override them); the prior itself is one function — `tour`, `own`, or `age`, which ramps each player's deviation from the tour average by `ratings.age_multiplier(age, *PRIOR_AGE)` and so is exactly `own` at (1, 1); `build` writes weights.json; record layout `R_*`, `rich`, `window` |
| `backtest.py` | walk-forward harness through the shipped path; `config()` knobs; `--gate`; writes `fitted_params.json` (since 2026-09-12 late also `test_matches`, `elo_log_loss`; since 2026-09-14 `prior_mode`; since 2026-09-15 `prior_age`); takes `HALF_LIFE` and `PRIOR_W` from `weights.py` since 2026-09-14 — it used to read them from `fitted_params` itself, which is how the first `prior_weight` sweep came back flat (rule 31). Since 2026-09-16 `walk_forward` takes an optional **`book_out`** dict and sets it to `{"book": book}` before every yield, so a caller can read the block a match was priced from — the service points behind each rating **as of that match** — which is what `confidence.py` needs to fit the band on the inputs a live price feeds it |
| `ratings.py` | the estimator (numpy) + reference loop + gates; both fits take `priors={pid: (serve, ret)}` since 2026-09-14 and the vectorised-equals-reference gate has a priors case; `age_multiplier` / `AGE_KNOTS` (22, 28, 34) is the one age ramp in the project — the rating half-life and, since 2026-09-15, the prior's blend both read it (rule 19) |
| `load.py` | CSV parsing, validation, `birthdays()`, `qc_records` (rich rows) |
| `news.py` | injury and player news: prompt, schema, weights, applied log |
| `app.py`, `web/` | browser view; computes nothing of its own. Rebuilt 2026-09-12 late around "type a name, Enter, twice": Enter fills the next empty slot and a typed name searches everyone; a tournament name auto-fills surface and best-of from the archive (`State._venue_hints`); bookmaker odds A/B (`price.market_view`, compared with the call, never used in it); the match in the address bar (`#a=&b=&surface=&best_of=&at=&entry_a=&entry_b=&odds_a=&odds_b=`); phone layout ≤ 760px; a "the model" tab that reads `fitted_params.json` and `data/market_check.json`. `.claude/launch.json` starts it for the preview pane. Since 2026-09-14 it names entry codes (`ENTRY_NAMES` in `web/app.js`: "entered as qualifier"), read from the archive's rows at the event or from the selects |
| `simulate.py` | point-by-point simulator, totals |
| `features.py` | workload / curve inputs; `live_workload` for a price today (reads `data/player_traits.json` for `resid_prior`; takes `entry` from the flag, the app, or an archive row at the event — which the reconstructed feed carries since 2026-09-14, so only a player's first match at an event needs the flag) |
| `data/player_traits.json` | per-player traits (384 players), written by `tools/curves.py write`: `resid_prior` (the live source of the seventh curve's input) plus `resid_365` and `surf`, supplied live but rejected as curves |
| `data/market_check.json` | the closing-line check per season (2025, 2024: n, model, closing, gap, buckets by how far model and closing differ), written by `tools/odds/m4.py`, read by the app's model tab |
| `confidence.py` | how much to trust one price — **rewritten 2026-09-16**: `features` / `score` / `BANDS` (three levels) / `MEASURED_DEFICIT` / `fit`, fitted against **surprise** on the same inputs a live price feeds it (rule 19), with the deficit kept as the check. `fit` writes `confidence_model.json`, which since 2026-09-16 also stores the **surprise** per band and the deficits alongside the log loss and accuracy |
| `tools/pathsweep.py` | **one knob of the shipped path, paired, in one walk** (`all`, `event_w`, `carry`) |
| `tools/knobsweep.py` | **a chosen constant, one walk per value in a subprocess, paired on the intersection** (`run <knob> <values…>`, `compare <knob>`; knobs `surface_hl`, `long_years`, `carry_cap`, `refit_days`, `age_knots`, since 2026-09-14 `prior_mode`, `prior_weight`, and since 2026-09-15 `prior_age`; cache in `tools/_knobsweep/`). Since 2026-09-15 `compare` always reports **both halves** and tags a value that wins on test but not on train `TEST ONLY -- flag` (rule 32); the shipped baseline is read from the modules, so an adopted value is the baseline of the next sweep |
| `tools/traitsweep.py` | **`TRAIT_K` × `TRAIT_MIN` on the residual cache, paired, no walk** (new 2026-09-14; the grid, or explicit `K,MIN` pairs; re-annotates the cached rows, refits the eight curves per fold, scores the shipped application at k=1; ~10 s a value) |
| `tools/refit_chain.sh` | the whole refit after a model change, in dependency order — `weights.py --rebuild`, `backtest.py --gate`, `backtest.py`, `pathsweep.py all`, `curves.py build` / `loo` / `antisym` / `fit` / `write`, `confidence.py fit`, `m4.py 2025` / `2024`, `tennis.py gates` — logged to `$1`, ending `ALL GATES PASS` / `== DONE`; ~25 min at 7 days uncontended (`chain_age.log`, 2026-09-15, is the current one; `chain_own.log` ran 22:52 → 23:18 the day before; the path sweep is the slow step, 445 s in the latest chain and 383 s in the one before, and the chain takes ~1.5 h when other walks run alongside). In the repo since 2026-09-13 |
| `tools/agehl.py` | age half-life configs, paired |
| `tools/qcthin.py` | the supplement at the thin-player threshold |
| `tools/curves.py` | residual cache, curve fits, `antisym`, `add` (forward selection onto the shipped set), `loo`, `reliability` (split-half, rule 17), `write` (curves + `data/player_traits.json`); `--k=` on `loo`/`write`. Since 2026-09-16 `build` reads the pricing block through `walk_forward(book_out=…)` and stores **`den`** (the service points behind that player's rating as of that match) and **`form_sd`** on every cache row — before that the cache had neither, and the confidence band was fitted on proxies for both |
| `tools/odds/` | odds join, `m4.py` vs closing line (writes `data/market_check.json`), `disagree.py`. Since 2026-09-16 the `disagree.py` cache carries **match-time** service points (`den_w` / `den_l`, read from `walk_forward(book_out=…)`) instead of reading them out of the shipped `weights.json` — today's numbers for a two-year-old match, which had been putting well-measured players in the thin bucket; its **`bands`** command (added 2026-09-15, run by the chain) iterates the shipped `confidence.BANDS` and re-measures `MEASURED_DEFICIT` |
| `update.py` | the weekly refresh (rule 30): the mirror (dead since 2026-05-25 — a no-op), results from tennisabstract via `tools/ta/`, the weather cache, provenance re-verified (`VERIFY PASS`) |
| `tools/ta/` | `refresh.py` fetches the player pages and rebuilds `data/manual_matches.csv` (`--rebuild-only` re-emits from the cache); `build.py` parses the result cells — since 2026-09-14 `prefix_of` keeps the draw prefix (digits → seed, letters → entry code) and `split_result_full` carries both sides'; `emit.py` fills `winner_seed` / `winner_entry` / `loser_seed` / `loser_entry` |
| `tools/inevent.py`, `tools/combo.py`, `tools/twostage.py` | the single-number-model tools; superseded by `pathsweep`, kept with their caveats in the docstrings |
| `data_plan.md` | the lab notebook |

---

## Rules — all learned the hard way

1. **Score every config on the SAME matches.** `tools/pathsweep.py`, one
   walk, many configs, paired.
2. **Never trust an unconverged fit.** `walk_forward` counts unconverged
   blocks and prints them.
3. **A miscalibrated model punishes real improvements.**
4. **Per-player values are ALWAYS shrunk.**
5. **Don't measure an effect on the data that fitted the ratings.**
6. **Derive shrinkage from measured reliability, not an analytic formula.**
7. **Write back what was actually used.** The backtest writes every switch
   it ran with, and keeps every `*_note`.
8. **Long-window quantities must not replace short-window ones.** The
   surface carry-over is this rule made numeric: 0.015 nats.
9. **ORIENTATION LEAKS.** Adjustments must be antisymmetric.
10. **An additive probability adjustment can leave (0,1).** Log-odds.
11. **Measure how an adjustment is APPLIED, not only what it contains.**
12. **A single-split score cannot adopt a curve.** Leave-one-out decides.
13. **The intersection you score on is itself a choice.** Ask who the change
    is for before choosing MIN_PTS.
14. **The archive dates a match by its TOURNAMENT.** Use `ROUND_ORDER`.
15. **A match-level covariate cancels to EXACTLY zero.**
16. **Raw log loss cannot tell "the model is bad here" from "this is hard
    for anyone".**
17. **Reliability first, feature second.**
18. **Never rebind a module attribute other modules import.** Mutate in place.
19. **Two derivations of one quantity WILL drift.** Now there is one
    derivation and one matchup function, and a gate. When you add a layer,
    add it to `serve_probs` and nowhere else.
20. **A `pgrep` wait-loop matches itself.** Wait on a file.
21. **Module state that depends on call order is a bug waiting for a second
    caller.** `BIRTHDAYS` was rebuilt by every `load()`; the two callers got
    two tables. Derive such tables once, from everything, and cache them.
22. **File order is not chronological order.** Rounds are alphabetical in
    several seasons. Anything that "banks after pricing" must sort by round.
23. **A layer measured ALONE is not measured.** The three-stage serve was
    +12 t alone and −8.5 t in company (`tools/pathsweep.py all`, final
    configuration at the 7-day cadence with the age-dependent prior on the
    refreshed archive: +0.00505 at t −8.54; the ladder rung is +0.00615 at
    t −8.85; with the flat own prior +0.00315 at t −5.81 / rung +0.00418
    at t −6.41;
    with the tour-average prior at 7 days +0.00209 at t −8.92 / rung
    +0.00229 at t −7.95; at 21 days +0.00206 at t −8.65 / t −7.56, at 91
    days +0.00200 at t −8.76 / t −7.32). The −6.5 quoted
    earlier was the 2026-09-11 measurement at (0.70, 0.85) on 22,736 test
    matches (+0.00137, t −6.50), superseded by the age change.
    Measure every structural change with the other layers present, i.e.
    `pathsweep`, before shipping it.
24. **Two fits composed as a delta must see the same records.** `stages +
    (single − base)` isolates the decomposition only if both fits had the
    supplement. A missing rating must fall back, never default to the mean.
25. **A "baseline" that reads the shipped defaults is not a baseline.** Pass
    the null explicitly and check the baseline differs from the candidate.
26. **A grid optimum on the edge is a flag, not a result.** `form_scale`
    landed on 0.50 at the edge; the widened grid put it at 0.60, interior.
27. **A candidate pool is not a forward selection.** Leave-one-out over
    overlapping candidates makes every one look harmful; add each alone to
    the shipped set (`tools/curves.py add`), then leave-one-out the result.
28. **A curve a live price cannot evaluate must not ship.** Entry type
    waited a day for `--entry-a/-b` and the app control; the workload gate
    is what enforces this (live pricing must supply all eight curve inputs).
29. **A walk-forward's refit cadence is a model parameter, not a
    convenience** — it decides how stale every rating is between refits.
    91 → 21 days was −0.00413 at t +7.06, the largest single gain of
    2026-09-12, sitting in a constant nobody had swept; 21 → 14 → 7 added
    −0.00154 more, one paired step at a time.
30. **The refit cadence is also a commitment.** The measured number
    assumes the shipped ratings are never staler than the cadence, so ship
    the cadence you will actually refresh at (`update.py`). 3 days is
    −0.00023 at t +5.38 against 7 and does not ship: with the results
    mirror frozen, weekly is what the tool can keep.
31. **A sweep whose values all score IDENTICALLY is a broken knob, not a
    flat one.** The first `prior_weight` sweep returned four walks at the
    same 0.61059 to five places: `backtest.py` was reading the constant
    from `fitted_params` itself, so the `TENNIS_PRIOR_WEIGHT` override
    moved the live derivation and not the harness. Check that an override
    reaches the code that fits before reading a sweep as flat.
32. **A wide sweep is a wide set of chances to be lucky.** `prior_age` was
    fourteen values chosen by held-out log loss, which is fourteen draws
    from the same test half. The guard is cheap and now automatic:
    `tools/knobsweep.py compare` scores every value on BOTH halves, and a
    value that wins on test must also win on train, in the same order. A
    "TEST ONLY" row is a flag, not a result.
33. **A fitted corrector hides an improvement underneath it.** The
    age-dependent prior is −0.00181 at t +7.17 on the ratings and
    **+0.00016 at t −0.80 once the eight curves are applied**: the curves
    were already correcting what it fixes. Measure a rating-layer change
    both ways before claiming it, and say which number the claim is. It
    still ships — the market gap and the totals path see a gain the curves
    hide, and a model that needs less correction is the point — but "the
    price moved" would have been false.

---

## Tested and DO NOT work

- **Head-to-head** (`h2h_w` → 0), **opponent style** (`style_w` → 0). Both
  measured at zero for the life of the project and no longer swept: neither
  is in the pricing path, and the harness now only measures what can ship.
- **The three-stage serve, in company.** −0.00195 alone, **+0.00505** in
  the shipped path (t −8.54 at 7 days with the age-dependent prior;
  +0.00315 at t −5.81 with the flat own prior; +0.00209 at t −8.92
  with the tour-average prior; +0.00206 at t −8.65 at 21). Off. See above.
- **Logistic calibration.** Measured slope **1.009** this run (7 days,
  age-dependent prior, refreshed archive) and **off** by its own test:
  applying it costs +0.00007 at t −3.09 (0.60885 → 0.60891). The 7-day run
  with the flat own prior measured 1.007, +0.00007 at t −3.68 (0.61059 →
  0.61066), off; the 7-day run with the
  tour-average prior measured 1.012, +0.00007 at t −2.32 (0.61140 →
  0.61147), off; the 21-day run's 0.997 was identity to three decimals
  (−0.00002 at t +2.43), on and doing nothing; the 91-day run's 1.012
  (2026-09-11) made the test loss worse (0.61720 → 0.61728, t −2.87) and
  was off. It follows the model; leave the switch alone.
- **Height, ranking.** Inside the ratings. Rank *trend* is carried by `age`.
- **Raw wins banked at an event** (`event_matches`). Margin, not count.
- **Injury proxies** — retirements, walkovers, comebacks, layoff length. All
  ≈0 out of sample. The market knows something the log does not; `news.py`
  is the channel for it.
- **Travel, elevation change, surface switch.** ≈0.
- **`home_km`.** Cancels exactly against `home`.
- **Recalibration of any kind.** Closes 2% of the market gap.
- **Substituting the long-window surface rating for the current one.** The
  CLI did this until 2026-09-11; it costs 0.015 nats.

---

## What DOES work: nonlinear curves

`fitted_curves.json` holds **shapes, not weights**, fitted on walk-forward
residuals of the shipped path (`tools/residuals.json`, rebuilt 2026-09-15
at the 7-day cadence with the age-dependent prior on the refreshed
archive, carry cap 0.08: **56,910 player-rows = 28,455 matches**, priced
with (0.50, 0.85)), shrunk by n/(n+400), applied
antisymmetrically in log-odds as `4·k·(adj_a − adj_b)` with k=1. **Eight
curves** (the eighth, `entry`, adopted 2026-09-12; the seventh,
`resid_prior`, 2026-09-11). "Alone" is a single split on the final cache;
"cost of dropping" is leave-one-out from the eight-set, 4 folds; the table
is ordered by what it costs to drop, and the order has changed — `entry`
is now the largest and `age`, which the prior took over from, has halved:

| covariate | alone | **cost of dropping** | what it is |
|---|---|---|---|
| **`entry`** | −0.00045 | **+0.00100** | how the player got into the draw: qualifiers beat their price; doubled once the reconstructed rows carried codes (2026-09-14) |
| **`age`** | −0.00060 | **+0.00091** | a decaying rating lags a rising player; was −0.00148 / +0.00227 under the flat own prior, and the age-dependent prior took half of it |
| `event_gwp` | −0.00083 | +0.00090 | games-won share so far at this event |
| `resid_prior` | −0.00045 | +0.00088 | the player's own prior residual: do they beat the point model? |
| `matches_28d` | −0.00040 | +0.00083 | rust: cold players underperform |
| `form_spw` | −0.00026 | +0.00026 | 28d serve level vs their own 365d |
| `event_sets_lost` | −0.00017 | +0.00022 | |
| `home` | −0.00010 | +0.00015 | playing in your own country |

Set of eight: **−0.00541 at k=1, 4 folds of 4** (no curves 0.60883 →
0.60341). It was **−0.00738** on the 7-day cache with the flat own prior
(no curves 0.61064 → 0.60326; leave-one-out there: age +0.00227, entry
+0.00105, resid_prior +0.00093, event_gwp +0.00091, matches_28d +0.00085,
form_spw +0.00027, event_sets_lost +0.00021, home +0.00015; alone, in the
same order: −0.00148, −0.00040, −0.00066, −0.00080, −0.00050, −0.00031,
−0.00019, −0.00009). On the 7-day cache with the tour-average prior (56,754 rows,
2026-09-12 late) the same eight were worth −0.00735 (no curves 0.61161 →
0.60426; leave-one-out there: age +0.00183, resid_prior +0.00152,
matches_28d +0.00118, event_gwp +0.00086, entry +0.00049, form_spw
+0.00029, event_sets_lost +0.00019, home +0.00011; alone, in the same
order: −0.00127, −0.00091, −0.00077, −0.00074, −0.00014, −0.00031,
−0.00019, −0.00006); on the 21-day cache −0.00807
(leave-one-out there: age +0.00185, resid_prior +0.00153, matches_28d
+0.00144, event_gwp +0.00087, entry +0.00051, form_spw +0.00048,
event_sets_lost +0.00018, home +0.00013; alone, in the same order:
−0.00126, −0.00086, −0.00092, −0.00077, −0.00014, −0.00055, −0.00019,
−0.00007), and on the 91-day cache −0.00999 (leave-one-out: age +0.00250,
resid_prior +0.00178, matches_28d +0.00167, event_gwp +0.00091, form_spw
+0.00075, entry +0.00058, event_sets_lost +0.00016, home +0.00016; the
seven without `entry`, −0.00941). A better rating layer absorbs part of
what the curves corrected — the expected direction, and the same thing the
age half-life did in 2026-09-09 and the refit cadence did in 2026-09-12.
The flat own prior left the total where it was (−0.00735 → −0.00738) and
moved it between curves: `entry`'s cost of dropping doubled once the
reconstructed rows carried codes, and `age`'s grew because a declining
player was shrunk toward a better past. **The age-dependent prior then
took a quarter of the whole layer** (−0.00738 → −0.00541), and the biggest
single fall is `age` (+0.00227 → +0.00091 to drop): the prior now does
what the curve was doing. Every curve still earns its place — the
smallest, `home`, is +0.00015 to drop — and every one of the eight
improves its own single split.

**Magnitude — k stays 1.** The `antisym` grid on the final (7-day,
age-dependent prior) cache: x2 (k=1) −0.00541, x2.5 (k=1.25) −0.00564, x3
(k=1.5) −0.00543, x4 (k=2) −0.00372 and only 3 folds of 4. Every fold's
train half picked x3, and that choice scores 0.60340 on test against
0.60341 at the shipped k=1 — **one hundred-thousandth of a nat, which does
not buy a new tunable** — so k stays
1.0 and "no new tunable" holds; every earlier cache said the same. The
7-day cache with the flat own prior: k=1 −0.00738, k=1.25 −0.00763, k=1.5
−0.00727, k=2 −0.00475, train-chosen 0.60327 against 0.60326; the 7-day
cache with the tour-average prior: x2.5 −0.00752, x3 −0.00706, x4 −0.00427,
train-chosen 0.60440 against 0.60426; the 21-day cache: x2.5 −0.00818, x3
−0.00756, x4 −0.00421, train-chosen 0.60552 against 0.60522; and the
91-day cache: x2.5 −0.01014, x3 −0.00940, x4 −0.00536, train-chosen
0.60787 against 0.60771. On the six-curve set the train
halves had preferred k=1.5; the seventh curve absorbed what the larger
magnitude was compensating for. The grid's "x2" column is the shipped k=1
(its label used to say x1; fixed).

Rejected, each because it makes the set worse or adds nothing:
`event_matches`, `bp_form`, `event_opp_rank`, `career_matches`,
`career_pts`, `home_km`, `rank_change`, `peak_gap`, `vs_quality`,
`opp_log_rank`, `opp_faced_mean`, `round_order`, `run_vs_price`; on
2026-09-11 `rank_gap`, `log_rank`, `seeded`, `bo5_resid_prior`; and on
2026-09-12 **`resid_365`** (the player's residual over the last 365 days
only, K=20, min 8: −0.00131 alone, **+0.00092** when added to the seven)
and **`resid_surface`** (the residual on this row's surface only: −0.00038
alone, **+0.00119** added) — both substitutes for `resid_prior`, both still
computed into `data/player_traits.json` (`resid_365`, `surf`) and supplied
live so they can be re-measured. The 2026-09-11 candidates are in their own
subsection below.

### `resid_prior` — does this player beat the point model?

**Definition.** The player's own mean walk-forward residual (y − p) over
their *prior* cached rows, shrunk by n/(n+40); no value until 15 prior rows
(both constants swept 2026-09-14 by `tools/traitsweep.py` and flat — the
constants section); rows of the same day never see each other. It asks whether the point model
systematically under- or over-prices this player, and carries the answer
forward.

**Reliability first (rule 17).** Split-half on the 2026-09-11 cache: all
matches r +0.243, full-sample 0.391, 286 players with 40+ rows. Best-of-five
only: r +0.083 / 0.153 (97 players) — too weak to carry a curve of its own,
which is why `bo5_resid_prior` was measured and rejected (below).

**Curve shape.** On the 7-day cache with the age-dependent prior, shrunk,
`fitted_curves.json` carries **−0.028** (bucket below −0.04) to **+0.024**
(above +0.04), monotone apart from a flat middle (the same cache with the
flat own prior read −0.033 to +0.028; with the
tour-average prior −0.032 to +0.035; the 21-day cache −0.035 to
+0.036; the 91-day cache −0.039 to +0.036).

**Live source.** Live prices read the trait from `data/player_traits.json`
(384 players, written by `tools/curves.py write`); `features.live_workload`
supplies it, and the workload gate asserts that live pricing supplies all
eight curve inputs.

**Extremes (shrunk trait, 21-day cache; not re-listed at 7 days — the
current values are in `data/player_traits.json`).** Flavio Cobolli +0.116 (n 173),
Learner Tien +0.108 (101), Alexander Bublik +0.107 (370), Daniel Merida
Aguilar +0.098 (25); Hugo Dellien −0.133 (89), Rogerio Dutra Silva −0.121
(60), Facundo Bagnis −0.113 (117), Blaz Kavcic −0.109 (24).

### `entry` — how the player got into the draw (adopted 2026-09-12)

**Definition.** The archive's entry code for the player at this event: main
draw, `Q` (qualifier), `WC` (wild card), `LL` (lucky loser), `PR` (protected
ranking, back from injury), `SE` (special exempt). It is the one curve input
that is a fact about the draw rather than about the player's history.

**Buckets (shrunk, 7-day cache, age-dependent prior, refreshed archive).**
Main draw −0.005 (n 46,743), Q **+0.036** (5,740), WC +0.005 (2,582), LL
−0.009 (1,218), PR +0.006 (369, thin), SE −0.001 (189), other −0.005 (69).
Qualifiers still beat their price by 3.6 points (3.7 under the flat own
prior, 2.3 before that): the prior shrinks a qualifier toward a thin, low
history and the curve corrects it. (On the 7-day cache with the flat own
prior: main −0.005 on the same n, Q +0.037, WC +0.004, LL −0.009, PR
+0.000, SE −0.001; on the 7-day cache
with the tour-average prior: main −0.002 on n 46,813, Q +0.023 (5,619), WC
−0.004 (2,526), LL −0.018 (1,182) — lucky losers missed by 1.8 — PR +0.005
(362, thin), SE −0.004 (186); on the 21-day cache: main −0.002 on n 46,715,
Q +0.023 (5,588), WC −0.003 (2,497), LL −0.020 (1,177), PR +0.005 (354,
thin), SE +0.003 (186); on the 91-day cache: main −0.003, Q +0.020 on n
2,825, WC +0.011, LL −0.011, PR −0.003 (thin), SE +0.004.)

**Measured.** Forward selection onto the seven: **−0.00058** (adds);
leave-one-out on the eight: +0.00058 to drop; −0.00013 alone — all on the
91-day cache. On the 21-day cache it costs +0.00051 to drop; on the 7-day
cache with the tour-average prior +0.00049 to drop, −0.00014 alone; on the
7-day cache with the flat own prior, where the reconstructed rows carry
codes, +0.00105 to drop, −0.00040 alone; and on the shipped 7-day cache
with the age-dependent prior **+0.00100** to drop, −0.00045 alone — **the
largest of the eight**, now that the prior has taken most of `age`.

**Why it needs a flag, and since 2026-09-14 mostly does not.** Until
2026-09-14 the reconstructed results feed carried no entry column (847 rows,
0 with a code), so a live price could not learn it from the data at all;
that is why it was measured and not adopted on 2026-09-11 (rule 28), and
why it shipped with a way to say it. Tennis Abstract in fact prints every
player's draw prefix in the result cell — "(10)Jacquet", "(Q)Jacquet",
"(WC)Gabriel Diallo [CAN]", "(LL)", "(Alt)" — exactly as the archive
records it, and `tools/ta/build.py` had been stripping it. It now reads it
(`prefix_of`: digits → seed, letters → entry code), carries both sides'
prefixes through `split_result_full`, and `emit.py` fills
`winner_seed` / `winner_entry` / `loser_seed` / `loser_entry` (a player's own
page first, else what the opponent's page printed). Re-emitted: 341 of 969
reconstructed rows carry a code on at least one side, 579 a seed;
`load.py` reads them unchanged and `features.live_workload` returns the code
for the 2026 US Open qualifiers from their rows at the event. So the flag is
needed only for a player's **first** match at an event — the draw is not in
the archive until it is played.

**Live plumbing.** `tennis.py price A B --entry-a Q` / `--entry-b WC`
(choices `main`, `Q`, `WC`, `LL`, `PR`, `SE`); in the prompt `entry a Q`,
`entry b WC`, `entry off` (clears both); in the app two selects, "A entered
as" / "B entered as", which swap with the players; and when an archive row
at the event already carries the player's code, `features.live_workload`
takes it from there. Otherwise the entry is **unknown and no adjustment is
made** — it is never guessed as "main draw" — and the price's report line
says so (`entry Q` / `entry unknown`).

### Candidates measured and rejected (2026-09-11)

Forward selection onto the six shipped curves (the 2026-09-11 cache,
`tools/curves.py add <candidate>`, each candidate added alone to the
shipped set):

| candidate | added to the six | verdict |
|---|---|---|
| **`resid_prior`** | **−0.00166** | adds — **adopted** |
| `entry` | −0.00047 | adds; could not be evaluated live that day — **adopted 2026-09-12** once the flag existed (its subsection above) |
| `log_rank` | −0.00012 | nothing worth a stale live input |
| `rank_gap` | +0.00077 | hurts |
| `seeded` | +0.00035 | hurts |
| `bo5_resid_prior` | +0.00007 | hurts |

Single-split "alone" scores on the old cache (57,404 rows), for the record:
`rank_gap` −0.00080, `log_rank` −0.00036, `seeded` −0.00032, `entry`
−0.00014 (Q +0.020 on n 2,825; WC +0.011; LL −0.011; PR — protected
ranking, back from injury — −0.003, thin; SE +0.004), `bo5_resid_prior` −0.00037,
`bo_diff_prior` +0.00005, `elo_vs_model` +0.00006 (a perfectly
antisymmetric ±0.022 curve that still hurts out of sample), `opp_lefty`
+0.00008.

**The pool trap.** Leave-one-out over the six shipped curves *plus* all six
candidates put the set at 0.61400 against 0.60912 for the six alone — 0.005
*worse* — and every ranking-shaped candidate looked "harmful":
near-substitutes cancelling. A candidate pool is not a forward selection: add
each alone to the shipped set, then leave-one-out the result (rule 27).

**Entry type.** Real (−0.00047 in company that day) and not adopted then,
because a live price could not know it (rule 28). The flag, the prompt
command and the app control landed on 2026-09-12 and it is the eighth curve
— see its subsection above.

**Plumbing that stayed.** `load.Match` parses winner/loser entry, seed and
hand; `features.build` emits `entry`, `seeded`, `log_rank`, `rank_gap`,
`opp_lefty`; `live_workload` supplies `log_rank`, `resid_prior`,
`bo5_resid_prior` and, since 2026-09-12, `entry`, `resid_365` and the
per-surface residual; `price.curve_adjustment` derives `rank_gap`.
`TENNIS_EXTRA=1` re-measures the rejected opponent-calibre covariates
(`features.build` ~2 min without it, ~15 min with).

### `age` — halved by the prior it prompted

Bucket residuals on the 7-day cache with the age-dependent prior, shrunk,
as written to `fitted_curves.json` `age`: under 21 **+0.036** (n 3,736),
21–24 +0.019 (9,613), 24–27 +0.005 (13,864), 27–30 −0.009 (14,196), 30–33
−0.016 (8,744), 33+ **−0.019** (6,757). Monotone. Youngest minus oldest is
**+0.056**, from **+0.085** on the same cache with the flat own prior
(+0.050 (3,736), +0.030 (9,613), +0.008 (13,864), −0.011 (14,196), −0.024
(8,744), −0.035 (6,757)) — and it was +0.075 on the 7-day cache with the
tour-average prior
(+0.047 (3,730), +0.029 (9,576), +0.006 (13,831), −0.012 (14,146), −0.021
(8,720), −0.028 (6,751)), +0.078 on the 21-day cache (+0.049 (3,709),
+0.029 (9,520), +0.006 (13,798), −0.012 (14,120), −0.022 (8,705), −0.028
(6,730)), +0.097 on the 91-day cache and +0.123 before the age half-life.
The age-dependent half-life ((0.50, 0.85)) removed part of it, fresher
ratings removed more, the flat own prior put 0.010 of it back — a
declining player was shrunk toward a better past — and **the
age-dependent prior has now taken a third of what was left**: the prior
absorbs what the curve was correcting, which is the same thing the age
half-life did on 2026-09-09 and the refit cadence did on 2026-09-12. The
cost of dropping `age` fell with it, +0.00227 → **+0.00091**, and `entry`
is now the largest curve in the layer. The curve keeps the rest; it has
not been rejected, and every one of the eight still earns its place.

### Player news — the channel for what the log cannot see

`tennis.py news --prompt "Name"` / `--add report.json` / `news`. Rebuilt
2026-09-11 around **three levers, each in its own unit**: *level* (points
of serve and return rate the problem costs, entering where the ratings do),
*uncertainty* (a multiplier on the player's form_sd) and *retirement risk*
(folded in last; a retirement is a loss). The prompt hands the assistant
the model's sensitivities — 1 point of serve rate ≈ 4.4 win-probability
points at a coin-flip bo3, 5.2 at bo5 — and asks for an `impact` block in
those units. A report without one falls back to severity anchors solved to
move a reference match by exactly 2/6/13 points. The old design scaled the
level by the player's form_sd, which mixed the epistemic lever into the
physical one. Still a **prior, not a fit**; every application is logged to
`data/news_applied.jsonl`; `available: false` refuses to price; it is the
one layer the harness cannot model because no historical archive exists.

### Confidence bands — re-derived 2026-09-16

**What the band is for**, and it is the only question it answers: *how far
to trust this particular price*. It is not a probability that the pick is
right — a 60% favourite in a GOOD band is still a 60% favourite; the band
says the 60% is trustworthy.

**What it was fitted on until today was not what a live price computes.**
`confidence.fit` read the residual cache, which carried no service-point
count, so it **substituted a recent-match count** for "how well measured is
this player" and **pinned the volatility term to the constant 1**. The
resulting score could not reach its own top band: HIGH was unreachable, `n
= 0` in `confidence_model.json`. That is rule 19 one level below where it
was written — the band being measured was not the band that ships. The same
bug sat one level down in `tools/odds/disagree.py`, whose cache read
service points out of the shipped `weights.json` — today's numbers for a
match played two years ago — which put well-measured players in the thin
bucket. Both caches now carry their real inputs and were rebuilt before
anything was fitted (see the 2026-09-16 section).

**The target, decided before anything was fitted: SURPRISE**, the loss
minus the entropy of the model's own price, `−log p(outcome) − H(p)`. Zero
when the model is calibrated at whatever confidence it chose, positive when
it was more confident than it deserved. **Raw log loss cannot be the
target** — rule 16, a coin flip scores badly for everyone. **The market
deficit cannot be either**: it is a difference between two models and the
band describes only one of them, which is exactly how the old ordering
broke. So the deficit is kept as the out-of-sample **check**, not the
target. Surprise has one blind spot, stated plainly: **it does not punish
under-confidence.**

**What survived, measured on the held-out half:**

| term | measured | verdict |
|---|---|---|
| `comeback` | +0.0053 / +0.0185 / +0.0304 for none / one / both | **kept** — the heaviest term, and now the COUNT rather than a flag |
| `cold` | +0.0007 / +0.0053 / +0.0102 for 4+ / 2–3 / 0–1 matches in 28 days on the thinner side | **kept** — weak, monotone |
| `thin` | above the harness's 1,500-point floor it does not sort: +0.0120 (best measured), −0.0016, +0.0134 | **DROPPED** |
| `best_of` | −0.0212 surprise over five sets against +0.0112 over three | **DROPPED from the band** — a calibration error to fix in the model, not a trust level to report; see below |
| `form_sd` | sign backwards: +0.0248 at .030–.040 against −0.0004 at .055+ | **DROPPED** — steady players carry MORE surprise, which is the model's own volatility term already working inside the price, not a signal about it |

`thin` was also measured against a scale the model no longer has: its
thresholds (6,000 / 3,000 / 1,000) predate the current rating layer, and
the **thinner** of two players now runs 1,501 to 6,978 with a 99th
percentile of 5,934, so "well measured" almost never fired. That is the
second reason HIGH was unreachable. What remains in its place is **not a
fitted claim but a floor**: below 1,500 points the harness never scores a
match, so a live price there gets +2 on the score and is labelled
unmeasured.

**The band that ships — THREE levels, not four:**

```
features(min_pts, matches_28d_min, comeback) -> {unmeasured, cold, comeback}
score = cold + 2*comeback + 2*unmeasured
BANDS = [(0, 0, "GOOD"), (1, 2, "FAIR"), (3, 99, "LOW")]
```

The fourth level claimed a resolution the data does not support: on the
test half the old top two bands sat **within 0.004 nats of each other and
in the wrong order**. The three that remain are monotone on **both** halves
of the residual cache and, independently, on the closing line.

`confidence.py fit`, out of sample on 14,228 matches (the later half of
28,455):

| band | n | log loss | surprise | accuracy | vs closing |
|---|---|---|---|---|---|
| GOOD | 3,051 | 0.60880 | **+0.0007** | 0.6536 | +0.0132 |
| FAIR | 9,960 | 0.60841 | **+0.0068** | 0.6588 | +0.0201 |
| LOW | 1,217 | 0.61355 | **+0.0198** | 0.6311 | +0.0314 |

**The raw log loss is FLAT across the bands** — 0.6088 / 0.6084 / 0.6136.
That is rule 16 in one line, and it is why the app no longer leads with it.

`MEASURED_DEFICIT` was re-measured by `tools/odds/disagree.py bands` on the
rebuilt cache: GOOD **+0.0132** (n 996), FAIR **+0.0201** (3,518), LOW
**+0.0314** (452) — the shipped constants reproduce it exactly, and the
check sorts.

**The app's trust panel leads with the surprise** ("on 1,217 held-out
matches this band came out +0.0198 nats worse than the model's own
confidence implied"), because raw log loss does not sort across bands. The
deficit against closing is printed **underneath, as the independent check**
rather than as what the band was fitted to. The "thinner side" row now says
plainly that **above 1,500 points it no longer moves the band**, and that
below 1,500 the harness never scores a match so the band assumes the worst.

**SUPERSEDED — the four-band version (2026-09-15 and earlier).** Realised
log loss per band on the final residuals (`confidence.py fit`, 2026-09-15,
7-day cadence, age-dependent prior, refreshed archive): GOOD **0.58777** (n
10,238), FAIR **0.64113** (3,280), LOW **0.76531** (710) — monotone, and
HIGH absent because it was unreachable. (With the flat own prior at 7 days:
GOOD 0.59021 (10,238), FAIR 0.64117 (3,280), LOW 0.76423 (710); with the
tour-average prior at 7 days: GOOD 0.59458 (10,227), FAIR 0.63616 (3,252),
LOW 0.74471 (710); at 21 days: GOOD 0.59677 (10,181), FAIR 0.63391 (3,251),
LOW 0.74335 (714).) `confidence.MEASURED_DEFICIT` — the four numbers a
price printed beside its band — had carried the M4-era odds study through
every model change since, because nothing in the refit chain re-measured
them; `tools/odds/disagree.py bands` was added on 2026-09-15 and the chain
runs it. **Its deficit did not sort**, on the pre-fix cache (4,966 joined
matches, 2024–2026):

| band | n | model | market | deficit | was |
|---|---|---|---|---|---|
| HIGH | 479 | 0.6023 | 0.5800 | **+0.0223** | +0.0143 |
| GOOD | 2,570 | 0.6250 | 0.6061 | **+0.0190** | +0.0225 |
| FAIR | 1,552 | 0.5993 | 0.5814 | **+0.0179** | +0.0307 |
| LOW | 365 | 0.6203 | 0.5900 | **+0.0303** | +0.0627 |

Every deficit was smaller than the M4-era numbers — the model improved —
but the clean 4.4× from HIGH to LOW was gone: LOW was still the worst and
still the band to distrust, and HIGH was no longer the best. **The rebuilt
cache did not rescue it**: re-measured on match-time service points the old
band still failed to sort — HIGH +0.0232 (586), GOOD +0.0179 (2,342), FAIR
+0.0190 (1,662), LOW +0.0296 (376) — so the non-sorting was the target, not
the cache. Two things move a deficit and the band controls one: the model's
error, and how sharp the MARKET is. HIGH was well-measured, match-fit
players, which is to say the marquee matches Pinnacle prices hardest. That
is rule 16 one level up — raw log loss cannot separate "the model is bad
here" from "this is hard", and the deficit cannot separate "the model is
bad here" from "the market is unusually good here". Which is why the band
above is fitted to surprise and only checked against the deficit.

---

## Totals — the promising direction

Unchanged: ordering good, level bias fixed and validated out of sample
(`BIAS = {3: 0.53, 5: 1.59}` in `fastgames.py`). **BLOCKER: there are no
totals odds** — needs an account or payment decision.
`tools/odds/totals_market.py` will run the moment a CSV exists.

One thing did change on 2026-09-15: this path takes the serve
probabilities **directly** and never sees the eight curves, so a
rating-layer gain the curves hide on the moneyline is not hidden here
(rule 33). The age-dependent prior's −0.00181 at t +7.17 on the ratings is
a gain this path inherits — unmeasured against totals prices, because
there are still none.

---

## Known problems

- **`features.build` with `TENNIS_EXTRA=1` takes ~15 min; the default build
  is ~2 min.** The extra covariates (the rejected opponent-calibre set)
  rescan every per-player history for every match; they are off by default,
  so `tools/curves.py build` is now ~2 min. Turn them on only to re-measure
  a rejected candidate.
- **Roland Garros 2026 has no serve stats** (118 rows, 0 with stats in the
  2026-09-14 refresh; confirmed absent at the source). The US Open 2026 had
  none either until that refresh brought 91 of its 127 rows with stats.
  The in-event update has nothing to bank at an event without stats and
  the price says so.
- **The confidence band's term below 1,500 service points is a floor, not
  a measurement.** The harness never scores a match where either player is
  under `MIN_PTS`, so there is no held-out evidence about those matches at
  all: the `unmeasured` term is +2 on the score by assumption, chosen to
  err in the only safe direction, and it is the one part of the band that
  was not fitted. Above 1,500 points the service-point count does not sort
  the surprise (+0.0120 / −0.0016 / +0.0134) and no longer moves the band.
- **`sim` excludes the curves.** `price` and `sim` differ by the curve amount.
- **Sackmann's repos are deleted**; the mirror is frozen at 2026-05-25
  (`update.py` still tries it: a no-op); results after come from
  tennisabstract via `tools/ta/` (373/373 exact; 969 rows as of
  2026-09-14, refreshed weekly).
- **Entry type is known only once a player has played at the event.**
  The reconstructed feed carries the draw prefix since 2026-09-14 (341 of
  969 rows with a code), so the `entry` curve applies from a player's second
  match at an event; for the first match the user says it (`--entry-a`, the
  prompt, the app), otherwise it is unknown and skipped, never guessed.
- **Licence** — CC BY-NC-SA 4.0. Personal, non-commercial use.

---

## Next steps

0. **Ship the best-of-five `form_scale`.** The confidence re-derivation
   found the model systematically **under-confident over five sets**
   (−0.0212 surprise against +0.0112 for best-of-three), and fitting
   `form_scale` per format on the train half — **best of 3 → 0.70, best of
   5 → 0.50** — is worth **−0.00028 overall at t +2.14** on 21,584
   held-out matches and **−0.00144 at t +2.14** on the 4,209 best-of-five
   among them, with best-of-three unchanged. Measured and ready; not
   shipped because `form_scale` is a scalar read by `price.scaled_form_sd`
   and `backtest.price_player`, so a format-dependent one touches the live
   pricing path. Needs the plumbing, a refit chain and the rule-33
   both-ways check. `bo5_scale_note` in `fitted_params.json`.
1. **Refresh weekly.** `python3 update.py` then `sh tools/refit_chain.sh`
   — the 7-day cadence is a commitment (rule 30): the headline assumes the
   shipped ratings are never staler than a week. If the feed ever supports
   it, 3 days is measured (−0.00023 at t +5.38 against 7, on the archive
   before the refresh) and one refit chain away: `refit_days` in
   `fitted_params.json` (or `TENNIS_REFIT_DAYS=3`), then the chain.
2. **The curves now hide rating-layer gains (rule 33).** Two directions.
   Measure the next rating change **both ways** as a matter of course — the
   scratchpad `curvepair.py` is the pattern: two residual caches, paired
   per match, scored before and after the eight curves. And ask whether the
   **curve set should be re-derived** now that it is only −0.00541: every
   curve still earns its place, but `entry` is now the largest and `age`
   has halved, so the set was selected against a rating layer that no
   longer exists.
3. **The 10%+ bucket is still where the gap lives** (2025 +0.054 on 495
   matches, 2024 +0.072 on 497). Candidates: a per-player refit cadence; a
   draw feed for a player's **first** match at an event (later matches read
   the code from the feed since 2026-09-14).
4. **Get totals odds** (unchanged blocker) — and note the totals path is
   where the rating-layer gain is **not** hidden by the curves.
5. **Fit `news_w`** from `data/news_applied.jsonl` once a few hundred
   matches carry news.
6. **Or accept it as a study.** Beating tuned Elo by 0.0540 nats on the
   same matches is a real result.

Deliberately *not* next: more scalar Tier-2 features, and re-measuring
anything with a tool that prices the single-number model —
`tools/pathsweep.py` is the yardstick now.

---

## Commands

```bash
python3 tennis.py                       # interactive prompt
python3 tennis.py app                   # browse it: type a name, Enter, twice (.claude/launch.json starts it for the preview pane)
python3 tennis.py price Sinner Alcaraz clay bo5 --at "US Open"
python3 tennis.py price A B --entry-a Q  # entry type is asked, never guessed (main, Q, WC, LL, PR, SE; also --entry-b)
python3 tennis.py sim Sinner Alcaraz clay bo5
python3 tennis.py news --prompt "Alcaraz"
python3 tennis.py gates                 # 6 gates, ~1 min
python3 tennis.py fit                   # weights.json, ~11 s
python3 tennis.py backtest              # the ladder + fitted_params (incl. test_matches, elo_log_loss, prior_mode, prior_age); a walk at 7 days is 634 refits on the refreshed archive, 389 s (633 before it, ~6.5 min contended)
python3 backtest.py --gate              # harness derivation == weights.json
python3 tools/pathsweep.py all          # flip each shipped layer, paired (445 s at 7 days)
python3 tools/pathsweep.py event_w 0 0.5 1 2 4
python3 tools/knobsweep.py run refit_days 3 && python3 tools/knobsweep.py compare refit_days   # one walk per value, paired on the intersection (cache in tools/_knobsweep/); compare prints BOTH halves (rule 32)
python3 tools/knobsweep.py run prior_mode own && python3 tools/knobsweep.py compare prior_mode   # the prior: own vs tour, two walks (~452 s each at 7 days), paired
TENNIS_PRIOR_MODE=own python3 tools/knobsweep.py run prior_weight 100 300 600   # a knob under another knob's override — check the override reaches the harness (rule 31)
TENNIS_PRIOR_AGE=2,0 python3 tennis.py price A B        # the age ramp on the prior, as an override; (1,1) is exactly prior_mode own
TENNIS_PRIOR_MODE=age python3 tools/knobsweep.py run prior_age 1,1 1,0 2,0 2.5,0 && python3 tools/knobsweep.py compare prior_age   # the 2026-09-15 sweep: young,old — run (1,1) first, it must reproduce prior_mode own to 0.0 (rule 31)
python3 tools/traitsweep.py             # TRAIT_K x TRAIT_MIN on the residual cache, paired, ~10 s a value, no walk (or explicit pairs: 40,15 80,15)
python3 tools/agehl.py run 1.0 1.0 0.7 0.85 && python3 tools/agehl.py compare
TENNIS_MIN_PTS=300 python3 tools/qcthin.py run none 1.0 && TENNIS_MIN_PTS=300 python3 tools/qcthin.py compare
python3 tools/curves.py build           # ~2 min (features.build; TENNIS_EXTRA=1 for ~15 min with the rejected covariates), then:
python3 tools/curves.py add <candidates>   # forward selection: each candidate alone onto the shipped set
python3 tools/curves.py reliability     # split-half reliability of the per-player traits (rule 17)
python3 tools/curves.py loo && python3 tools/curves.py write   # write also refreshes data/player_traits.json; --k= on both
python3 tools/curves.py antisym --logit matches_28d event_gwp event_sets_lost home age form_spw resid_prior entry
python3 confidence.py fit
python3 tools/odds/m4.py 2025           # vs the closing line; writes data/market_check.json for the app's model tab (also 2024)
python3 update.py                       # the weekly refresh (rule 30): mirror (dead, a no-op) + tennisabstract results incl. seeds and entry codes + weather; ends with VERIFY PASS
sh tools/refit_chain.sh /tmp/chain.log  # then the whole chain in order (~25 min at 7 days uncontended, ~1.5 h with other walks alongside); the log ends with ALL GATES PASS and == DONE
```

The weekly rhythm is `python3 update.py` then `sh tools/refit_chain.sh`.
After **any** model change the same chain, which runs `tennis.py fit`,
`backtest.py --gate`, `tennis.py backtest`, `tools/pathsweep.py all`,
`tools/curves.py build` (~2 min) / `loo` / `antisym` / `fit` / `write`,
`confidence.py fit`, `tools/odds/m4.py 2025` / `2024` (the app's model tab
reads its output) and `tennis.py gates`, in that order (`tools/curves.py
add` is separate: forward selection of a candidate curve). A constant that
was chosen rather than fitted goes through `tools/knobsweep.py run` /
`compare` first (one walk per value; ~7.5 minutes each at 7 days on the
refreshed archive) — and the value must win on **both** halves, not just
the test one (rule 32) — a constant of the correction layer through
`tools/traitsweep.py` (no walk). A change to the rating layer is also
measured **both ways**, before and after the curves, before it is claimed
(rule 33).

The explainer artifact is **Serve and Return**:
(an internal explainer page, link removed) —
refresh it to match the code at the end of every session.
