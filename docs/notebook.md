# Tennis model — data points and their implications

## How to read this

The model is a Barnett–Clarke point model: every match reduces to two numbers,
`p_serve(A vs B)` and `p_serve(B vs A)`, which then get recursed or simulated up
to a match price. So every data point below does exactly one of three things:

- **(S)** sharpens the *estimate* of a player's serve/return ability — pre-match
- **(D)** perturbs `p` *within* a match — dynamic, only usable live or as an in-match term
- **(M)** feeds a *different market* (games total, set handicap, retirement) rather than moneyline
- **(X)** is a **trap** — looks predictive, isn't, or is unusable

The tier is value-per-hour-of-work, not intellectual interest. Tier 0 is ~90% of
the model. Everything in Tiers 1 and 2 combined is worth less than getting Tier 0
shrinkage right.

---

## Tier 0 — the spine

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **Serve points won %** (`w_svpt`, `w_1stWon`, `w_2ndWon`) | Sackmann `atp_matches_*.csv` | S | *This is the model.* Trailing, surface-split, opponent-adjusted, decay-weighted, shrunk. |
| **Return points won %** | derived: `1 − opponent's spw` in that match | S | Not a separate column. Same rows, read the other way. Together with spw it gives the matchup `p`. |
| **Service points played** (`w_svpt`) | same | S | The *denominator*. Weight decayed counts, never match-level percentages — a 45-point match must not equal a 210-point match. |
| **Match date** | `tourney_date` + round ordering | S | Decay anchor and the leakage guard. See the `tourney_date` trap below. |
| **Surface** | `surface` | S | Serve dominance grass > hard > clay. Needs *two-level* shrinkage: surface rating → player overall → tour mean. You cannot fit surface ratings independently; clay data for one player is ~12 matches/yr. |
| **Indoor / outdoor** | tournament lookup | S | Effectively a fourth surface. No wind, no sun, stable bounce → higher hold %. |
| **Best-of-3 vs best-of-5** | `best_of` | S,D | Changes variance (favourite's win prob rises in Bo5) *and* the fatigue basis. Bo3 averages ~155 points, Bo5 ~250. |
| **Opponent identity** | `winner_id` / `loser_id` | S | Mandatory. Raw spw is uninterpretable — a player fed qualifiers looks elite. Adjust iteratively (two-way effects) or jointly. |
| **Tour level** | `tourney_level` (G/M/A/D/F/C) | S | Mostly a proxy for opponent quality (already handled), but flags regime differences: Challenger courts vary far more and stats coverage is worse. |
| **Retirement / walkover** | `score` contains `RET`/`W/O` | S | Hygiene, not a feature. Keep the points for rating updates; drop the *outcome* from backtest labels. |

**Tour-average serve % is not a constant.** ATP ≈ 0.645, WTA ≈ 0.565. It also drifts
by year and surface. Your `TOUR_AVG_SERVE = 0.645` is fine for ATP-only and will
silently destroy the model the day you add WTA, because Barnett–Clarke centres the
whole matchup calculation on it.

---

## Tier 0.5 — structural priors (cheap, and they fix the tails)

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **Age / DOB** | `atp_players.csv` | S | Non-linear, and only matters at the tails. Teenagers: trailing ratings are stale and biased *low*. 33+: biased *high*. Use it to tilt the shrinkage target, not as a raw regressor. |
| **Career matches to date** | derived | S | What `prior_weight` is really keyed on. |
| **Handedness** | `atp_players.csv` | S | Real but subtle. A lefty's rating *already contains* his lefty advantage, since ~85% of his opponents were righties. The feature you want is the deviation when that advantage vanishes: `both_lefty`. Entering raw handedness double-counts. |
| **Height** | `atp_players.csv` | X,S | Genuinely drives serve %, but it is *already inside* `serve_won`. Adding both double-counts. Only useful as a prior for thin-data players — a 2.05 m rookie will probably serve well. |
| **Country / home advantage** | `atp_players.csv` | S | Small, real, larger for home wildcards and much larger in Davis Cup. |

---

## Tier 1 — conditions

**The single physical quantity is air density.** Temperature, altitude and humidity
are three inputs to one number. Entering them separately buys you collinearity and
nothing else.

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **Venue elevation** | one-off lookup, ~30 rows | S | Madrid 667 m, Gstaad ~1050 m, Kitzbühel ~760 m, Bogotá ~2640 m. Less drag → faster ball → serve dominance up, rallies short, clay plays like hard. Cheapest real edge on this list. |
| **Temperature** | Open-Meteo archive API (free, no key, ERA5, lat/lon + date) | S | A 10 °C → 35 °C swing is ~8% of density — *comparable to Madrid's entire altitude effect*. Not a marginal feature. |
| **Humidity** | same | S | Physics says humid air is less dense (H₂O is lighter than N₂); reality says humid courts play slow because the felt fluffs and the ball soaks. The ball effect usually wins. **Do not impose a sign** — fit it and expect the opposite of the physics term. |
| **→ Air density (derived)** | `air_density(temp, elev, rh) / 1.204 − 1` | S | Feed *this one number*, not its three inputs. |
| **Wind speed** | Open-Meteo | S,M | Outdoor only. Raises double faults, lowers 1st-serve %, hurts precision servers more than grinders, and *depresses* serve dominance overall. Underrated for totals. |
| **Roof open/closed** | hard — live feeds, news | S | Closed roof = indoor, weather effect is **zero**. If you don't flag it you are injecting pure noise into every weather coefficient. Roofs: AO ×3, Wimbledon ×2, RG (Chatrier), USO (Ashe, Armstrong). |
| **Day vs night session** | schedule data | S | **This is your identification lever.** See below. |
| **Court speed index** | compute it yourself | S | Better derived empirically — multi-year ace rate and hold rate at that event vs tour average — than sourced. ITF publishes a 1–5 class but not per-event CPI. Cincinnati and Monte Carlo are wildly different despite both being outdoor hard/clay. |
| **Ball brand** | tournament records | S | Real (players complain constantly, and they're right). Mostly absorbed into the tournament effect — so it only matters when a tournament **changes** balls, at which point your tournament effect is silently stale. |

### The identification problem

Temperature is almost perfectly confounded with tournament identity. The Australian
Open is hot — and also has particular balls, a particular court, and a particular
slot in the calendar. With one temperature per tournament you *cannot* separate the
two, and a naive fit will attribute the whole tournament effect to weather.

Identification has to come from **within-tournament variation**: the same event across
a hot week and a cool week, and especially **day vs night sessions**, where the
temperature gap is large and literally everything else is held constant.

### Where weather actually pays

Probably not moneyline — both players experience it, so it largely cancels. It pays
on **games totals**: hot conditions → more holds → more tiebreaks → longer sets.
Totals are less efficiently priced than match winner, so a weather-aware total is a
far more plausible edge than a weather-aware moneyline.

---

## Tier 2 — schedule and physical state

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **Days since last match** | derived | S | Non-linear: 0–1 fatigued, 2–4 optimal, 14+ rusty or quietly injured. |
| **Cumulative minutes this tournament** | `minutes` column, summed | S,D | The real fatigue variable — better than matches played. Three 5-setters ≠ three straight-sets wins. |
| **Points/sets played in previous match** | derived | S | Acute fatigue. |
| **Consecutive weeks on tour** | derived | S | Chronic load. |
| **Time-zone shift since last event** | derived from venue lat/lon | S | Jet lag. Indian Wells → Miami is 3h; Europe → Australia is brutal. Small, hard to fit, low priority. |
| **Retirement / MTO history** | `score` field, last N matches | M | Strong predictor of *another* retirement. Matters enormously for in-play and for "match completed" markets, much less for pre-match moneyline. |
| **Time since layoff return** | derived from date gaps | S | **The highest-leverage case on this page.** Comeback players are exactly where trailing ratings are most wrong *and* where the market is most likely to be wrong too. That's where edges live — and where you get slaughtered if you're naive about shrinkage. |
| **Protected ranking entry** | entry field | S | A flag meaning "this player's rating is stale by construction." Treat as a data-quality signal, not a feature. |
| **Qualifier status** | `winner_entry` / `loser_entry` | S | Cuts both ways: 2–3 extra matches of fatigue, but also hot form and a rating built on thin, low-level data. |

---

## Tier 2 — context and motivation

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **Round** | `round` | S | Mostly opponent quality (already adjusted). Residual: effort. Stars coast in early rounds at 250s. |
| **Ranking / points** | `winner_rank`, `winner_rank_points` | X,S | Redundant with your ratings and *worse* — ranking is a 52-week accumulation that ignores opponent quality and surface entirely. Use only for entry status and as a shrinkage prior when data is thin. |
| **Seeding** | `winner_seed` | S | Same, plus draw-position effects for tournament-level sims. |
| **Points defended / ranking milestones** | ATP ranking data | S | Real motivation effect, hard to quantify. Late-season coasting after Finals qualification is decided is genuine. |
| **Head-to-head record** | derived | **X** | **The big one.** Near-zero predictive power once ability and surface are controlled. It is the first thing every commentator mentions, which is precisely why the market overweights it — your edge runs in the *opposite* direction to the instinct. |
| **Coaching change** | news | X | Anecdotal, unquantifiable at scale. Skip. |

---

## Tier 3 — point-level data

**The rule: if a variable is an *outcome* of the point rather than an *input* to it,
it can never be a live feature. It can only be a player profile.**

| Data point | Source | Kind | Implication |
|---|---|---|---|
| **1st vs 2nd serve split** | `w_1stIn`, `w_1stWon`, `w_2ndWon` | X → S | Enormous effect (ATP ≈ 0.73 vs ≈ 0.52) and **completely unusable live** — you don't know which serve it is before the point. But the *gap* is a superb profile feature: a big gap means high variance. This is what should be driving `form_sd`, rather than a hand-set 0.020. |
| **Ace rate** | `w_ace` | S | Also your best empirical court-speed estimator, since ace rate is a joint function of server quality and surface pace. |
| **Double-fault rate** | `w_df` | S,M | Interacts with wind. Feeds totals. |
| **Rally length distribution** | Match Charting Project | X → S,M | Outcome, not input. Profile only. Genuinely useful for totals and for the fatigue interaction — a grinder tires a bomber. |
| **BP saved / faced** | `w_bpSaved`, `w_bpFaced` | X → D | *BP faced* is meaningful (it's serve quality restated). *BP conversion* is mostly noise — it doesn't persist beyond what serve/return quality already predicts. This is exactly what your `bp_serving` / `bp_returning` coefficients try to capture, and for most players the honest fitted answer is ~zero. |
| **Score state / momentum** | reconstructable | D | Your `momentum` term. Same warning: most apparent momentum in tennis is an artifact of the ability gap. |
| **Point-by-point sequences** | `tennis_slam_pointbypoint` (slams only) | D | The only way to actually *fit* the dynamic coefficients. Slams only, so Bo5-biased. |
| **Serve speed / placement / spin** | Hawkeye | — | Not public at scale. Skip. |
| **Distance run per point** | IBM slam feeds | D | The best direct fatigue measure that exists. Mostly unavailable. |
| **Time between points** | some PBP feeds | D | A real fatigue tell — players slow down measurably when tired. |

### On fitting the dynamic coefficients

Do **not** fit `bp_*`, `gp_*`, `momentum` or `fat_*` per player. Eleven free
parameters against a few thousand points per player will overfit ferociously and
produce confident nonsense. Fit a **tour-wide** effect first, then allow per-player
deviations shrunk hard toward it. Most players' deviations should come back
indistinguishable from zero, and that is the correct answer, not a failure.

---

## Market data — a benchmark, not a feature

| Data point | Source | Implication |
|---|---|---|
| **Pinnacle closing odds** | tennis-data.co.uk (`PSW`/`PSL`, ATP back to ~2001) | **Not a feature — the gate.** Backtest against closing and measure CLV *before* adding a single Tier 2 feature. |
| **Opening odds / line movement** | same | The *direction* of the move carries sharp information. But using it means you are modelling the market, not the match. Legitimate, separate project. |
| **Vig / book count** | derived | Needed to de-vig before any CLV number means anything. |
| **Liquidity and limits** | book-specific | A 4% edge into a €200 limit is not a business. Decide this before building, not after. |

---

## Plumbing — where the time actually goes

None of these are features. All of them will silently ruin the model.

- **Player ID mapping.** Sackmann IDs ↔ bookmaker name strings ↔ Tennis Abstract.
  Transliteration, accents, name collisions, juniors sharing surnames. Do it once,
  properly, with fuzzy match plus a manually reviewed override table. This is the
  single largest chunk of real work in the project.
- **`tourney_date` is the tournament *start* date, not the match date.** Every match
  in a fortnight-long slam shares one date. Your decay is coarse to the week and
  your "days since last match" is wrong unless you reconstruct match dates from
  round ordering.
- **Stats coverage is not uniform.** Point-level columns start ~1991 and are patchy
  before ~2000, and poor at Challenger level. Your spw is computed on a *biased
  subsample*. Plot coverage by year and by level before you trust a single number.
- **Doubles must be excluded**, and qualifying matches are in separate files
  (`atp_matches_qual_chall_*.csv`) — they count for fatigue but have worse coverage.
- **Match Charting Project is not a random sample.** Volunteers chart famous players
  in big matches. Tempting, and dangerous, for exactly that reason.
- **Timezones** on match datetimes, for correct rest-day arithmetic.

---

## Weighting: how to value the past

Exponential decay on the **counts**, not on match-level percentages:

```python
w = 0.5 ** (age_days / half_life_days)
num += w * points_won
den += w * points_played
rating = (num + prior_weight * prior) / (den + prior_weight)
```

`prior_weight` is a pseudo-count in units of service points. 300 means "this player
needs 300 weighted service points before I trust him over the tour average." That
one line is your entire shrinkage.

**Fit the half-life, don't pick it.** Grid over `(60, 90, 180, 365, 540, 730)`,
walk forward, minimise out-of-sample log loss. Expect different answers per quantity:
serve ability is stable and wants a long half-life; surface-specific ratings want a
longer one still, purely because the data is so thin — you are trading recency
against sample size.

**Use two timescales.** A single half-life forces one answer to two different
questions — *how good is this player* and *how is he playing now*:

```python
slow = decayed_rating(m, asof, half_life_days=730)   # career level
fast = decayed_rating(m, asof, half_life_days=90)    # current form
p    = alpha * fast + (1 - alpha) * slow             # fit alpha, ~0.25-0.4
```

**Decay by calendar days, never by matches played.** A player back from an eight-month
injury *should* have stale ratings, and calendar decay gives you that for free.

**No leakage, ever.** Ratings as-of a match use only matches strictly before it, and
the backtest walks forward. Random k-fold on tennis data will hand you a beautiful,
entirely fictional result.

---

## What this implies for `tennis_sim.py` as it stands

1. `TOUR_AVG_SERVE = 0.645` — hardcoded, ATP-only, and drifts by year and surface.
   M1 replaces it with a computed value; the tour-average check is also what tells
   you the constant was right in the first place.
2. `fatigue_basis` divides by 250 points — tuned for Bo5. In Bo3 (~155 points) the
   hinge at `x = 0.6` almost never fires. Either scale by expected match length or
   fit separate coefficients per format.
3. `form_sd = 0.020` is hand-set. It should be *derived* from the player's 1st/2nd
   serve gap and match count, not assumed uniform.
4. The eleven dynamic coefficients need pooled-then-shrunk fitting, not per-player
   least squares. Defaults of 0.0 are correct until then — and the zero-coefficient
   equivalence to `static_p` is the property that keeps invented numbers out of a price.

---

## Sources

| What | Where |
|---|---|
| Match results + stats, ATP/WTA | `github.com/Aneeshers/tennis-sackmann-archive` — **upstream is gone**, see below |
| Challenger / qualifying | `atp/atp_matches_qual_chall_YYYY.csv` in that mirror |
| Player DOB, hand, height, country | `atp/atp_players.csv` |
| Slam point-by-point | `slam_pointbypoint/` in the same mirror (snapshot Oct 2024) |
| Rally-level charting | `github.com/JeffSackmann/tennis_MatchChartingProject` — still live (biased sample) |
| Pinnacle closing odds | `tennis-data.co.uk` |
| Historical weather | Open-Meteo archive API — free, no key, back to 1940 |
| Venue elevation | one-off manual table, ~30 rows |

---

## Build order, with gates

| Step | Work | Gate — do not proceed until it passes |
|---|---|---|
| **M1** | ~~Clone, parse match CSVs, compute spw/rpw per player~~ | **DONE** — 199,389 matches, 0.6372 recent |
| **M2** | Decay + shrinkage + opponent adjustment | **DONE** — beats Elo 0.6316 vs 0.6596 on held-out log loss |
| **M3** | Wire ratings into the sim, price matches | Sim agrees with exact recursion (you already have this gate) |
| **M4** | Backtest vs Pinnacle closing, measure CLV | **Match or beat closing.** If you can't, stop. |
| **M5** | Air density, court speed, wind — totals first | Improves log loss out-of-sample, not in-sample |
| **M6** | Dynamic coefficients from slam PBP | Pooled effects significant before any per-player deviation |

**M4 is a gate, not a milestone.** If the pre-game model can't match the closing
line, no fatigue term will rescue it — the problem is in the ratings, and every
feature you add after that point just hides it better.


---

## Addendum — data source, verified 2026-09-07

**Jeff Sackmann's `tennis_atp` and `tennis_wta` repositories no longer exist.**
His GitHub account is down to a single public repo (`tennis_MatchChartingProject`).
Every tutorial and paper that tells you to clone `JeffSackmann/tennis_atp` is now
pointing at a 404.

The project uses `Aneeshers/tennis-sackmann-archive` instead — a data-only mirror,
ATP/WTA snapshotted from upstream in June 2026, slam point-by-point from commit
`6febb77` (October 2024).

### Provenance — how the mirror was verified

No independent second copy exists to hash against, so verification is statistical
and semantic rather than cryptographic. All four checks passed:

| Check | Result |
|---|---|
| Arithmetic identities (`1stIn ≤ svpt`, `1stWon ≤ 1stIn`, `2ndWon ≤ svpt − 1stIn`) | **50 violations in ~158,000 sides (0.03%)** |
| Surface ordering of serve dominance | Grass 0.660 > Hard 0.642 > Clay 0.619 — physically correct |
| Era drift | 0.6233 (2000–04) → 0.6420 (2025+), monotone, matches known racquet/string trends |
| Top-of-list players | Servers: Karlovic, Isner, Raonic, Roddick, Opelka. Returners: Coria, Nadal, Ferrer, Djokovic |

The 14,074 rejected sides are **blank**, not corrupt — that is coverage, and it is
concentrated pre-2000 exactly as predicted. Treat this as good but not proof:
re-run `load.py` after any re-clone, and treat a change in those numbers as a
provenance failure.

### Licence — decide this before you build further

The data is **CC BY-NC-SA 4.0**, which is Sackmann's own licence, not something the
mirror added. The **NonCommercial** clause is a live question for a betting model:
personal wagering is arguably not commercial use, running it as a business plainly
is, and "ShareAlike" has implications if you ever redistribute anything derived
from it. This is a judgment call and it is yours to make — but make it now, not
after M4, because the answer may change which data you are willing to build on.

### Correction to Tier 0

The plan said tour-average serve is "≈ 0.645". Measured on this dataset it is
**0.6319** across 2000–2026 and **0.6372** for 2015–2026. The 0.645 figure is
roughly today's *hard-court* number, not an all-surface average.

This matters because `tour_avg` enters `matchup_p` as `(1 − tour_avg)` — a symmetric
shift applied to both players. It cancels in a symmetric matchup, but not otherwise,
and it biases every games-total. **The operative rule: `serve_won`, `return_won` and
the average used with them must all come from the same slice of data.** Mixing a
quoted constant with your own ratings is the failure mode.

Surface values now live in `tour_avg.json`, read via `load.tour_avg(surface)`.


---

## Addendum — M2 estimator, built 2026-09-07

Built and gated against **synthetic data with known true abilities** before
touching real matches. That ordering earned its keep: three real bugs showed up
that real data would have hidden, because real data has no ground truth to
disagree with.

### What synthetic data caught

**1. Assortative pairing must sort on `serve + ret`, not `serve − ret`.**
The latter is serve *bias*, not ability — it pairs big servers against weak
returners and biases the test backwards. The naive estimator came back at slope
1.22 (over-dispersed) when the true effect is compression.

**2. One streaming pass is worse than no adjustment at all.**
Correcting A's serve with B's return, when B's return was itself corrected with
A's serve, is circular. Measured on synthetic data:

| estimator | slope (1.0 = unbiased) | rmse |
|---|---|---|
| raw, unadjusted | 0.663 | 0.01455 |
| streaming, adjusted | 0.604 | 0.01732 |
| **iterative, converged** | **1.028** | **0.00497** |
| oracle (true opponent ratings) | 1.002 | 0.00452 |

The oracle row is the diagnostic that mattered — it proved the *equation* was
right and isolated the fault to the estimates feeding it.

**3. Convergence is not optional, and a fixed iteration cap fails silently.**
Slope climbs 0.676 → 0.800 → 0.914 → 1.020 at 1, 12, 40, 150 sweeps. A cap of 12
returns 0.800 — attenuated by 20% and entirely plausible-looking. `fit_iterative`
now reports `info["converged"]`; **check it, every time.**

Convergence *rate* is set by how well connected the who-played-whom graph is.
Tight assortative pairing (k=8) needs ~350 sweeps; k=32 converges in 12. Real ATP
data converges in **47 sweeps (0.2s)** — actual draws are far better connected
than a synthetic ladder, thanks to qualifiers, upsets and surface variety.

### What the real fit then showed

Fitted on 30,441 rated matches, 2015–2026, 730-day half-life:

- Serve: Isner, Raonic, Sinner, Djokovic, Opelka, Fritz. Return: Alcaraz, Sinner,
  Nadal, Djokovic, De Minaur, Medvedev. Both correct.
- **The opponent adjustment is mostly a level shift, not a re-ranking**
  (mean +0.0159, slope vs raw 0.970).

The mechanism is worth internalising, because it applies to every stat in Tier 0:
**winning a match earns you another one.** Top-50 players make ~113 decayed
appearances to the bottom-50's ~39. So the average *opponent* is meaningfully
better than the average *player* — mean return ability faced is 0.3800 against a
0.3628 prior — and **every raw serve percentage on the tour is biased down by
about 1.7 points.**

`serve[]` therefore means "serve % against a league-average returner", not "serve
% observed". `matchup_p` puts the opponent effect back. Serve and return shift
together, so the two cancel and the tour-average level still holds — the
`(serve + c, ret + c)` invariance of the two-way model.

### Still open in M2

- Walk-forward log-loss backtest, and **fitting** the half-life, `alpha` and
  `prior_weight` rather than accepting the defaults.
- Surface-split ratings with two-level shrinkage.
- `tourney_date` is still the tournament start date. Reconstructing true match
  dates from round order is needed before decay is finer than weekly.


---

## Addendum — M2 backtest, 2026-09-07

Walk-forward, quarterly refits, 3-year burn-in, trained only on prior matches.
57,795 matches 2005–2026 → 35,576 scorable, split in half by time. Everything
tuned on the first half, reported on the second.

| model | log loss | brier | acc |
|---|---|---|---|
| coin flip | 0.69315 | 0.25000 | — |
| Elo, K=4 (results only) | 0.65964 | 0.23214 | 0.6147 |
| point model, no form_sd | 0.63727 | 0.22290 | 0.6351 |
| point model, no opponent adjustment | 0.63402 | 0.22239 | 0.6307 |
| **point model, form_sd=0.035** | **0.63161** | **0.22121** | **0.6351** |

**The point model beats Elo by 0.028 nats.** That was the gate worth setting:
Elo knows only who beat whom, so if Barnett–Clarke could not beat it, the whole
serve/return premise would have been unearned. It is earned.

### Two things the backtest reversed

**1. The opponent adjustment appeared to hurt, and does not.** Before `form_sd`,
adjusted scored *worse* than unadjusted on log loss (0.6185 vs 0.6172) while
scoring *better* on accuracy. The explanation: the adjustment correctly spreads
ratings apart, which raises confidence — and the model was already overconfident,
so a better ordering scored worse. With `form_sd` applied the ranking flips to
0.63161 vs 0.63402 and the adjustment is worth what synthetic data said it was.
**A miscalibrated model will punish you for improvements.** Fix calibration before
judging any feature.

**2. The Elo baseline was crippled and had to be fixed.** At K=24 it scored 0.858
— worse than a coin flip at 63% accuracy — through sheer overconfidence. Tuned on
the training half it wants K=4. Beating a broken baseline proves nothing, so Elo
now gets the same fitting courtesy the real model does.

### The point model is overconfident, and `form_sd` only half-fixes it

The plain point model treats every point as an i.i.d. draw from a known `p`, so
the only randomness is binomial — far less than real matches show. Players have
off days and ratings are estimates, not facts. `form_sd` integrates over match-day
ability (5-node Gauss–Hermite) and fits at **0.035**.

It helps (0.63727 → 0.63161) but does not close the gap. Residual on test:

| predicted | realised | gap |
|---|---|---|
| 0.62 | 0.60 | +0.022 |
| 0.71 | 0.68 | +0.024 |
| 0.79 | 0.76 | +0.030 |
| 0.87 | 0.84 | +0.032 |

Ordering is good; spread is too wide. **The next fix is a logistic recalibration
layer fitted on train — it is not yet applied, and prices are live without it.**

### Unfitted constants still in play

`SURFACE_SHRINK = 4000` (price.py), `alpha`, `HL_FAST`, and the 730-day half-life
are all still chosen rather than fitted. Surface weight currently lands near 45%
for a top player, which may under-weight surface specialists — Sinner prices ahead
of Alcaraz on clay, which is worth interrogating before trusting surface prices.

---

## Tooling added

| file | what it does |
|---|---|
| `price.py` | price a matchup from pre-match variables; `--variables` lists every accepted input and whether it is LIVE, RECORDED or IGNORED |
| `update.py` | pull the mirror forward, **re-verify provenance**, invalidate stale rating caches |
| `fastmatch.py` | tabulated + interpolated `p_match` (max error 5e-05, 52× faster with form integration); the exact recursion stays the source of truth |
| `backtest.py` | walk-forward harness, Elo baseline, form_sd fitting, calibration report |
| `data/manual_matches.csv` | optional, same 49-column schema, for results newer than the mirror; `load.py` merges it automatically |

`update.py` refuses to overwrite a data directory with local edits, and re-runs the
M1 arithmetic and surface-ordering checks on every pull — a shift there is a
provenance failure, not a rounding difference.


---

## Addendum — per-player weights, 2026-09-08

Two hand-picked constants replaced with derived, shrunk per-player values.
Verified on held-out data rather than assumed.

| model (test, 17,056 matches) | log loss | brier | acc |
|---|---|---|---|
| Elo, K=4 | 0.65964 | 0.23214 | 0.6147 |
| tour-wide form_sd=0.040 | 0.63108 | 0.22103 | 0.6351 |
| **per-player weights (scale 0.85)** | 0.62840 | 0.21964 | 0.6402 |
| **+ calibration** | **0.62778** | **0.21944** | **0.6402** |

### What each per-player weight is

**form_sd** — measured as *overdispersion*: how much a player's match-to-match
serve % varies beyond binomial noise. Residuals are taken against the
**opponent-adjusted expectation**, not the player's own mean. Measuring around a
raw mean makes form_sd absorb schedule variety — a journeyman facing both
qualifiers and top-10 looks volatile when it is their opponents varying, not
them. Shrunk toward the tour value by match count; a global scale of **0.85** is
then fitted on train.

**surface ability** — empirical Bayes. The deviation is (this surface) minus
(all *other* surfaces), combined by precision:

```
ability = [x1/v1 + (x2+mu)/(v2+tau²)] / [1/v1 + 1/(v2+tau²)]
```

Ruud gets 92% weight on his clay record (10,565 points) but only 34% on grass
(1,040 points). A flat `SURFACE_SHRINK` constant could not make that distinction.

Measured population spread of *real* surface effects:

| surface | serve tau | mean shift | return tau | mean shift |
|---|---|---|---|---|
| Clay | 0.0144 | −0.0216 | 0.0161 | +0.0166 |
| Hard | 0.0118 | +0.0115 | 0.0148 | −0.0006 |
| Grass | 0.0099 | +0.0115 | 0.0138 | −0.0270 |

Return tau exceeds serve tau on every surface — **surface specialisation lives
more in return than in serve**, which matches how tennis actually works.

### Two bugs the first attempt had

**1. tau came out 0.0000 — "surface specialisation does not exist".** The
deviation was measured as `surface − overall`, but the overall rating *contains*
the surface matches. Correlated estimates overstate sampling variance and drive
the estimated population spread to exactly zero. Contrasting against
*off-surface* matches makes the two samples disjoint and the signal appears.
Compounding it, `prior_weight=300` compressed the deviations while the noise
floor stayed unshrunk — the contrast fits now run near-unshrunk on purpose.

**2. form_sd was absorbing opponent quality**, as described above.

Both were caught by testing the hypothesis directly — measuring whether the
signal exists among well-measured players — rather than by patching the
estimator until it produced agreeable numbers.

### The calibration layer is nearly a no-op, and that is worth stating

Fitted slope **0.960** for per-player pricing, worth 0.0006 of log loss. The
tour-wide slope came back **1.002** — no correction at all. Fitting `form_sd`
properly absorbed essentially all of the overconfidence that calibration was
meant to fix; the causal fix removed the need for the cosmetic one.

Residual miscalibration remains but is **non-monotonic** (+0.036 at 0.83–0.92,
+0.008 at 0.92–1.00), so a single log-odds slope cannot capture it, and the worst
bucket holds only 954 matches (~3 SE). Isotonic regression is the next tool if
this is worth chasing — it may not be.

### Still unfitted

`half_life=730`, `prior_weight=300`, `HL_FAST`, `alpha`, and the `years=12`
training window are all still chosen rather than fitted.


---

## Addendum — matchup effects and Tier 1, 2026-09-08

### DATA STOPS 2026-05-25

The mirror's last snapshot is 2026-06-25 and its ATP data ends **2026-05-25** —
the first day of Roland Garros. Nothing newer exists upstream.

**Missing: Roland Garros 2026, Wimbledon 2026, the whole summer hard-court swing,
and the US Open.** Any price for a current match is built on ratings that are
~3.5 months and two slams stale. Fill the gap via `data/manual_matches.csv`
(49-column schema, merged automatically by `load.py`) or accept the staleness
explicitly.

### Opponent style and head-to-head: built, measured, worth zero

Both requested, both implemented in `interactions.py`, both fitted on the
training half of the walk-forward:

```
style_w 0.00  0.59306      h2h_w 0.00  0.59306
style_w 0.25  0.59311      h2h_w 0.25  0.59407
style_w 0.50  0.59350      h2h_w 0.50  0.59680
style_w 1.00  0.59478      h2h_w 1.00  0.60037
```

**Both fit to exactly 0.00.** Loss rises monotonically with weight. Test log
loss is identical with and without them (0.62840).

This is not a null result from a weak test. The effects *do* show weak
persistence — style raw split-half r = 0.23 across eras (137 players, +2.7 SE),
H2H r ≈ 0.16 (97 pairs, +1.6 SE, i.e. not significant), and H2H survived a check
for the obvious confound of lagging player ratings. **Persistence is not
predictive value.** The effects are real-ish, tiny, and swamped by the noise
they add.

The plan predicted this for H2H. It now also holds for stylistic matchups. The
code stays in place, switched off via fitted weights of zero — flip them by
setting `style_w`/`h2h_w` in `fitted_params.json` if a future dataset disagrees.

**Method note.** The first shrinkage attempt derived weights from an analytic
variance formula for a weighted-least-squares slope. That formula overstated
noise, drove tau to zero, and flattened a genuinely persistent effect to nothing.
Replaced with shrinkage calibrated from *measured* split-half reliability
(Spearman–Brown), which needs no algebra to be right.

### Tier 1 — venues and air density

`venues.py`: 110 venues with lat/lon/elevation/indoor, **95.2% of matches by
volume**. `weather.py`: Open-Meteo historical daily temperature, humidity and
wind, cached.

Name normalisation matters more than expected — the source data carries
`US Open` and `Us Open` as separate strings (1,264 + 760 matches), and a
hyphen mismatch was dropping Winston-Salem entirely.

**Air density predicts serve dominance, as the physics says it should:**

| density index | serve residual | points |
|---|---|---|
| < −0.10 (high altitude) | **+0.02169** | 36,736 |
| −0.10 to −0.07 | +0.00092 | 61,812 |
| −0.03 to 0.00 | −0.00038 | 1,359,542 |
| > 0.00 | +0.00027 | 719,343 |

`corr(density_index, serve residual) = −0.0350` on 22,456 outdoor
player-matches (~5.2 SE). Negative is correct: thinner air, less drag, faster
ball, server favoured. Slope implies Madrid vs sea level at 25 °C is worth about
**0.56 percentage points of serve**. The effect is concentrated at altitude —
the bulk of matches sit near zero index and show nothing, which is expected.

Indoor matches are excluded outright: a roof means no weather effect, and
feeding outdoor weather to an indoor match injects pure noise.

**Caveat: that measurement used only the venues whose weather had downloaded.**
Open-Meteo signals rate limits as valid JSON with HTTP 200, so 92 of 110 venues
silently cached as empty while the log printed success lines. `fetch_venue` now
raises on `error` and on empty `daily`, and `fetch_all` treats empty entries as
unfetched and retries with backoff. Currently 30/110 venues populated; the rest
are blocked by the hourly limit and the fetch resumes with the same command.
**Re-run the density analysis once coverage is complete before trusting the
coefficient.**

### Not yet done

Air density is measured but **not yet in the model** — it needs to go into
`backtest.py` as a fitted term, and the games-total market is where data_plan.md
expects it to pay, not moneyline.


---

## Addendum — air density + full hyperparameter fit, 2026-09-08

Final held-out results, 13,875 test matches, nothing tuned on them:

| model | log loss | brier | acc |
|---|---|---|---|
| coin flip | 0.69315 | 0.25000 | — |
| Elo, K=4 | 0.65492 | 0.22997 | 0.6200 |
| tour-wide form_sd | 0.62273 | 0.21740 | 0.6425 |
| per-player weights | 0.61720 | 0.21500 | 0.6493 |
| **+ air density (w=0.40)** | **0.61715** | **0.21498** | 0.6492 |
| + calibration | 0.61737 | 0.21506 | 0.6492 |

### Fitted, not guessed

`half_life` **730 → 270** (paired t = +2.80 on 13,875 common matches),
`prior_weight` 300 → 150 (nearly flat: 75–600 within 0.0002), `train_years`
8 → 5, `form_scale` 0.85.

**Two things had to be fixed before that comparison meant anything.**

**1. Configs were being scored on different matches.** A shorter half-life
means fewer players clear `MIN_PTS`, so it scores a *smaller and easier*
subset. Raw log loss then rewards shrinking the sample: half_life 270 "beat"
1460 by 0.008 while scoring 29,037 matches against 36,916. All comparisons now
run on the intersection, with a paired per-match t-test.

**2. `backtest.py` was clobbering the tuned values.** Its JSON writeback
hardcoded `half_life_days: 730, prior_weight: 300`, so the first two "final"
runs silently ran the *old* parameters. It now writes back what was actually
used.

### Surface needs its own timescale — and must not replace the current rating

data_plan.md predicted the first half: surface data is thin, so surface
ratings want a longer half-life than overall ratings. Dropping the overall
half-life to 270 took surface weights from 669 players to 413 and left only
Hard with enough well-measured players. Surface contrast now runs on its own
1,095-day half-life over a 12-year window.

The second half was not predicted. Substituting long-window surface ability
for the current rating **discards the entire benefit of the fitted 270-day
half-life** — measured, that made per-player *worse* than tour-wide
(t = −3.14). Carrying each player's recent form shift onto their long-window
surface ability instead flips it to **t = +4.54 in favour of per-player**.
Same information, opposite conclusion, purely from how the two timescales are
combined.

### Air density: real, measured, and nearly worthless for moneyline

`dens_w` fits to 0.40 and is worth **0.00005** of log loss. That is not a
failure of the feature — it is what data_plan.md predicted. Air density is
**symmetric**: both players serve in the same air, so it barely moves the
match winner. Its value is in **games totals**, which this backtest does not
score. The effect itself is solidly real (corr −0.035, ~5.2 SE, and +0.0217
serve residual at high altitude).

### Calibration is now DISABLED

Measured slope 1.030, and applying it made test log loss *worse*
(0.61715 → 0.61737). Fitting per-player `form_sd` absorbs the overconfidence
that calibration existed to correct. `calibration_b` is set to 1.0 — kept in
the code, switched off by its own fitted value.

### Still open

- `MIN_PTS = 1500` is unfitted and interacts with `half_life` (a shorter
  half-life means fewer decayed points, so fewer players qualify).
- `SURFACE_HALF_LIFE = 1095` and `LONG_YEARS = 12` are chosen, not fitted.
- Weather fetch was at 74/110 venues; all 9 significant high-altitude venues
  (Quito, Bogotá, Gstaad, Madrid, Kitzbühel, São Paulo, Santiago, Munich,
  Marrakech) are cached. Finish with `python3 weather.py fetch` and re-fit.
- **A games-total model is the natural next step** — it is where air density,
  wind and court speed should actually pay.

---

## Session 2026-09-09 — the browser view, and what it caught

`app.py` + `web/` put the whole tool behind a page: a roster of every rated
player, a player page, the price, and totals. Standard library only, bound to
127.0.0.1, and it **computes nothing** — every number comes back from
`price.py`, `weights.py`, `features.py`, `confidence.py`, `fastgames.py`, and
each answer carries the literal `tennis.py price` / `tennis.py sim` text in a
collapsed panel so the layout can be checked against the tool it renders.

Ranking a roster needs a scalar the model does not have — it has a serve
rating and a return rating, which trade off. The page ranks on the model's own
answer to "what does this player do against a tour-average opponent": the same
`win_prob` the pricing path runs, with the opponent pinned at tour average on
both sides. Not a new quantity, the model evaluated at a fixed reference.

### Two bugs the page made obvious in the first ten minutes

**1. `live_workload` never set `comeback`, so no live price could see a
layoff.** `features.build` emits the flag (no run at this event, 60+ days since
the last one) and `confidence.py` was **fitted** with it at **weight 2** — the
heaviest term in the band, for the population measuring **+0.052 against the
closing line, roughly double the baseline**. But `live_workload`, which every
interactive price goes through, returned five keys and that was not one of
them, so `wa.get("comeback") or 0` was 0 every single time. The band could
report thin data and cold form and was blind to the one factor that hurts most.

Visible in one glance on the player page: Sinner, 71 days idle since Wimbledon,
next to a band reading GOOD. Fixed — `live_workload` now derives `days_rest`,
`layoff_days` and `comeback` the way `build` does, with "before" defined as
"not part of the current run" rather than "a different event name", so last
year's edition of the same tournament still counts as history. **No price
moves**: `comeback` is not one of the three fitted curves, so it reaches the
band and nothing else. Verified bit-identical (0.5581389112295 both sides) and
all five gates pass. Sinner–Alcaraz now reads FAIR.

This is rule 7 wearing a different hat. Two derivations of the same quantity,
one of them quietly incomplete, and the incomplete one is the one a person
actually looks at.

**2. Surface strings.** `weights.json` keys surfaces `"Hard"`; the CLI maps a
typed `hard` through `price.SURFACES` before it reaches `Book.rating`. Passing
the lowercase string through does not raise — it finds no surface split and
silently prices on the overall rating. Wrong number, no error. Every surface
entering `app.py` now goes through one `_surface()` helper.

### Not a bug: the US Open 2026 draw

The page shows Sinner with no matches in 28 days and a −0.032 rust adjustment.
Checked: the draw in `manual_matches.csv` is complete and consistent — 64 R128
matches, 128 distinct players, 2 of 4 quarter-finals played — and he is not in
the field. Alcaraz shows 148 days since his previous *event* (Barcelona, 13
April) because he did not play between then and Flushing. Both are the data
being right, and both would have been invisible from the command line.

---

## Session 2026-09-09, part 2 — how the curves are applied, and home advantage

The instruction was "confirm nothing moved, then keep improving accuracy".
The backtest confirmed it: **0.61791 on test, to the digit**, with every
fitted parameter — `form_scale` 0.85, `dens_w` 0.40, `style_w` 0, `h2h_w` 0,
calibration OFF — coming back identical. The `comeback` fix lives in
`live_workload`, which `backtest.py` never calls, so that was the expected
result rather than a lucky one.

Then the improving. The handoff said not to add more Tier-2 features, and
re-running `tools/curves.py fit` over all fourteen confirmed why: outside the
three adopted curves, nothing clears ±0.0001. So the search went elsewhere.

### The application was worth more than any feature

`combined()` scored the curves by nudging each player's row independently.
`price.py` cannot do that — two probabilities must sum to one — so what the
harness measured and what the tool applied were **different adjustments**,
and nobody had measured the one that ships. Added `tools/curves.py antisym`,
which rebuilds matches from the winner/loser row pairs and scores exactly
`k(adj_a − adj_b)` applied to A.

Two things fell out.

**Additive-in-probability is unsafe, and it bit.** Fold 1 got sharply worse
between k=0.375 and k=0.5 — a jump far too large for 3,584 matches. It was
**one row**: p = 0.03321, adj = −0.0761, so `p + adj` went negative and the
clamp quoted 1e-6. That single match cost 13.8 nats, 0.0039 of the fold mean,
and by itself made the fold prefer a weaker adjustment. Without it the fold
agreed with the other three. `price.py` had the same clamp and could quote
the same million-to-one price on a real matchup.

Applied as a log-odds shift of `4*adj` instead: exact at p = 0.5 where
dp/dz = 1/4 and the curves were fitted, tapering toward the tails where a
bucket average should not be applied at full strength. It cannot leave (0,1)
by construction. **−0.00205 against −0.00170 at the same magnitude**, and
fold 1 stops being pathological (0.61885 → 0.61863 → 0.61862, a gentle
minimum instead of a blow-up).

**The magnitude was half what it should be.** `curve_adjustment` returned
`(adj_a − adj_b)/2`. Rule 9 requires *antisymmetry*, and any `k(adj_a − adj_b)`
is antisymmetric — the ½ was a conservative choice stacked on top of the
shrinkage `fit_curve` already applies. k=1 beats k=½ on **4 folds of 4**,
−0.00334 against −0.00205, with a flat optimum from k ≈ 0.75 to 1.5. k=1 is
also the natural value: A moves by what the curve says and B by the negative.
No new tunable, and the number that was already being reported to users was
half the effect that had been measured.

### Home advantage exists

Raw win rate at home is **46%** — home players are disproportionately
wildcards, which is exactly why it has to be measured on the residual.

On the residual, home players beat their own price by **+1.9 points**
(3,505 rows, +2.5 SE, positive in 9 of 12 years). Adopted: **−0.00015** on
top of the other three, **4 folds of 4**. Small, and no single year clears
2 SE, so it stands on fold consistency and a mechanism rather than on any
one split.

Three pieces of plumbing were needed and all three are worth having anyway:

* `load.Match` now carries `w_ioc`/`l_ioc`.
* `venues.COUNTRY` maps all 110 venues to a host nation, with the rotating
  season-ending finals left as None on purpose. **Validated against the
  data**: the mapped country is over-represented at its own event in
  **79/79** venues with enough rows, median lift **4.8x**. (The first
  version of that check ranked by ratio and "disagreed" on 40 venues — one
  Cypriot at a small event scores a lift of 6. Excess count is the quantity
  that is large when a host packs its own draw.)
* `load.fill_iocs` back-fills nationality from the player's nearest match in
  time. The tennisabstract feed publishes no country column, so **all 847
  rows of 2026** arrived blank and anything keyed on nationality would have
  silently dropped the current season. 97.4% → **99.89%**, with a gate:
  ≥99% coverage and zero players holding two countries inside one season.

### Rejected: `home_km`

Graded distance from home, own country = 0. The shape is real — ≤800 km
(one border away) over-performs by **+0.022**, *more* than home players, and
10,000 km+ under-performs by −0.015 — so the signal is genuinely broader than
nationality. But it scores −0.00007 alone and, run together with `home`, the
two cancel to **exactly** the three-curve baseline. Same signal, counted
twice, each over-correcting the other. Kept in the code for a future version
that uses country shapes rather than centroids: a centroid puts an American
at the US Open **2,096 km** from home, further than a Luxembourger at Metz
at 76 km, so raw distance ranks players by how large their country is.

A six-bucket `home_km` also lost out of sample by fitting the wiggles between
the two ends; collapsing it to three buckets on the **train** half's shape
flipped it back to positive. Bucket edges are a fitted quantity too.

### Net

Curve layer: **−0.00170 → −0.00349**, 4 folds of 4. Against the +0.029 gap to
Pinnacle closing, that is **5.9% → 12.0%**. The base model is untouched and
still scores 0.61791.

`fitted_curves.json` had no writer — it was maintained by hand, and its note
still claimed the curves were worth −0.0008 and closed 3% of the gap, both
long superseded. `tools/curves.py write` now produces it (rule 7).

---

## Session 2026-09-09, part 3 — age, and the end of the "features are exhausted" story

The handoff said not to add more Tier-2 features, and re-running
`tools/curves.py fit` over all fourteen existing covariates confirmed it:
outside the three adopted curves nothing cleared ±0.0001. That conclusion was
right about the covariates that had been tried and wrong about the shape of
the search.

### First, remove nothing

Added `tools/curves.py loo` — leave-one-out over the adopted set, at the
magnitude `price.py` actually uses. All four earned their place
(`matches_28d` +0.00218 cost to drop, `event_gwp` +0.00082, `event_sets_lost`
+0.00023, `home` +0.00014). Nothing to prune.

This turned out to be the tool that mattered, because a single-split score
cannot tell a real effect from a near-substitute.

### `age` — the largest effect in the project

`winner_age` has sat unused in column 15 since the beginning.

| age | residual | age | residual |
|---|---|---|---|
| under 21 | **+0.082** | 27–30 | −0.011 |
| 21–24 | +0.049 | 30–33 | −0.030 |
| 24–27 | +0.010 | 33+ | **−0.041** |

Monotone across all six buckets, monotone in each of three independent eras,
**youngest minus oldest +0.123 ± 0.013 = 9.3 SE**, worth **−0.00207 alone**
and **+0.00427 cost to drop** from the set. Nothing else here is within a
factor of two of it.

The mechanism is structural. The ratings are a decayed average over a
270-day half-life, so a rising player's rating lags their ability and a
declining player's over-states it. Every backward-looking rating does this;
chess gives juniors provisional ratings for exactly this reason. What is
surprising is not that the effect exists, it is that it is this large.

**The confound was tested and rejected.** A 19-year-old has few service
points, so `weights.py` shrinks their rating toward the tour mean — and
tour-level 19-year-olds are better than the tour mean. So "age" could just be
thin data. Built `career_pts` (decayed service points, the exact quantity
driving the shrinkage) and `career_matches` as controls: `career_pts` has a
nearly flat curve worth −0.00011, `career_matches` **hurts** the set, and with
both in, dropping `age` still costs **+0.00350**. The decline half settles it
regardless — 33-year-olds have the *most* data and are the most over-rated,
which no shrinkage story can produce.

**The adjustment is largest on lopsided-age matches, and that is exactly
where it gains most**: −0.0072 at a 0–3 year gap, −0.0043 at 3–6, −0.0119 at
6–10, **−0.0228 at 10+**. A wrong curve would do its damage precisely there.

### `form_spw` — the margin version of recent form

28-day service-points-won minus the player's own 365-day rate. `matches_28d`
counts recent matches; this measures how well they went, in points. Against
their own baseline rather than the tour's, so a career-long weak server does
not read as out of form.

−0.00118 alone, **+0.00145 cost to drop**. Monotone: −0.029 for a serve 3+
points below their year, +0.040 for 6+ points above. This is rule 8 run in
the other direction — a short window ON TOP OF a long one, the same shape as
the surface-timescale finding.

### Built, measured, rejected

- **`bp_form`** — break points saved over 180 days minus their own 730-day
  rate. The only clutch measurement the file contains, and the honest test of
  whether clutch is anything: −0.00013 alone, and it makes the set **worse**.
  A point model treats every point as identical; the data says that is fine.
- **`event_opp_rank`** — mean log10 rank of opponents beaten at this event,
  to give `event_gwp` the quality axis it lacks. **−0.00000**, non-monotone.
- **`rank_change`** (rank now vs a year ago) and **`peak_gap`** (rank now vs
  career best). Both real alone, −0.00076 and −0.00085, both strongly
  monotone. Both **hurt the set** once `age` is in it. They are the same
  trend, and `age` carries it better.
- **`career_matches`**, **`career_pts`** — controls, kept only as controls.

Every rejection has the same shape: **near-substitutes cancel**, and only
leave-one-out sees it. `home`/`home_km` cancelled exactly last round;
`age`/`rank_change`/`peak_gap` this round.

### Plumbing, all of it gated

- `Match` now carries `age`, `rank`, `bpSaved`, `bpFaced`.
- `load.fill_ages` back-fills age by arithmetic: an age at one date fixes the
  birthday, the birthday fixes the age at every date. Needed because the
  tennisabstract feed publishes no age column, leaving all 851 rows of 2026
  blank. 97.4% → **99.82%**.
- The birthday is the **median** implied birthday, not the mean. The gate
  caught why: the source's age is off by exactly one year on a scattering of
  rows (36 players of 4,539) and one is off by five years, and a mean let
  those drag the estimate by months.
- `live_workload` reads the same shared birthday rather than one match row —
  found because the consistency gate flagged 13 rounding-level disagreements.
- **`features._gate` now asserts that `live_workload` supplies every key
  `fitted_curves.json` consumes**, and that live and build agree on age and
  home (218/218). This is the `comeback` bug turned into a gate: a curve
  fitted on a key live pricing never sets is silently dead.

### Net

| | start of session | now |
|---|---|---|
| curve layer, out of sample | −0.00170, 3/4 folds | **−0.00924, 4/4** |
| share of the 0.029 market gap | 5.9% | **31.9%** |
| curves | 3 | 6 |
| base model | 0.61791 | **0.61791** (three runs) |

The handoff's claim that "nothing derivable from the match log moves the
ordering gap" was wrong. What was true is that nothing moves it **as a linear
weight**. Both new curves describe a *trend* — how a player is changing —
which a decayed average of past performance structurally cannot represent at
any weight.

**The obvious next move is to fix the cause rather than the symptom**: an
age- or trend-dependent half-life in `weights.py`. `age` works because the
270-day decay lags; correcting that inside the estimator should dominate a
residual curve bolted on afterwards. Untested, and it is a change to the
estimator rather than a layer on top, so it needs the full gate/backtest/
compare cycle rather than the curve harness.

---

## Session 2026-09-09, part 4 — fixing the cause instead of the symptom

The `age` curve works because `ratings.fit_iterative` is an exponentially
weighted mean and an exponentially weighted mean lags a trend by roughly
`slope × half_life / ln 2`. Correcting that with a residual curve treats the
symptom. The obvious question is whether the estimator can stop producing the
error at all.

### The change

`fit_iterative` gained a `half_life_fn(pid)`. Each player's own history now
decays at their own rate — including inside the opponent-adjustment term,
which took some care: `sv_opp[a][b]` belongs to A's serve equation and carries
A's decay, `rt_opp[b][a]` belongs to B's return equation and carries B's, both
off the same match. Sharing one weight across both is only correct because the
two rates used to be equal.

The rate is `base × age_multiplier(age)`, piecewise linear through knots at
22, 28 and 34, pinned to 1.0 through the prime. Two free numbers. The knots
are fixed on purpose: three free parameters on 25,000 matches is a sweep, five
is a fishing trip.

### The result

Eleven configurations, each a full walk-forward, scored paired per match on
the intersection:

| m_young | m_old | vs baseline | paired t |
|---|---|---|---|
| 0.35 | 1.00 | −0.00143 | +3.59 |
| 0.50 | 0.70 | −0.00146 | +4.29 |
| 0.50 | 1.00 | −0.00123 | +4.50 |
| **0.70** | **0.85** | **−0.00087** | **+5.06** |
| 0.70 | 1.00 | −0.00076 | +5.27 |
| 0.85 | 1.00 | −0.00038 | +5.68 |
| 1.00 | 0.70 | −0.00022 | +1.22 |
| 1.00 | 0.85 | −0.00012 | +1.40 |
| 1.00 | 1.30 | +0.00028 | −2.07 |
| 1.30 | 1.00 | +0.00070 | −6.46 |

**Monotone across the entire grid, in both directions.** Shortening the young
half-life helps; lengthening it hurts at t = −6.46. That is about as clean a
confirmation of a proposed mechanism as this kind of study produces.

The magnitude is much less determined than the direction. The point estimate
was still improving at m_young = 0.35 while its t was falling — variance
catching up with bias — and everything from 0.35 to 0.85 is within noise.
Shipped (0.70, 0.85): interior to the grid, highest t among the configs that
meaningfully help, and it does not depend on the old-side lever being real,
which it may not be (t = 1.22 to 1.40).

**Only the main rating is age-decayed.** The surface-contrast fits keep their
1,095-day half-life. They measure a stable trait, and shortening a long-window
quantity to chase current form is precisely the error that once made
per-player surface ratings score worse than a tour-wide constant.

### Three consequences, none of them predicted

**1. Every other fitted parameter moved.** `backtest.py` refits everything
downstream, and it produced `form_scale` 0.85 → **0.70** and tour-wide
`form_sd` 0.040 → **0.035**. Shorter memory, tighter form distribution.

**2. Calibration flipped back ON**, at slope **0.966** — the model is now
*overconfident*, where before it was mildly underconfident and calibration
made things worse. The mechanism is direct: a shorter half-life for young
players means fewer effective points behind their ratings, noisier ratings
produce overconfident probabilities, and shrinking toward 0.5 now genuinely
helps (0.61434 → 0.61400). The switch was thrown by the backtest's own
measurement, which is exactly what rule 7 was rebuilt to allow.

**3. The headline log loss became incomparable.** The run reports 0.61400
against a previous 0.61791, and that comparison is **meaningless**: a shorter
young half-life means fewer young players clear `MIN_PTS = 1500`, so it scores
**27,395** matches where the old model scored **29,347** — a smaller and
easier subset. Raw log loss rewards shrinking the sample. This is the same
trap that made half_life 270 "beat" 1460 by 0.008 back in the tuning session,
and the caveat is now written into `fitted_params.json` beside the number so
nobody quotes it.

### It does not replace the curve

With the estimator fixed, the `age` curve falls from −0.00207 to −0.00154
alone, and its cost of dropping from +0.00427 to +0.00345. **About a quarter
of it was absorbed.** All six curves still earn their place, and the layer as
a whole delivers −0.00819 on the new estimator against −0.00924 on the old.

That is the right relationship. A multiplier at three fixed knots is a blunt
instrument; a six-bucket curve is not. The estimator fix also helps everywhere
the curves have no data to speak — a debutant with no 28-day history still
gets a correctly-short memory.

### The bug that ate an hour

The first run of the sweep produced **eleven identical configurations**, all
exactly the baseline. `tools/agehl.py` did `from load import BIRTHDAYS` at
module scope, and `load.fill_ages` ended with `BIRTHDAYS = birth` — a
**rebind**, not a mutation. The importing module kept a reference to the
original empty dict, every lookup missed, and every config silently fell back
to the global half-life. It read as a clean null result.

The tell was one line of diagnostic output that had been there all along:
`birthdays for 0 players`. `fill_ages` now does `.clear()` / `.update()`, and
the sweep refuses to start if `BIRTHDAYS` is empty.

### Still chosen rather than fitted

`MIN_PTS = 1500`, `SURFACE_HALF_LIFE = 1095`, `LONG_YEARS = 12`, and the
`AGE_KNOTS = (22, 28, 34)`. `MIN_PTS` is the most interesting of the four,
because it interacts with the half-life — it is the reason the headline number
moved — and because it is a pure scoring threshold that changes what gets
measured without changing the model at all. `tools/agehl.py` generalises to
any of them.

---

## Session 2026-09-10 — "does he play better against good players?"

The most natural question anyone asks about this model, and the one it was
structurally unable to answer. `ratings.fit_iterative` adjusts for the
opponent **additively**: a player's edge is assumed to be the same shift
whatever the opposition. `interactions.py` tests the opponent's *shape* and
deliberately strips their **level** out — its own docstring says "level is
what the base model handles". Whether the base model handles level *equally
well for every player* had never been looked at.

### Is it a trait at all?

Before building anything, the reliability. Per player, the slope of serve rate
on log10 opponent rank, halves split randomly by match, Spearman-Brown
corrected:

| quantity | players | split-half r | full-sample |
|---|---|---|---|
| serve level (control) | 294 | 0.873 | **0.932** |
| quality slope, ≥40 m | 294 | **−0.065** | — |
| quality slope, ≥100 m | 195 | 0.183 | 0.309 |
| quality slope, ≥250 m | 83 | 0.350 | **0.519** |

The control confirms the method: serve level is a trait and the measurement
says so loudly. The quality slope is **real but weak, and only for long
careers** — below 40 matches the halves are uncorrelated, so there is nothing
to shrink toward.

Return-side and all-points formulations were checked too: 0.34–0.38 at 100+,
0.38–0.54 at 250+. No version of the statistic is meaningfully better than the
serve slope, so nothing was left on the table by choosing it.

The **population** gradient is +0.02196 of serve rate per log10 rank — large,
real, and already handled by the opponent adjustment. Only the per-player
deviation from it is new information.

### It does not work, twice, for the same reason

**First attempt**, K = 40 shrinkage and a 20-match floor: **+0.00009**, hurts.
The bucket shape was an inverted U — both extremes negative, middle positive.
The natural reading was over-confident shrinkage.

**Second attempt**, K = 220 derived from the reliability table (one K fits
n = 60, 100 and 250, which is the evidence that n/(n+K) is the right form and
not just a convenient one), 50-match floor: **+0.00012**. Same shape.

A shape that survives a 5.5× change in shrinkage is not a shrinkage artefact.
The diagnosis: **the covariate is not a matchup quantity.** The two players in
a match land on opposite sides of it **47.6%** of the time — a coin flip. The
sign carries nothing; only the magnitude does.

### What the magnitude actually is

|vs_quality| alone gives a clean monotone curve worth −0.00011, and the
player-specific factor carries it rather than the lopsidedness of the match:
bucketing on |opponent distance from average rank| alone is non-monotone and
hurts (+0.00018).

So the honest reading is "this player fits the additive model badly" — a
model-fit signal, which belongs in `confidence.py`, not the price. Tested
there the way the bands were validated, thresholds set on the earlier half:

| group | n | realised log loss |
|---|---|---|
| fits well | 5,780 | 0.61246 |
| middling | 1,860 | 0.61466 |
| **fits badly** | **505** | **0.60999** |

The wrong way round, and non-monotone. A band that says "trust this less" has
to actually lose more. It does not.

### The last check, and why it failed too

Restricted to the population where the trait *is* reliable, the out-of-sample
number improves — −0.00049 at 250+ career matches, −0.00141 at 350+. Tempting,
and wrong: **every curve stays non-monotone** (at 350+: −0.0344, −0.0040,
+0.0015, −0.0168, +0.0089, −0.0099) and the gain grows as the sample shrinks.
That is a six-bucket curve finding structure in 3,745 test rows.

The contrast with `age` is the whole point. Age was monotone across all six
buckets, monotone in three independent eras, 9.3 SE end to end, and its gain
*grew* with the size of the effect rather than with the smallness of the
sample. That is what a real one looks like here.

### Why a real trait can be worth nothing

Reliability ~0.3 means about a third of the measured deviation is signal. That
third is then multiplied by a small opponent-distance term. What comes out is
a fraction of a percentage point on the price — below the noise floor of what
33,000 walk-forward matches can validate. The trait is real; the *usable* part
of it is not large enough to measure.

### Housekeeping this exposed

`features.build` had crept from 9.2s to **42.5s** over these sessions — every
rejected covariate scanning the player's full history once more per row. All
of them are now behind `features.EXTRA_FEATURES`, off in production and
switched on by `tools/curves.py build`, which is the only caller that needs
them. Production build is back to **16.2s**; the extra 7s over the original is
`form_spw`, which is adopted and earns it.

The adopted six are unchanged and all still earn their place on the rebuilt
cache: age +0.00345, form_spw +0.00167, matches_28d +0.00133, event_gwp
+0.00083, event_sets_lost +0.00019, home +0.00008.

---

## Session 2026-09-10, part 2 — the same question, three more ways

Asked again, so tried again, differently. Two things were wrong with the first
attempt and both are worth writing down.

**1. ATP rank is not the currency that matters.** The model has its own
opinion of who is good — the price it puts on the match. "Does he beat his
price more as an underdog than as a favourite" is the same question asked in
the units the model actually gets wrong.

**2. A career-long slope confounds the player's own trajectory.** An improving
player faces tougher fields later, when they are also serving better. That
manufactures a spurious "better against good players" slope out of nothing but
career progression. Never controlled for.

Fixing both required player ids in the residual cache, which it did not carry —
`confidence.py` has a comment apologising for their absence and works from
proxies. Added; a per-player slope cannot be estimated without them at all.

### Construction 2: win/loss against the model's own price

Per player, fit `P(win) = sigmoid(a + b·logit(p_model))`. The formulation
matters: a player whose rating is simply too high has p too high in *every*
match, which lands entirely in `a` and leaves `b` untouched. So `b` separates
"the rating is wrong" from "the model's opponent scaling is wrong for this
player" — which a rank-based slope cannot do.

Reliability: **−0.05 at 60+ rows, −0.02 at 120+, 0.17 at 200+.** Adding a
linear time term (the trajectory control) lifts it to 0.24 at 200+.

Essentially unmeasurable — and the reason is the thesis of the whole project.
A win is **one bit**; serve rate is seventy-five points. Construction 1 had
two orders of magnitude more information per observation. Section 02 of the
explainer, biting the hand that wrote it.

### Construction 3: serve rate against the model's own opponent rating

The synthesis — dense outcome, right axis. `interactions.residuals` already
computes exactly the residual needed; it keys it on opponent *style* with
level deliberately stripped out, so swapping level back in is a one-line
variant of gated machinery.

Reliability: **0.13 at 40+, 0.27 at 100+, 0.44 at 250+.** Better than
construction 2, still **worse than rank**. The likely reason is
errors-in-variables: the model's rating is itself estimated and refitted, so
regressing on it puts noise on the x-axis, which attenuates and destabilises
a slope. A smooth external rank does not have that problem.

### The comparison that settles it

`tools/reliability.py` now runs the check against two anchors — one quantity
that is indisputably a trait, and one the backtest independently fits to zero:

| quantity | 40+ | 100+ | 250+ |
|---|---|---|---|
| serve level *(anchor: real)* | 0.94 | 0.97 | 0.98 |
| slope on opponent LEVEL | 0.01 | 0.27 | **0.44** |
| slope on opponent STYLE *(anchor: fits to 0)* | 0.14 | −0.02 | **0.30** |

At 250+ matches the quality slope reaches 0.44 against style's 0.30. That is
not a separation. **"Plays better against good players" is about as measurable
as "handles big servers well"** — and `style_w` has fitted to exactly zero in
every backtest this project has run.

Reliability estimates carry their own sampling error; re-seeding the split
moves these by about ±0.05, which is the same order as the gap between the
two rows. That is the point.

### Verdict

Four constructions, the best of them the one already rejected last round, and
the ceiling sits where a known null sits. The trait is real for veterans and
too small to use. Stopping here.

### What came out of it anyway

- **Player ids in the residual cache.** `confidence.py` can stop guessing from
  proxies — it currently derives "thin data" from `matches_28d` because it has
  no id to look a player up with. Worth doing, not done here.
- **`tools/reliability.py`.** Rule 13 as a command. Against two anchors, so
  the answer is a comparison rather than a number needing interpretation. This
  is the thing to run *before* building the next per-player feature, and it
  would have saved both attempts at this one.

---

## Session 2026-09-10, part 3 — round in the tournament

Asked whether the round a match is played in affects performance, and to ship
it if so. It does not, three different ways, and the third is the interesting
one.

### 1. It cancels algebraically, not approximately

Both players in a match are in the same round. Every bucket of a round-based
curve therefore contains each match's winner *and* its loser in exactly equal
measure, and the mean residual is **identically zero**. The harness prints
`+0.0000` in every bucket of `round_order`, `wins_to_title` and `draw_size` —
four decimals of exactly nothing.

That is a proof, not a weak measurement, and it generalises: **no match-level
covariate can move an antisymmetric price.** Worth knowing before building
one. `tools/round_effect.py` already said so in a comment; now it is measured.

Round can therefore only enter as (a) a confidence input, where match-level is
exactly right, or (b) an interaction with something player-specific.

### 2. The raw gradient is large, clean, and meaningless

| stage | n | model log loss | mean \|p−.5\| |
|---|---|---|---|
| R128 | 912 | 0.60813 | 0.165 |
| R64 | 1,418 | 0.60950 | 0.170 |
| R32 | 2,381 | 0.60998 | 0.163 |
| R16 | 1,606 | 0.60966 | 0.173 |
| QF | 936 | 0.61824 | 0.173 |
| SF | 528 | 0.63329 | 0.161 |
| F | 291 | 0.63113 | 0.164 |

**+0.025 nats from first round to semi-final** — as large as the entire gap to
the market — and monotone in `wins_to_title`. Tightness is flat across the
whole table, so it survives the control that killed the first version of the
confidence bands. This looks like a finished feature.

### 3. And the market makes it vanish

Later rounds are harder for *everyone*. Deficit against Pinnacle closing, on
the 3,282 odds-joined matches:

| | n | deficit | t |
|---|---|---|---|
| early (R32 and before) | 1,970 | +0.03332 | 7.00 |
| late (QF and after) | 639 | +0.02471 | 3.06 |
| **difference** | | **−0.00861 ± 0.00938** | **−0.92** |

Flat within noise — and the sign says the model is if anything *better* deep
in a draw. Finals alone read +0.0503 at t = 2.45 on n = 99; one stage of seven
clearing 2 SE is what chance produces, and I would not report it as anything
else.

Independently, adding depth to the confidence bands made them separate
**worse**: spread +0.0234 → −0.0075.

**The lesson is the yardstick.** Raw log loss cannot distinguish "the model is
bad here" from "this is hard for anyone". Table 2 alone ships a "trust finals
less" term that is 100% intrinsic difficulty and 0% model error. Only a
control that faces the same matches — the market — separates them.

### The near-miss: a run of wins, signed by the price

`tools/round_effect.py` had the one real thing here: underdogs with wins
banked at an event beat their price (+0.0195, +3.7 SE) while favourites with
wins banked miss theirs. **Opposite signs** — which finally explains why
`event_matches` as a raw count fitted to zero. Pooled, the two halves cancel.

So the covariate has to be the interaction. Added a `DERIVED` mechanism to
`tools/curves.py` for covariates that combine a stored feature with the
model's own price, which `features.py` never sees, and defined
`run_vs_price = event_matches × (0.5 − p)`.

It scored −0.00015 alone, with clean sign structure, and **earned its place in
the set at +0.00014 on 4 folds of 4.** By every standard this project has used
it was adoptable.

**The control killed it.** `price_only = 0.5 − p` — the same thing with the
run removed — scores **−0.00030**, *better*, and its curve is a perfectly
antisymmetric shrink toward 0.5:

```
 -9 to -0.25   -0.0053
 -0.25 to -0.1 -0.0186
 -0.1 to 0     -0.0085
 0 to 0.1      +0.0085
 0.1 to 0.25   +0.0186
 0.25 to 9     +0.0053
```

That is the **calibration layer**, rediscovered as a curve. With both in the
set, both hurt (−0.00045, −0.00027) — the same collinearity signature as
home/home_km and age/rank_change.

`price.py` applies calibration at slope 0.966, and that slope was fitted by
`backtest.py` on a model with no curves. A p-shaped curve and the calibration
layer are substitutes: adopt one without refitting the other and you
double-count; refit and nothing is left.

**The general trap.** The residual cache is priced *before* calibration, which
is correct for fitting curves — production applies curves before calibration
too. But a covariate that is a **function of p** competes with a layer applied
*downstream* of the harness, so the harness cannot see the duplication.
`price_only` is the control to reach for whenever a candidate touches the
model's own price.

All six adopted curves still earn their place with `price_only` in the set, so
none of them is carrying calibration.

### Shipped

Nothing. `round` moves in `price.VARIABLES` from RECORDED to **IGNORED**, with
the reason attached, because "not fitted yet" wrongly implies it is waiting
its turn.

---

## Session 2026-09-10, part 4 — three structural changes

Asked for the four items from the "what are we missing" assessment. All four
have answers and three of them shipped. None is a new feature; each changes
what the model *is*.

| change | worth | paired t | tool |
|---|---|---|---|
| qual/Challenger supplement | **−0.00388** | +4.13 | `tools/qcthin.py` |
| in-event rating update | **−0.00267** | +6.82 | `tools/inevent.py` |
| three-stage serve | **−0.00195** | +12.32 | `tools/twostage.py --walk` |
| the last two together | −0.00407 | +8.90 | `tools/combo.py` |

For scale: the age-dependent half-life was −0.00087 and the whole six-curve
layer is −0.00819.

### The experiment that had to be run twice

The Challenger supplement measured **+0.00063 at t = −0.87** the first time: a
clean null. It was the experiment that was wrong, not the idea.

Rule 1 scores every config on the intersection of what each can price, and
the baseline can only price matches where both players clear MIN_PTS = 1500.
Those are the well-measured players — precisely the ones 105,000 Challenger
matches cannot help. The 16,138 matches the supplement makes newly scorable
are thin-player matches: the entire target population, discarded by the
intersection.

Lower the threshold to 300 so the baseline prices them too — badly, which is
the point — and the same data, same code, gives **−0.00388 at t = +4.13**.

That is now rule 13. Rule 1 says score on the same matches; it does not say
which, and the answer depends on who the change is for.

The level correction turned out not to matter: the sweep is flat in k
(−0.00063 to −0.00066 across k = 0 to 1), so the 2.5-point serve gap between
levels is handled by the opponent adjustment and what the supplement buys is
simply evidence.

Coverage: **27,395 → 43,533** scorable matches, rated pool **1,079 → 4,555**.

### A serve is three decisions

`w_1stIn`, `w_1stWon`, `w_2ndWon` have been in the file since the beginning
and the model collapsed them to one number.

The decomposition **cannot help by arithmetic alone** — Barnett–Clarke
consumes one probability per server, so recombining three stages with the
same expected rate gives an identical match probability, exactly as a round
curve cancels to zero. The whole gain is the *separate opponent adjustment
per stage*: a returner can be differentially good against second serves, and
a single additive number cannot express that at any weight.

Single split: −0.00428. Walk-forward with the real cadence, window, MIN_PTS
and both serve orders: **−0.00195 at t = +12.32** on 29,347 matches. The
largest t this project has produced.

In production the three stages supply the level and surface stays a delta on
top, so the empirical-Bayes surface machinery is untouched.

### Ratings that move inside a tournament

Refits are quarterly, so a player who had won three matches at an event
carried the rating they arrived with. `round_effect.py` had measured the cost
at +0.0195, 3.7 SE, for underdogs with wins banked.

The update is a shrinkage step on the **opponent-adjusted** residual, with
the rating's own effective sample size as the denominator — so a long record
barely moves, a thin one moves a lot, and no second parameter is needed.

The weight sweep has an **interior optimum**, unlike the age half-life where
the grid edge kept improving:

| w | vs w=0 | t |
|---|---|---|
| 0.5 | −0.00103 | +10.31 |
| 1.0 | −0.00183 | +9.18 |
| **2.0** | **−0.00267** | +6.82 |
| 4.0 | −0.00134 | +1.74 |

### The leak the date format invites

The archive dates a match by when its **tournament** started, so every round
of Wimbledon carries one date and "matches at this event before now" cannot
be written as a date filter. The first production version of `event_update`
priced a historical quarter-final using the final — an 8-point swing in the
test that caught it.

It now refuses to run historically without a round and caps on `ROUND_ORDER`.
Live there is nothing to guard: the log holds completed matches and the one
being priced has not happened. The measurement harness was correct
throughout, because it banked each match only after pricing it — which is
why the −0.00267 stands.

### Do they overlap?

88% additive. Three stages add −0.00140 on top of in-event; in-event adds
−0.00212 on top of three stages; the sum of the two alone is −0.00462 against
an actual combined −0.00407.

### Item 7: where the missing stats went

**They are genuinely absent at the source.** US Open 2026 (122 matches) and
Roland Garros 2026 (127) publish no serve statistics on tennisabstract; the
scrape emits them as results and `tools/ta/gate.py` still passes 373/373 on
reconstruction accuracy. 249 matches of two Grand Slams that cannot train the
ratings. Davis Cup ties have never carried stats in any year — structural,
not a failure.

Two real bugs turned up on the way:

* **`tools/ta/build.py` skipped Roland Garros entirely.** `CUT` was hardcoded
  to the archive's last tournament DATE. The mirror was snapshotted
  mid-tournament, so the archive held all 127 RG matches as results with every
  stat column blank — and the scraper skipped the event because "the archive
  already has it". The boundary event is exactly the one a mid-tournament
  freeze breaks. `CUT` is now derived from the last date the archive has
  *usable stats* for, so the next freeze cannot repeat it.
* **`load()` appended `manual_matches.csv` without deduplicating.** Harmless
  while the scrape only extended the archive; a double-count the moment it
  overlapped. The merge is now keyed, and the row carrying stats wins.

### Still not comparable

The headline `test_log_loss` has moved twice for set-composition reasons.
The age half-life shrank the scored set (29,347 → 27,395); the supplement
grew it (27,395 → 43,533). Elo on the same sets went 0.65631 → 0.65364 →
0.66494, which is the set getting harder, not Elo getting worse. The current
value is 0.61929 and it means nothing next to the old ones.

---

## Session 2026-09-10, part 5 — news as an input, and a website with a point of view

### The channel for what the log cannot see

Every injury proxy derivable from the match log has measured to zero —
retirements, walkovers, layoff length, comebacks — despite comeback matches
carrying double the market's deficit. The conclusion on file was blunt: the
model is wrong about who is better and *the market knows something the log
does not*. `news.py` is the channel for that something.

An assistant with a browser gets a prompt, returns strict JSON, and the JSON
becomes a rating shift in the same units as everything else. The schema is
deliberately small — `available`, fitness `severity` 0-3, `area`, `sourcing`,
and a little `context.direction` — because a large schema is a schema an
assistant fills in unreliably.

**Where it enters:** the same place and shape as the in-event update, a shift
to both ratings before the stage decomposition and before surface. The
serve/return split comes from *where* the injury is — a shoulder wrecks a
serve, an ankle wrecks court coverage — and is mechanical rather than fitted,
because there is nothing to fit it on. Decay is a 21-day half-life, halved
again once the player has completed two matches since the report: a player
who has since won twice is not the player the report described.

### Being honest about an unfittable weight

This is the first number in the project that is a **prior rather than a
measurement**, and the design had to make that unmistakable rather than
comfortable.

There is no archive of what the news said on the morning of each historical
match, so `news_w` cannot be swept the way `age_m_young` or `event_update_w`
were. What *can* be done is state the anchors in a unit a person can judge
and solve for them exactly rather than guessing near them. Against a stated
reference — median form_sd, even best-of-3, even serve/return split — the
multipliers were bisected until severity 1, 2 and 3 move the price by exactly
**2.0, 6.0 and 13.0 points**. Sourcing multiplies by 1.00 / 0.65 / 0.30.

The scaling by each player's own form_sd is not neutral and is worth saying
out loud: the same report moves a volatile player further than a metronome,
and best-of-five amplifies again, so a confirmed severity 3 on a volatile
player in a slam is a 20-point move. That is the intended behaviour — there
is less certainty about that player to begin with — but it is exactly why the
reference has to be stated instead of the anchors being described as "about".

**Every application is logged** to `data/news_applied.jsonl` with the price
and the shift. That file is the archive that does not exist yet; once a few
hundred matches carry news, it plus the results makes `news_w` measurable.
The feature ships with the route to its own validation built in.

Two smaller decisions worth recording:

* `available: false` makes `price.py` **refuse** rather than guess. A
  withdrawal is not a 95% favourite.
* News is reported **beside** the confidence band, never inside it. The
  band's measured deficits were fitted before this input existed, and folding
  an unmeasured term into a measured scale is precisely how the tightness
  mistake happened the first time.

### A bug that is becoming a pattern

`price.price` unpacks `sa, ra, na, wa, nsa = book.rating(a_id, surface)` — and
the news patch introduced `na, nb = nws.get(...)`, silently overwriting the
service-point count with a dict. It surfaced as
`'<' not supported between instances of 'dict' and 'dict'` in the confidence
band, three call frames away.

That is the third shadowing bug this project has had (`off` in the features
gate, `BIRTHDAYS` rebound at module scope, now `na`). Short names in long
functions are the common factor.

### The website

The browser view had drifted into a generic dark dashboard: slate ground, one
blue accent, everything in rounded cards with uppercase letterspaced labels,
one type size, an even grid of tiles. Competent and characterless.

Rebuilt around a specific reference — **an umpire's scorecard**. Paper ground
rather than slate, hairline rules rather than card borders, nothing rounded
except the two controls you actually press, and no shadows at all. The two
players sit on facing sides of a ruled spine with the probabilities set at
44px in tabular figures, the favourite carrying the single accent. Names are
set in a serif, data in mono, and the type scale actually varies instead of
everything sitting at 12px uppercase.

The tile grids became ruled stat rows, which suit a scorecard and also stop
every block from claiming equal importance. Headings are lowercase and small;
the interface says "the call", "games", "the player", "the model" rather than
"Price / Totals / Player / Model".

Two layout bugs fell out and are worth noting because both were invisible
until rendered: `#conditions` carries the `.controls` class as well as its own
id, so it inherited `flex-direction: column` and stacked every control into a
right-aligned pile; and `.bits` is a two-column CSS grid, which fills
row-major, so concatenating player A's five facts then player B's put A's
third line in B's column. Both needed the screenshot.

---

## Session 2026-09-11 — one derivation, one pricing path, and what the gate found

Next steps item 0: the harness and the CLI had diverged. The fix was
architectural — `weights.derive` is now the only derivation and
`price.serve_probs` the only matchup function, the harness prices through
both, and `backtest.py --gate` asserts a harness block equals `weights.json`
— and the gate paid for itself within the hour.

### Six divergences, three of them unrecorded

The handoff listed three (stages, in-event update, news). The code held
three more. The CLI derived form volatility on a 270-day half-life over ten
years while the harness used 1,095 days over twelve, so `form_scale` had been
fitted against numbers production never produced. The CLI priced a surface
match from the long-window surface rating alone — the exact substitution the
2026-09-08 session measured at t = −3.14 — while the harness carried the
recent form shift on top. And the CLI would price one player on a surface
split against another on the overall rating; the harness never had.

Measured in the unified path, the carry-over is worth **0.0155 nats at
t = 12.4**. It is the largest single layer in the model, and it had never
shipped.

### The gate's first run failed, and the reason was load order

Long-window and surface fits matched to 1e-16; the age-decayed fits differed
by hundreds of decayed points. The only age-dependent input is the birthday
table, and `fill_ages` rebuilt it from whatever `load()` had just parsed —
last call wins. `weights.build` finished with the 2013+ qualifying files'
birthdays, the harness with 2005+, and a player missing from the table got
the base half-life. `load.birthdays()` now scans the whole archive once
(26,300 players) into `data/birthdays.json`, keyed on the files. Rule 21.

### Rounds are alphabetical in several seasons

`F, QF, R128, R16 …` in file order for 2019 outright and ~2,000 rows a year
from 2020 on. `tools/inevent.py` and `tools/combo.py` banked in file order,
so a first-round price could contain the final. The in-event gain was
−0.00267 leaked and is **−0.00130 (t 4.9)** clean; the optimum is still
interior at w = 2. Rule 22.

### The three-stage serve does not survive company

First measurement in the unified path: **+0.0068** — because the stages were
fitted on main-tour rows while the overall rating had the supplement, so
2,000 Challenger-rated players had no stage rating and were priced at the
tour average. Fixed (supplement rows carry stage counts; a missing stage
rating falls back). Second measurement: **+0.00137 at t −6.50**. A layer
that was +12 t alone is −6.5 t beside the surface split and carry-over. It
ships off. Rules 23 and 24.

### An estimator that took fifteen minutes on one block

A poorly connected early block needed ~3,000 sweeps and the pure-Python loop
took 912 s on it. The sweep is two sparse matrix-vector products, now done
with `numpy.bincount`; the loop is kept as the reference and the estimator
gate asserts agreement to 1e-9. A walk-forward is now ~90 s. Every
measurement below was only possible because of this.

### The age half-life, with a real baseline

`tools/agehl.py`'s (1.0, 1.0) "baseline" had been running the shipped
multipliers (`half_life_fn=None` now means "what ships"). With an explicit
global half-life and the complete birthday table, on 41,809 common matches:
(0.85, 1.0) −0.00063 t 9.5; **(0.70, 0.85) −0.00135 t 8.3**; (0.50, 1.0)
−0.00178 t 6.5; (0.50, 0.70) −0.00189 t 5.7. Head to head (0.50, 0.70)
beats the shipped pair by 0.00054 at t 3.2 and prices 1,705 fewer matches.
Not adopted; recorded as the first live candidate. Rule 25.

### Everything else, re-measured on the shipped path

Supplement at MIN_PTS 300: −0.00450 (t 4.5). `form_scale` 0.70 → 0.60 (the
first fit landed on the grid edge at 0.50; the grid was widened — rule 26).
Calibration slope 0.999. Curves refitted on residuals from the shipped path:
−0.00871 at k = 1, 4/4 folds; the train halves all prefer k = 1.5
(−0.00948) — the second live candidate. All six curves keep their place; `age`
+0.00402 to drop. Confidence bands refitted. M4 re-run: +0.0249 (2025) and
+0.0302 (2024) before the curve layer.

### Headline

**0.61797** on 22,736 test matches, shipped path end to end, Elo 0.66323 on
the same set. Not comparable to anything before it.

### The news channel, in the right units

Asked how a fitness report should move a price. The old design expressed
severity as multiples of the player's own form_sd, so the same report moved
a volatile player further than a steady one — the epistemic lever mixed into
the physical one. A shoulder costs the same pace off a metronome's serve as
off anyone else's.

Now three levers, each in the unit that thing has: **level** in points of
serve and return rate (entering where the ratings do, so best-of, surface
and opponent still shape it), **uncertainty** as a multiplier on form_sd,
**retirement risk** as a probability folded in last (a retirement is a
loss). The model's own sensitivities anchor the prompt: 1 point of serve
rate off one player moves a coin-flip bo3 by 4.4 points of win probability
and a bo5 by 5.2; widening form_sd ×1.5 on a 57/43 favourite is worth half a
point. The assistant is asked for an `impact` block in those units; a report
without one falls back to severity anchors re-solved in absolute points so
that 1/2/3 still move the reference match by 2/6/13 points. Still a prior.

## Session 2026-09-11, later — the age pair, a seventh curve, and the candidates that lost

The morning entry left two live candidates — (0.50, 0.70) on the age pair
and k = 1.5 on the curves — and a loader that had never read four of the
archive's columns. Both candidates are closed below, one replaced by a
better pair and the other by a seventh curve, and the columns turned out to
hold one real variable that cannot ship yet. Every number is on the shipped
path; at ~90 s a walk the grids are complete rather than sampled.

### The age pair: nine configs, then head to head

The morning grid was four configs on 41,809 common matches. Re-run as nine,
against a single global half-life, on the 40,181 test matches every config
can price:

| m_young | m_old | vs global | t |
|---|---|---|---|
| 0.40 | 0.70 | −0.00163 | 3.86 |
| 0.40 | 0.85 | −0.00161 | 4.11 |
| 0.50 | 0.70 | −0.00163 | 4.75 |
| **0.50** | **0.85** | **−0.00183** | **6.32** |
| 0.50 | 1.00 | −0.00171 | 6.28 |
| 0.60 | 0.70 | −0.00143 | 5.06 |
| 0.70 | 0.85 | −0.00129 | 7.88 |
| 0.85 | 1.00 | −0.00060 | 9.09 |

The t column rises toward the smallest change, as it should; the gain
column is what ranks them. Against a global baseline everything looks good,
so the decision was made head to head against the previously shipped
(0.70, 0.85) on the same 40,181 matches: **(0.50, 0.85) −0.00053 at t 3.95**; (0.50, 1.00)
−0.00042 t 2.84; (0.50, 0.70) −0.00034 t 1.77; (0.40, 0.70) −0.00034
t 1.25; (0.40, 0.85) −0.00032 t 1.27; (0.60, 0.70) −0.00013 t 0.96. The
morning's candidate (0.50, 0.70) is third; its −0.00054 at t 3.2 was on a
different common set and does not hold on this one. The optimum is interior
in both directions — 0.40 on the young side is no better than 0.50 at lower
t, and 0.70 on the old side is worse than 0.85 — so (0.50, 0.85) ships.

What it costs is scorable matches, not accuracy: 42,169 at MIN_PTS 1500
against 43,514 under (0.70, 0.85), because a shorter young memory carries
fewer players over the threshold. The paired numbers above are on the
common set, so the 1,345 missing matches are a scoring artefact. The
headline moves with the set and is not comparable to the morning's.

### Four columns the loader never read

The archive lists each player's entry type (Q, WC, LL, PR), seed, hand and
own rank in every row, and `load.Match` had parsed none of them. It does
now; `features.build` emits `entry`, `seeded`, `log_rank`, `rank_gap` and
`opp_lefty`. Beside those, traits read from the residual cache itself:
`resid_prior`, the player's own mean walk-forward residual (y − p) over
their prior cached rows, shrunk by n/(n + 40), none until 15 prior rows,
rows of the same day never seeing each other — does this player beat the
point model; `bo5_resid_prior`, the same on best-of-five rows only;
`bo_diff_prior`; and `elo_vs_model`.

Reliability first (rule 17). A trait that does not agree with itself across
halves of a player's own rows cannot be a feature, whatever a split says.
Split-half r for `resid_prior` is **+0.243** across the 286 players with
40+ rows, **0.391** for the full sample; on best-of-five rows alone it is
+0.083 / 0.153 over 97 players, which is why `bo5_resid_prior` was expected
to lose before it was scored.

Single-split, each alone, on the morning's cache (57,404 player-rows):
rank_gap −0.00080, log_rank −0.00036, seeded −0.00032, entry −0.00014,
bo5_resid_prior −0.00037, bo_diff_prior +0.00005, elo_vs_model +0.00006 (a
perfectly antisymmetric ±0.022 curve that still hurts out of sample),
opp_lefty +0.00008. `resid_prior` alone on the final cache (55,642
player-rows = 27,821 matches, priced through the shipped path with
(0.50, 0.85)): −0.00128. The
entry buckets are the interesting ones: qualifiers +0.0195 (n 2,825),
protected ranking −0.011 (n 504), wildcards +0.011.

### The pool trap — rule 27

The first leave-one-out took the six shipped curves plus all six candidates
as one set. The twelve scored **0.61400** against **0.60912** for the six
alone — 0.005 worse — and every ranking-shaped candidate looked harmful,
including `rank_gap`, the best single-split number of the lot.
Near-substitutes cancel: leave-one-out on a pool of them charges each one
for the others' presence, and a set that contains the same signal four
times is worse than a set that contains it once.

The honest test is forward selection: add each candidate alone to the
shipped six, on the final cache, and read the change (`tools/curves.py add
<cands>`). resid_prior **−0.00166** adds; entry **−0.00047** adds; log_rank
−0.00012, not worth a stale live input; rank_gap **+0.00077** hurts; seeded
+0.00035 hurts; bo5_resid_prior +0.00007 hurts. Rule 27: a candidate pool is
not a forward selection. Add each alone to the shipped set, then
leave-one-out the result.

### resid_prior ships — the seventh curve

Leave-one-out on the seven, 4 folds of 4: the set is worth **−0.00941** at
k = 1 (the six on the same cache: −0.00775), and the cost of dropping each:

| curve | alone | to drop |
|---|---|---|
| age | −0.00167 | +0.00255 |
| resid_prior | −0.00128 | +0.00166 |
| matches_28d | −0.00120 | +0.00146 |
| event_gwp | −0.00079 | +0.00092 |
| form_spw | −0.00077 | +0.00074 |
| home | −0.00009 | +0.00018 |
| event_sets_lost | −0.00023 | +0.00016 |

`age` is still the largest. Its under-21 bucket reads +0.055 on the final
cache against +0.082 when the curve was first fitted, on the old harness's
residuals: the shorter young memory now carries part of what the curve
used to, and the curve still costs +0.00255 to drop. The six buckets:
+0.055, +0.035, +0.007, −0.013, −0.027, −0.033, still monotone.

The magnitude, re-checked with the seventh curve in: ×2 (k = 1) 0.60830,
×2.5 (k = 1.25) 0.60830 — a tie — ×3 (k = 1.5) 0.60919, ×4 0.61354. The
scale chosen on each fold's train half scores 0.60865 (−0.00906), worse
than k = 1. So k stays 1.0 and the morning's second candidate is closed: on
the six-curve set the train halves preferred k = 1.5 because the larger
magnitude was standing in for a trait the set did not have. "No new
tunable" holds.

The curve itself, shrunk: −0.039 for a trait below −0.04, through a flat
middle near −0.012, to +0.036 above +0.04. The extremes of the trait, live:
Flavio Cobolli +0.118 (n 173), Learner Tien +0.109 (101), Alexander Bublik
+0.106 (367), Ben Shelton +0.096 (219); Hugo Dellien −0.118 (88), Facundo
Bagnis −0.111 (117). A +0.118 means Cobolli has won twelve points of win
probability more than his priced serve and return rates said he would,
averaged over 173 rows and shrunk.

Plumbing: `tools/curves.py write` now also writes `data/player_traits.json`
(382 players); `live_workload` reads it, and the workload gate asserts live
pricing supplies all seven curve inputs. `tools/curves.py reliability` runs
the split-half check; `--k=` on `loo` and `write`; `TENNIS_EXTRA=1`
re-measures the rejected opponent-calibre covariates (`features.build` is
~2 min without it, ~15 min with), so a curves build is ~2 min, not 17.

### Entry type — real, and unknowable live. Rule 28

Entry is the one archive column that carried a real effect in company:
−0.00047 on top of the shipped six, qualifiers +0.0195 over 2,825 rows,
protected ranking (back from injury) −0.011 over 504. But a live price
cannot know a player's entry type before their first match at an event;
nothing the live path reads carries it. It waits for a draw source — a
`--entry Q|WC|LL|PR` flag on `price` and an app control, or a draw feed —
and then a re-run of `curves.py add` and `loo`. Not adopted. Rule 28: a
curve a live price cannot evaluate must not ship; the workload gate is what
enforces it.

### The refit

In the order the HANDOFF gives — gates, fit, backtest, `pathsweep all`,
`curves build / add / loo / write`, `confidence fit` — on 42,169 scorable
matches, one walk, train 20,157 / test **22,012**:

| rung | log loss | vs previous | t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo K=4, results only | 0.66253 | | |
| tour-wide single rating, form_sd 0.030 | 0.62198 | | |
| per-player surface + form (scale 0.60) | 0.61927 | | |
| + in-event update (w = 2) | 0.61730 | −0.00198 | 6.07 |
| + air density (w = 0.40) | **0.61720** | −0.00009 | 4.30 |
| + calibration | 0.61728 | +0.00008 | −2.87 |
| three-stage serve ON (measured, not shipped) | 0.61933 | +0.00213 vs shipped | −7.32 |

Headline **0.61720**, Elo 0.66253 on the same 22,012, a gap of 0.0453. Not
comparable to 0.61797 or anything before it.

Calibration goes back OFF. The measured slope is 1.012; on the tour-wide
single rating applying it helps (0.62181, −0.00017 at t 3.08), on the full
model it costs +0.00008 at t −2.87, because per-player form_sd already
absorbs the overconfidence the slope was fitted to fix. `calibration_b` is
1.0 with the measured value kept beside it.

Every knob flipped alone (`tools/pathsweep.py all`, test 22,012):
three-stage serve ON +0.00200 t −8.76; in-event update OFF +0.00170
t −5.60; both +0.00363 t −9.99; surface carry-over OFF **+0.01522
t −11.84**, still the largest layer; no surface split at all +0.00257
t −2.77. The in-event weight sweep (interior at w = 2) and the supplement
at MIN_PTS 300 (−0.00450, t 4.48) were measured this morning at
(0.70, 0.85) and not re-run.

The shipped configuration, as `fitted_params.json` has it:

| knob | value | knob | value |
|---|---|---|---|
| half_life_days | 270 | age (young, old) | 0.50, 0.85 |
| prior_weight | 150 | qc_supplement | on, k 1.0 |
| train_years / long_years | 5 / 12 | surface_carry | on |
| form_scale | 0.60 | event_update_w | 2.0 |
| form_sd (tour) | 0.030 | three_stage_serve | off |
| dens_w | 0.40 | calibration_b | 1.0 = off (measured 1.012) |
| news_w | 1.0, a prior | | |

2,747 rated players on the five-year window; the archive runs through
2026-08-31 with 80,144 tour matches and 104,806 qualifying/Challenger.

Confidence bands, refitted on the final residuals: GOOD 0.60156 (n 10,004),
FAIR 0.63789 (3,210), LOW 0.74742 (697). Monotone.

M4 against the Pinnacle closing line, before the curve layer. 2025: 2,375
matches, model 0.63019, closing (devigged) 0.60541, gap **+0.02477**. By
distance from the market: 0–2% n 413 +0.0008; 2–5% n 577 +0.0092; 5–10%
n 671 +0.0205; 10%+ n 714 +0.0553. 2024: 2,481 matches, model 0.61477,
closing 0.58547, gap **+0.02930**; 0–2% n 421 +0.0006; 2–5% n 627
+0.0024; 5–10% n 717 +0.0147; 10%+ n 716 +0.0843. The seven-curve layer
(−0.0094 walk-forward) is applied downstream of this, so the live gap is
roughly +0.015 to +0.02. Where the model is within 2% of the market it is
as good as the market; most of the gap lives in the matches where it
disagrees by 10% or more. Rescaling closes about 2% (M4-era).

### Where this leaves it

Both of the morning's candidates are closed. Entry type is the one open
candidate and waits on plumbing, not on measurement. The two things that
worked today are per-player and trend-shaped — a shorter young memory and
the player's own residual trait — and the 10%+ bucket is where the distance
from the market is. One housekeeping item: an `app.py --port 8765` from an
earlier session is still serving the old model and should be killed before
the browser view is opened.

## Session 2026-09-12 — entry type goes live, and the constants nobody had fitted

Yesterday closed with one open candidate, entry type, waiting on plumbing
rather than on measurement, and with a set of constants — the surface
half-life, the long window, the carry cap, the age knots, the refit cadence
— that had each been chosen once and never swept. Both are closed below.
Entry type is the eighth curve; three of the five constants stay where they
were, the carry cap moves a little, and the refit cadence is the largest
single gain of the day. Every sweep is paired on the intersection of what
its values price (rule 1); the curves are 4 folds of 4 as before.

### Entry type, live — the eighth curve

The first question was whether a live price could ever know it. The scraped
results feed carries no entry column: 847 rows since the mirror froze, none
with a code. So a live price learns it from the user or from the archive,
and from nowhere else. `tennis.py price` takes `--entry-a` / `--entry-b`
(main, Q, WC, LL, PR, SE); the prompt takes `entry a Q` and `entry off`;
the app has two selects, "A entered as" / "B entered as", which swap with
the players. When an archive row at the event already carries a code for
the player — a qualifier's second match — the price reads it from their
earlier rows. Otherwise the type is unknown and the curve applies no
adjustment. It is never guessed as "main draw".

With the flag in, rule 28 is satisfied — the workload gate asserts live
pricing supplies all eight curve inputs — and the measurement can follow.
Forward selection onto the shipped seven, final cache of 2026-09-11 (55,642
player-rows): **−0.00058**, adds. Leave-one-out on the eight: **+0.00058**
to drop. Alone −0.00013, which is why it never looked like much on a single
split; in company it earns its place because nothing else in the set
carries how a player got into the draw. Bucket shape on that cache, shrunk:
main draw −0.003, qualifiers +0.020 (n 2,825), wildcards +0.011, lucky
losers −0.011, protected ranking −0.003 (thin), special exempt +0.004.
Yesterday's entry put the −0.011 on protected ranking; on today's
measurement it is the lucky losers, and protected ranking is too thin to
hold a sign (in the refitted buckets below it reads +0.005 on 354 rows).

The eight-curve set on that old cache: −0.00999 at k = 1, 4 folds of 4;
×2.5 (k = 1.25) −0.01014, ×3 −0.00940, ×4 −0.00536; the scale chosen on
each fold's train half scores 0.60787 against 0.60771 at k = 1, so k stays
1. Those numbers were superseded within the day by the refit below; they
are recorded because they are the ones the adoption was decided on.

### Two trend traits that lost — substitutes for resid_prior

`resid_prior` is the player's mean residual over all their prior cached
rows. Two sharper versions of the same idea were measured, on the
hypothesis that a recent or surface-specific residual would carry more of
the trend: `resid_365`, the residual over the last 365 days only (K = 20,
none until 8 rows), and `resid_surface`, the residual on this row's surface
only. Alone each looks like a feature — resid_365 **−0.00131**,
resid_surface −0.00038. Added to the shipped seven, each hurts: resid_365
**+0.00092**, resid_surface **+0.00119**. Rule 27 again: a single split
scores the signal, forward selection scores what the signal adds, and both
are near-substitutes for the resid_prior the set already has — the larger
the alone number, the larger the overlap. Neither ships. Both are still
computed into `data/player_traits.json` (`resid_365`, `surf`) and supplied
live, so a later set can re-measure them without new plumbing.

### tools/knobsweep.py — the constants nobody had fitted

Five constants in the walk-forward had been chosen once and never swept,
because each is module-level and read at import, so varying one means a
fresh process. `tools/knobsweep.py run <knob> <values>` does exactly that:
one full walk per value in its own subprocess with the knob's `TENNIS_*`
variable set, cached as a pickle; `compare <knob>` scores every cached
value on the intersection of what they all price, fits form_scale on the
train half per value, and pairs each against the shipped value with a
per-match t. About ninety seconds a value at the 91-day cadence,
uncontended. Running five walks at once slowed each about five-fold — the
machine was the limit, not the code — so sweeps run three at a time
(`TENNIS_POOL=3`).

The overrides are `TENNIS_SURFACE_HL`, `TENNIS_LONG_YEARS`,
`TENNIS_CARRY_CAP`, `TENNIS_REFIT_DAYS`, `TENNIS_AGE_KNOTS`,
`TENNIS_TRAIT_K`, `TENNIS_TRAIT_MIN`. They exist for the sweep, not for
pricing; the backtest writeback now carries `carry_cap`,
`surface_half_life_days` and `refit_days` into `fitted_params.json`, so a
swept value survives the next refit (rule 7).

Three of the five are flat:

| knob | value | vs shipped | t | common |
|---|---|---|---|---|
| surface_half_life_days | 730 | +0.00015 | −0.74 | 42,169 |
| | **1095** | shipped | | |
| | 1460 | −0.00006 | +0.84 | |
| | 2190 | +0.00006 | −0.39 | |
| long_years | 8 | +0.00004 | −0.45 | 42,169 |
| | **12** | shipped | | |
| | 16 | +0.00004 | −0.95 | |
| AGE_KNOTS | (20, 26, 32) | +0.00044 | −2.94 | 40,960 |
| | **(22, 28, 34)** | shipped | | |
| | (24, 30, 36) | +0.00005 | −0.42 | |

Nothing there is distinguishable from the shipped value except the younger
age knots, which are worse. All three stay. That is a result in itself: the
surface memory, the long window and the age knots were guesses, and the
guesses are within noise of the best value on the grid.

The carry cap is not flat. Against 0.05 on 42,169 common matches: 0.03
**+0.00157** (t −3.98); 0.08 **−0.00047** (t +2.17); 0.10 −0.00049
(t 2.01); 0.12 −0.00051 (t 1.96); no cap −0.00053 (t 1.90). A plateau from
0.08 up — the gain barely grows and the t falls as the cap loosens — so the
smallest change with the highest t ships: **carry_cap 0.08**. A tighter cap
costs three times what a looser one gains, which says the recent-form shift
carried onto the surface rating is real and the old cap was clipping it.

The refit cadence is not flat either, and it is monotone. `REFIT_DAYS` was
91 by convenience — every walk in this notebook refitted the rating layer
four times a year. Paired against 91 on 40,374 common matches (21,378
test):

| refit_days | vs 91 | t |
|---|---|---|
| 182 | +0.00410 | −5.38 |
| 91 | shipped | |
| 45 | −0.00135 | +2.61 |
| 30 | −0.00252 | +4.54 |
| **21** | **−0.00413** | **+7.06** |

Still improving at the shortest value measured. A 14-day walk was started
(~550 refits) and abandoned for time; it is the next point to run. **21
ships**, the largest single gain of the day. form_scale refits to **0.50**
at 21 days, from 0.60: fresher ratings need less volatility on top, which
is the cadence gain read from the other side. Cost: a 21-day walk is ~370
refits against ~85 at 91 days, a few minutes uncontended.

Rule 29: a walk-forward's refit cadence is a model parameter, not a
convenience. It decides how stale every rating is between refits, and the
live tool refits whenever `weights.json` is rebuilt, so a short cadence is
also the closer description of what ships. Every headline before today was
measured with ratings up to 91 days stale.

### The refit

In the order the HANDOFF gives — gates, fit, backtest, `pathsweep all`,
`curves build / add / loo / write`, `confidence fit` — at carry cap 0.08
and the 21-day cadence, on 42,838 scorable matches, one walk, train 20,494
/ test **22,344**:

| rung | log loss | vs previous | t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo K=4, results only | 0.66283 | | |
| tour-wide single rating, form_sd 0.030 | 0.61808 | | |
| + calibration (slope 0.998) | 0.61807 | −0.00001 | 2.13 |
| per-player surface + form (scale 0.50) | 0.61497 | | |
| + in-event update (w = 2) | 0.61305 | −0.00191 | 5.82 |
| + air density (w = 0.40) | 0.61297 | −0.00009 | 3.78 |
| + calibration (slope 0.997) | **0.61295** | −0.00002 | 2.43 |
| three-stage serve ON (measured, not shipped) | 0.61517 | +0.00221 vs shipped | −7.56 |

Headline **0.61295**, Elo 0.66283 on the same 22,344, a gap of 0.0499. Not
comparable to yesterday's 0.61720: that was 22,012 test matches at the
91-day cadence, and both the scorable set and the cadence moved. The honest
number for what the cadence did is the paired one above, −0.00413 at t 7.06
on 40,374 common matches.

Calibration goes back ON, and it hardly matters. Yesterday's measured slope
was 1.012 and cost +0.00008 on the full model; on fresher ratings the slope
is **0.997**, and applying it is worth −0.00002 at t 2.43 — the right sign,
three parts in a thousand from identity. It ships because it is measured
and helps, not because any price will move.

Every knob flipped alone (`tools/pathsweep.py all`, test 22,344, 21-day
cadence): three-stage serve ON +0.00206 t −8.65; in-event update OFF
+0.00164 t −5.35; both +0.00355 t −9.52; surface carry-over OFF **+0.01531
t −11.35**, still the largest layer; no surface split at all +0.00314
t −3.43. The ordering is yesterday's; the surface split itself reads
+0.00314 against +0.00257 with the fresher ratings.

The shipped configuration, as `fitted_params.json` has it:

| knob | value | knob | value |
|---|---|---|---|
| half_life_days | 270 | age (young, old) | 0.50, 0.85 |
| prior_weight | 150 | AGE_KNOTS | 22, 28, 34 |
| train_years / long_years | 5 / 12 | qc_supplement | on, k 1.0 |
| surface_half_life_days | 1095 | surface_carry | on, **carry_cap 0.08** (was 0.05) |
| **refit_days** | **21** (was 91) | event_update_w | 2.0 |
| form_scale | **0.50** (was 0.60) | three_stage_serve | off |
| form_sd (tour) | 0.030 | calibration_b | **0.997, on** (was 1.0 = off) |
| dens_w | 0.40 | TRAIT_K / TRAIT_MIN | 40 / 15 |
| news_w | 1.0, a prior | | |

The correction layer, eight curves, refitted on the new cache
(`tools/residuals.json` rebuilt at the 21-day cadence), k = 1.0. Alone
(single split) and the cost of dropping (leave-one-out, 4 folds of 4):

| curve | alone | to drop |
|---|---|---|
| age | −0.00126 | +0.00185 |
| resid_prior | −0.00086 | +0.00153 |
| matches_28d | −0.00092 | +0.00144 |
| event_gwp | −0.00077 | +0.00087 |
| entry | −0.00014 | +0.00051 |
| form_spw | −0.00055 | +0.00048 |
| event_sets_lost | −0.00019 | +0.00018 |
| home | −0.00007 | +0.00013 |

The set is worth **−0.00807** at k = 1 (×2.5 −0.00818; ×3 −0.00756; ×4
−0.00421; the scale chosen on each fold's train half scores 0.60552 against
0.60522 at k = 1, so k stays 1). It was −0.00999 on the old cache. The
layer shrank because fresher ratings absorb part of what the curves
corrected — the expected direction, and the same thing the age half-life
did to the age curve yesterday. Every curve still earns its place: all
eight cost something to drop.

Age buckets on the new cache, shrunk: +0.049 (n 3,709), +0.029 (9,520),
+0.006 (13,798), −0.012 (14,120), −0.022 (8,705), −0.028 (6,730), still
monotone; youngest minus oldest **+0.078**, against +0.097 yesterday and
+0.123 before the age half-life. Entry buckets, shrunk: main draw −0.002
(n 46,715), Q **+0.023** (5,588), WC −0.003 (2,497), LL **−0.020** (1,177),
PR +0.005 (354, thin), SE +0.003 (186). Qualifiers beat their price by 2.3
points; lucky losers miss it by 2. resid_prior runs −0.035 below −0.04 to
+0.036 above +0.04, monotone. `data/player_traits.json` carries 384
players.

Confidence bands, refitted on the final residuals: GOOD **0.59677**
(n 10,181), FAIR 0.63391 (3,251), LOW 0.74335 (714). Monotone, and each
band lower than yesterday's on its new set.

M4 against the Pinnacle closing line, final configuration, before the
curve layer. 2025: 2,379 matches, model 0.62631, closing (devigged)
0.60379, gap **+0.02252** (was +0.02477). By distance from the market:
0–2% n 462 +0.0000; 2–5% n 605 +0.0090; 5–10% n 685 +0.0216; 10%+ n 627
+0.0531. 2024: 2,499 matches, model 0.60989, closing 0.58606, gap
**+0.02382** (was +0.02930); 0–2% n 450 −0.0015; 2–5% n 651 +0.0037; 5–10%
n 774 +0.0143; 10%+ n 624 +0.0750. Both years better than yesterday, on
slightly different match counts; 2024 by half a point. The eight-curve
layer (−0.0081 walk-forward) is applied downstream of this, so the live
gap is roughly +0.014 to +0.016. Within 2% of the market the model is the
market; the distance is still in the 10%+ bucket.

All six gates pass: live pricing supplies all eight curve inputs, and the
harness derivation equals `weights.json`. Rebuilt today, in order:
`weights.json`, `fitted_params.json`, `tools/_pathsweep/all.json`,
`tools/residuals.json`, `fitted_curves.json` with
`data/player_traits.json`, `confidence_model.json`.

### Where this leaves it

The three things that worked this week are per-player and trend-shaped —
the young memory, the residual trait — or structural, the cadence. The 10%+
bucket is where the gap lives, and nothing today moved it below +0.05.
Next: the 14-day cadence point (~550 refits, the one walk that was
abandoned); a draw feed, so entry type is known without asking; and a sweep
of TRAIT_K / TRAIT_MIN (40 / 15) for resid_prior with `TENNIS_TRAIT_K` on
the cache — in memory, cheap, and the last constants that were chosen
rather than fitted. Further out, in the direction of what worked: a
per-player refit cadence or per-player prior weight. Totals odds and the
news_w fit wait unchanged. The stray `app.py --port 8765` from an earlier
session is still serving the old model and should be killed.

## Session 2026-09-12, part 2 — the cadence to seven days, and a browser view that needs no manual

The morning entry shipped 21 days and left the 14-day walk abandoned for
time. The late session ran it, and then kept going: 14 paired against 21,
7 against 14, 3 against 7, each step against the value that had just
shipped, with the chain rebuilt twice on the way — once at 14 and again at
7. **Seven ships.** Three is measured, real and not adopted, for a reason
that is now rule 30. The other half of the session rebuilt the browser view
around the one thing a person actually does with it — type a name, press
Enter, twice — and made its model tab read the files the refit writes
instead of numbers typed into the page, which had gone stale within a day.
The 7-day chain ran past midnight, so the dates written inside
`data/market_check.json` said the 13th (the 2026-09-14 refit has since
overwritten them).

### The cadence, one step at a time

`tools/knobsweep.py` as this morning: one walk per value in its own
subprocess, scored on the intersection of what the values price, form_scale
fitted on the train half per value, a per-match t. Each step was paired
against the value that had just shipped rather than against 91, so that
each number is the gain of the next halving and not the distance from a
baseline nobody would ship again:

| step | vs shipped | t | common / test |
|---|---|---|---|
| 14 vs 21 | −0.00074 | +2.74 | 41,816 / 21,902 |
| 7 vs 14 | −0.00080 | +3.72 | 41,803 / 21,899 |
| 3 vs 7 | −0.00023 | +5.38 | 41,801 / 21,898 |

All at carry cap 0.08. The step is flat from 21 to 7 — the second halving
is worth as much as the first — and shrinks to a third of that at 3, at the
highest t of the three because the two walks differ least. form_scale
refits to 0.50 at every cadence from 21 days down (0.60 at 91): fresher
ratings need less volatility on top, and below 21 days the amount stops
changing.

The full ladder against the shipped 7, on the 41,801 matches all five
values price (train 19,903 / test 21,898):

| refit_days | form_scale | test log loss | vs 7 | t | scorable alone |
|---|---|---|---|---|---|
| 3 | 0.50 | 0.61089 | −0.00023 | +5.38 | 43,003 |
| **7** | **0.50** | **0.61112** | shipped | | 42,997 |
| 14 | 0.50 | 0.61192 | +0.00080 | −3.72 | 42,901 |
| 21 | 0.50 | 0.61266 | +0.00154 | −5.49 | 42,838 |
| 91 | 0.60 | 0.61672 | +0.00560 | −9.30 | 42,169 |

Monotone the whole way, and 91 to 7 is worth 0.0056 nats on the same
matches — a constant nobody had swept, sitting behind only the surface
carry-over (0.015) and the eight-curve layer (0.0074) among the things this
model is made of. The last column is why no two headlines this week are
comparable: the scorable set grows as the cadence shortens, 42,169 at 91
days to 43,003 at 3, so a headline moves with the set as well as with the
model. Cost: 392 s contended for the 7-day walk — six and a half
minutes — and 598 s for the 3-day one. I had guessed ~1,100 and ~2,500
refits from the span; the logs say 633 and 708. The harness refits on the
first tournament day at or past the due date, and tournaments start weekly,
so a 3-day cadence buys only the mid-week starts (72 refits at 91 days,
258 at 21, 372 at 14) — which is also why 3 costs half again as much as 7
rather than twice, and gains a fifth as much.

**7 ships.** 3 is measured, real — t 5.4 is not noise — and not adopted.
The gain is 0.0002 nats, and the cadence is a promise, not a knob: the
headline only holds if the live ratings are refreshed at that cadence,
which means `update.py` on that schedule, and the results mirror is frozen
with 847 rows scraped since. Weekly is the cadence this tool can actually
keep. Switching later is one refit chain — `refit_days` in
`fitted_params.json`, or `TENNIS_REFIT_DAYS=3` — and nothing else.

Rule 30: the refit cadence is also a commitment. The measured number
assumes the shipped ratings are never staler than the cadence, so ship the
cadence you will actually refresh at. Rule 29 made the cadence a model
parameter; this is the other half of it — a parameter the data feed has to
keep, or the headline describes a tool that does not exist.

### Two chains, and what moved

The chain in the HANDOFF order — gates, fit, backtest, `pathsweep all`,
`curves build / loo / antisym / fit / write`, `confidence fit`, `m4` for
both seasons, gates again — was started at 14 days with the 7-day walk
running beside it; 7 was paired against 14 before that chain had finished,
and the chain was started again at 7 the minute it had, with the 3-day walk
running beside that one. The 14-day state, for the record, since it was
superseded the same evening: train 20,516 / test 22,385 on 42,901 scorable,
headline **0.61227**, Elo 0.66292, calibration OFF by its own test (0.61227
uncalibrated against 0.61230 calibrated); against the closing line, 2025 on
2,386 matches, model 0.62606 / closing 0.60405, gap +0.02201, and 2024 on
2,500, 0.60912 / 0.58587, gap +0.02325. All six gates passed.

At 7 days, on 42,997 scorable matches, one walk of 506 s, train 20,577 /
test **22,420**:

| rung | log loss | vs previous | t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo K=4, results only | 0.66291 | | |
| tour-wide single rating, form_sd 0.030 | 0.61667 | | |
| + calibration (slope 1.015) | 0.61674 | +0.00007 | −1.92 |
| per-player surface + form (scale 0.50) | 0.61330 | | |
| + in-event update (w = 2) | 0.61148 | −0.00182 | 5.62 |
| + air density (w = 0.40) | **0.61140** | −0.00008 | 3.43 |
| + calibration (slope 1.012, measured, not shipped) | 0.61147 | +0.00007 | −2.32 |
| three-stage serve ON (measured, not shipped) | 0.61370 | +0.00229 vs shipped | −7.95 |

Headline **0.61140**, Elo 0.66291 on the same 22,420, a gap of 0.0515 —
wider than 0.0499 at 21 days and 0.0453 at 91. Not comparable to 0.61295
(22,344 test at 21 days) or to 0.61227 (22,385 at 14): the scorable set
moves with the cadence, and the paired steps above are the honest numbers
for what the cadence did.

Calibration is OFF again. The measured slope is back at 1.012 (1.015 on the
tour-wide rating), and applying it costs +0.00007 at t −2.32 on the full
model — this time it hurts the tour-wide rung too, +0.00007 at t −1.92.
That is the third flip in three sessions, every one of them on a slope a
few parts in a thousand from identity: per-player form_sd absorbs what the
slope was fitted to fix, and the knob will keep changing sign with the
noise. `calibration_b` is 1.0 with the measured value kept beside it.

Every knob flipped alone (`tools/pathsweep.py all`, 42,997 matches, test
22,420, one walk over six configurations): three-stage serve ON +0.00209 t
−8.92 (+0.00206 at 21 days); in-event update OFF +0.00159 t −5.27
(+0.00164); both +0.00359 t −9.89 (+0.00355); surface carry-over OFF
**+0.01508 t −11.28** (+0.01531), still the largest layer; no surface split
at all +0.00329 t −3.63 (+0.00314). Same ordering as at 21 and at 91, and
the split itself has grown with each shortening of the cadence: +0.00257 at
91, +0.00314 at 21, +0.00329 now. The sweep took 3,711 s — an hour, against
231 s for the same six paths at 14 days, which the cadence alone does not
explain. Noted, not investigated.

The shipped configuration, as `fitted_params.json` has it:

| knob | value | knob | value |
|---|---|---|---|
| half_life_days | 270 | age (young, old) | 0.50, 0.85 |
| prior_weight | 150 | AGE_KNOTS | 22, 28, 34 |
| train_years / long_years | 5 / 12 | qc_supplement | on, k 1.0 |
| surface_half_life_days | 1095 | surface_carry | on, carry_cap 0.08 |
| **refit_days** | **7** (was 21) | event_update_w | 2.0 |
| form_scale | 0.50 | three_stage_serve | off |
| form_sd (tour) | 0.030 | calibration_b | **1.0 = off** (measured 1.012; was 0.997, on) |
| dens_w | 0.40 | TRAIT_K / TRAIT_MIN | 40 / 15 |
| news_w | 1.0, a prior | curves | eight, k 1.0 |

`fitted_params.json` now also carries `test_matches` (22,420) and
`elo_log_loss` (0.66291), written by `backtest.py` for the app's model tab,
and the `*_note` strings for refit_days, test_log_loss, three_stage,
event_update, surface_carry, curves and knob_sweep carry the 7-day numbers
with the 21-day ones kept as history.

The correction layer, eight curves, refitted on the new cache
(`tools/residuals.json` rebuilt at the 7-day cadence, 56,754 player-rows),
k = 1.0. Alone (single split) and the cost of dropping (leave-one-out, 4
folds of 4):

| curve | alone | to drop |
|---|---|---|
| age | −0.00127 | +0.00183 |
| resid_prior | −0.00091 | +0.00152 |
| matches_28d | −0.00077 | +0.00118 |
| event_gwp | −0.00074 | +0.00086 |
| entry | −0.00014 | +0.00049 |
| form_spw | −0.00031 | +0.00029 |
| event_sets_lost | −0.00019 | +0.00019 |
| home | −0.00006 | +0.00011 |

The set is worth **−0.00735** at k = 1, 4 folds of 4 — no curves 0.61161,
with them 0.60426 (×2.5, k = 1.25, −0.00752; ×3 −0.00706; ×4 −0.00427; the
scale chosen on each fold's train half scores 0.60440 against 0.60426 at
k = 1, so k stays 1). The layer was −0.00999 at 91 days, −0.00807 at 21,
−0.00774 at 14: it shrinks with every shortening of the cadence, because
fresher ratings absorb part of what the curves were correcting — the
expected direction, and the same thing the age half-life did to the age
curve two days ago. Every curve still earns its place: all eight cost
something to drop, home by the least at +0.00011.

Age buckets on the new cache, shrunk (under 21, 21–24, 24–27, 27–30,
30–33, 33+): +0.047 (n 3,730), +0.029 (9,576), +0.006 (13,831), −0.012
(14,146), −0.021 (8,720), −0.028 (6,751), monotone; youngest minus oldest
**+0.075**, against +0.078 at 21 days, +0.097 at 91 and +0.123 before the
age half-life. Entry buckets, shrunk: main draw −0.002 (n 46,813), Q
**+0.023** (5,619), WC −0.004 (2,526), LL **−0.018** (1,182), PR +0.005
(362, thin), SE −0.004 (186). Qualifiers beat their price by 2.3 points;
lucky losers miss it by 1.8. resid_prior runs −0.032 below −0.04 to +0.035
above +0.04, monotone apart from a flat middle. `data/player_traits.json`
carries 384 players.

Confidence bands, refitted on the final residuals: GOOD **0.59458**
(n 10,227), FAIR 0.63616 (3,252), LOW 0.74471 (710). Monotone; GOOD is
lower than at 21 days (0.59677), FAIR and LOW a little higher (0.63391,
0.74335), each on a slightly different set.

M4 against the Pinnacle closing line, final configuration, before the curve
layer — and now also written to `data/market_check.json` for the app. 2025:
2,388 matches, model 0.62533, closing (devigged) 0.60373, gap **+0.02159**
(was +0.02252 at 21 days, +0.02201 at 14). By distance from the market:
0–2% n 480 −0.0003; 2–5% n 629 +0.0096; 5–10% n 677 +0.0244; 10%+ n 602
+0.0484. 2024: 2,512 matches, model 0.60784, closing 0.58556, gap
**+0.02228** (was +0.02382, +0.02325); 0–2% n 475 −0.0001; 2–5% n 672
−0.0001; 5–10% n 768 +0.0176; 10%+ n 597 +0.0712. The gap has closed a
little at every cadence step, in both seasons. The eight-curve layer
(−0.0074 walk-forward) is applied downstream of this, so the live gap is
roughly +0.014. Within 2% of the market the model is the market, and in
2024 within 5%; the distance is in the 10%+ bucket, +0.048 and +0.071.

All six gates pass at the end of the chain — simulator against the exact
recursion, estimator recovery and no leakage, data integrity and the tour
average, name resolution and line parsing, workload derivation (live
pricing supplies all eight curve inputs), and the harness derivation equal
to `weights.json` — and the log ends `ALL GATES PASS`. Every earlier chain
today passed the same six. Rebuilt, in order: `weights.json`,
`fitted_params.json`, `tools/_pathsweep/all.json`, `tools/residuals.json`,
`fitted_curves.json` with `data/player_traits.json`,
`confidence_model.json`, `data/market_check.json`.

### The app, rebuilt around "type a name, Enter, twice"

The browser view of 2026-09-09 had every control the CLI has and needed the
README to use: a roster to scroll, a data filter that hid the player you
were looking for if their rating was thin, and a model tab whose numbers
were typed into the page and wrong by the next refit. Rebuilt (`app.py` +
`web/`) so that the first thing a person does is the only thing they have
to know:

* **The search box.** Enter picks the highlighted match into the next empty
  slot — the slot marked "next" — ↑↓ move the highlight, Esc clears. A
  typed name searches *everyone*: the data filter no longer hides the
  player you asked for, and a rating under the threshold is marked "thin
  data" instead of dropped. Same resolver as the CLI.
* **A guided empty state**, three lines and a "show me an example" button
  that loads the two highest-rated players on file.
* **A one-line reading under the call** — "Sinner 60.7%, a lean — fair odds
  1.65; confidence LOW" — with "copy the call".
* **Naming a tournament sets surface and best-of** from the archive's most
  recent edition at that venue (`State._venue_hints`, keyed like the venue
  list), with a note saying so — "clay, best of 5 — as last played there" —
  and both can be changed.
* **Bookmaker odds, A and B.** `price.market_view()`, new in `price.py`,
  removes the margin proportionally — the same devig `tools/odds/m4.py`
  scores against — and the page shows the market's opinion, the model's,
  and the difference in points, with the measured caveat printed beside it:
  the model is about 0.02 nats *behind* closing and all of that gap lives
  in confident disagreement, so a large difference is a question, not an
  edge. Compared with the call, never used in it.
* **The address bar carries the match**
  (`#a=&b=&surface=&best_of=&at=&entry_a=&entry_b=&odds_a=&odds_b=`),
  restored on load, so a reload or a pasted link comes back to it.
* **A phone layout** at 760 px and under: the index sits above the match
  and folds away once both players are in; "change players" brings it
  back.
* **"the model" tab reads the files the refit writes** — `test_log_loss`,
  `elo_log_loss`, `test_matches`, `refit_days`, `carry_cap` from
  `fitted_params.json`, the market check from `data/market_check.json`.
* Smaller: the CSS variable names `--a`, `--warn` and `--dimmer` that
  `app.js` used never existed and were fixed; the player page shows the
  player's own residual against the point model (resid_prior) and the entry
  code when the archive has it; `.claude/launch.json`, so the app can be
  previewed; the stray `app.py` on :8765 from an earlier session, still
  serving an old model, was killed, and the server restarted on the final
  model after the refit.

The rule from 09-09 held: **the page computes nothing.** Everything that
could have been three lines of arithmetic in the page went into the tool
instead — `market_view` lives in `price.py`, the venue hints in `State`,
and the model tab reads the fitted files. That last one is the lesson of
the day in miniature: the tab used to carry its numbers typed in, and four
refit chains in two days left every one of them stale within a day of being
written. So `backtest.py`'s writeback now carries `elo_log_loss` and
`test_matches` beside `test_log_loss`, and `tools/odds/m4.py` writes
`data/market_check.json` per season — n, model, closing, gap, and the
buckets by |model − closing| — every time a season is scored. Rule 7 with a
page on the end of it: one derivation, and the page reads it.

Two fixes to the HANDOFF and README from the earlier audit were made by
hand: the entry-bucket parenthetical in the 2026-09-11 candidates section
(Q +0.020, n 2,825; WC +0.011; LL −0.011; PR −0.003, thin; SE +0.004), and
README's app section, rewritten for the new controls.

### Where this leaves it

The cadence is settled at the value the feed can keep, and the things that
moved the number this week are the same two kinds as before: per-player
and trend-shaped — the young memory, the residual trait — or structural,
the cadence. The 10%+ bucket is where the gap lives; in 2025 it has sat
between +0.047 and +0.056 all week, in 2024 never under +0.07.

0. Refresh weekly: `python3 update.py`, then `python3 tennis.py fit` or the
   chain. The 7-day cadence is a commitment (rule 30). If the feed ever
   supports it, 3 days is measured and one chain away.
1. In the direction of what worked: a per-player refit cadence or a
   per-player prior weight; a draw feed, so entry type is known without
   asking.
2. Totals odds, the unchanged blocker.
3. Fit `news_w` from `data/news_applied.jsonl` once a few hundred matches
   carry news.
4. Sweep TRAIT_K / TRAIT_MIN (40 / 15) with `TENNIS_TRAIT_K` on the cache —
   in memory, cheap, and the last constants chosen rather than fitted.
5. Or accept it as a study.

## Session 2026-09-14 — the weekly refresh, entry codes from the feed, and a player-specific prior

The 09-12 entry closed with the cadence settled at seven days and a list:
refresh weekly, sweep the last two chosen constants, a per-player prior
weight, a draw feed. Today did the refresh first, because rule 30 says the
headline is only true if it happens; then found that the draw feed had been
in the results page all along and `build.py` was throwing it away; swept
TRAIT_K / TRAIT_MIN and found them flat; and replaced the tour-average
prior with the player's own long-window rating, which is the one change of
the day that moved the number — and, on the way to measuring it, found that
a sweep can come back four times identical and look flat when it is broken.
The chain ran 22:52 to 23:18 on the 14th, about 25 minutes uncontended.

### The weekly refresh — rule 30, honoured

`python3 update.py` at 21:57. The Sackmann mirror is still dead — snapshot
8373358735, "already up to date -- nothing new upstream", a no-op — so the
new matches come from tennisabstract.com: `tools/ta/refresh.py` fetched 427
player pages and rebuilt `data/manual_matches.csv`. **969** rows (was 965),
**782** with full serve stats (was 701), dated 2026-05-25..2026-08-31 — the
US Open is dated by its start (rule 14) and now has 127 rows, 91 with
stats. Coverage by event: Wimbledon 123 of 126, Canada and Cincinnati 94 of
95 each, Winston-Salem 47 of 47, the US Open 91 of 127; Roland Garros 0 of
118 — results but no stat lines. The weather cache was extended to
2026-09-14: 110 of 110 venues, six days each, 6,101 days per venue.
Provenance re-verified, since the mirror is third party: 80,150 matches
2000–2026, 0 unparseable; 73,014 (91.1%) pass the arithmetic identities;
tour average serve 0.6320, Grass > Hard > Clay; **VERIFY PASS**. One cached
rating book invalidated; `matchgrid.npz` kept, it depends on the rules and
not the data. The 7-day cadence is a commitment (rule 30), and this is the
first refresh since it became one: the live ratings were rebuilt on the
refreshed archive inside the seven days the headline assumes. Then the whole
chain, `tools/refit_chain.sh` — but after the sweeps below, because the
prior changed what the chain fits and the chain is the expensive step.

### Entry codes were in the feed all along

Two days ago I wrote that the results feed carries no entry column — 847
rows since the mirror froze, none with a code — and built the flag, the
prompt command and the two selects around that. Wrong about the feed, right
about the file. Tennis Abstract prints each player's draw prefix in the
result cell exactly as the archive records it — "(10)Jacquet",
"(Q)Jacquet", "(WC)Gabriel Diallo [CAN]", "(LL)", "(Alt)" — and
`tools/ta/build.py` had been stripping it in `clean()` on the way to a
name, together with the country tag. The column was empty because the
builder emptied it.

Now `build.prefix_of()` reads the prefix — digits are a seed, letters an
entry code, upper-cased, Alt kept as the archive spells it, blanks for main
draw and unseeded — `split_result_full()` returns both sides' prefixes
beside the names, `build.main()` stores seed / entry / opp_seed / opp_entry
per side, and `emit.py` fills winner_seed / winner_entry / loser_seed /
loser_entry: a player's own page first, else what the opponent's page
printed about them. Re-emitted with `refresh.py --rebuild-only`: **341 of
969** rows carry an entry code on at least one side (Q on 196 sides, WC 112,
LL 51, PR 14, SE 3), **579** carry a seed. `load.py` reads them unchanged — the column
names are the Sackmann ones — and `features.live_workload` returns entry =
1 (Q) for the 2026 US Open qualifiers from their archive rows at the event,
with no flag.

What that changes: the entry curve needs the flag only for a player's
FIRST match at an event — the draw is not in the archive until it has been
played — and reads the code from the feed for every match after it. The
`--entry` flags, the prompt commands and the app selects stay for that
first match; the "draw feed" of the 09-12 list is now one match wide. And
the curves cache (`features.build` → `tools/curves.py build`) sees codes on
the reconstructed rows too, which shows up in the refit below: entry's cost
of dropping doubled, +0.00049 → **+0.00105**.

### TRAIT_K / TRAIT_MIN — flat, and now measured

`tools/traitsweep.py`, new, for the last two constants of the correction
layer that were chosen rather than fitted: the shrinkage n / (n + K) and
the floor (fewer prior rows than MIN: no read) of `resid_prior`. No walk.
Each (K, MIN) re-annotates the cached residual rows in memory
(`curves.py annotate_traits` reads the two module constants at call time),
refits the eight curves on each fold's train half and scores the shipped
antisymmetric log-odds application at k = 1 on the test half — what
`curves.py antisym --logit` does — but keeps every match's loss, so each
cell is paired against the shipped (40, 15) by a per-match t on **22,697**
identical matches (rule 1). Under a second a cell — the whole grid in about twenty seconds — on the 56,754
player-rows of the 7-day cache. The grid: K in {10, 20, 40, 80, 160, 320}
× MIN in {5, 10, 15, 25, 40}, thirty cells. The K = 40 column:

| K = 40, MIN = | rows with a read | vs shipped | t |
|---|---|---|---|
| 5 | 53,708 | −0.00002 | +0.17 |
| 10 | 51,508 | −0.00007 | +1.07 |
| **15** | 49,533 | shipped | |
| 25 | 46,009 | −0.00000 | +0.04 |
| 40 | 41,434 | +0.00018 | −1.15 |

Everything is within noise of the shipped cell. The best in the grid is
(40, 10) at −0.00007, t +1.07; MIN = 40 costs +0.00015..+0.00032 at t −0.8
to −1.5 for every K, because the floor drops a sixth of the reads (41,434
against 49,533); K = 320 costs +0.00013..+0.00032. **(40, 15) stays.** That
is item 4 of the 09-12 list closed with nothing, which is the result: two
guesses sit within noise of the best value on a grid thirty cells wide.
Recorded in `fitted_params.json` as `trait_k_note`.

### A player-specific prior

The 270-day rating is a shrinkage estimate: a player's serve and return are
pulled toward a prior by prior_weight 150 pseudo-points, and the prior was
the tour average — the same middle for everyone. A player back from a
layoff has little in the window, so he is priced as a tour-average player
until he has played his way back, and a top-ten player back from surgery
is not a tour-average player. The model already holds a better guess of
who he is: the long-window rating, 12 years at a 1,095-day half-life, that
the surface carry-over reads. `prior_mode` "own" shrinks the 270-day
rating toward that — by the same prior_weight — instead of toward the
tour, so a player back from a layoff is pulled toward who he was, not
toward the middle.

The plumbing. `ratings.fit_iterative` and `fit_iterative_reference` take an
optional `priors={pid: (serve, ret)}`; the vectorised-equals-reference gate
has a third case with a synthetic player-specific prior on a subset of
players, max diff 1.5e-11, PASS. In `weights.derive` the long fit moved
ahead of the main fit, which now needs it — the same numbers, and the
harness == `weights.json` gate in the chain says so. `weights.PRIOR_MODE`
reads `TENNIS_PRIOR_MODE`, else `prior_mode` in `fitted_params.json`,
"tour" until today; `backtest.py` writes it back (rule 7);
`tools/knobsweep.py` has it as a knob, `run prior_mode own`. Two walks at
the 7-day cadence, cap 0.08, on the refreshed archive, 452 s each, paired
on **43,075** identical matches (train 20,648 / test 22,427):

| prior_mode | form_scale | test log loss | vs shipped | t |
|---|---|---|---|---|
| **own** | **0.70** | **0.61059** | **−0.00091** | **+2.92** |
| tour | 0.50 | 0.61151 | shipped | |

**Adopted.** The tour row is also what the refresh alone did to the old
headline: 0.61140 on 42,997 scorable matches became 0.61151 on 43,075.
form_scale refits from 0.50 to 0.70 under the own prior — the opposite
direction from what the cadence did to it two days ago, and I do not have
the reading for that yet; recorded, not explained.

prior_weight 150 had been fitted against the tour prior (`ratings.py`:
"pseudo-counts, in service points; fitted"), so it was re-swept under the
own one — `TENNIS_PRIOR_MODE=own tools/knobsweep.py run prior_weight 100
300 600`, all four on the same 43,075 matches:

| prior_weight | form_scale | test log loss | vs shipped | t |
|---|---|---|---|---|
| 100 | 0.70 | 0.61057 | −0.00002 | +0.39 |
| **150** | **0.70** | **0.61059** | shipped | |
| 300 | 0.60 | 0.61112 | +0.00053 | −4.71 |
| 600 | 0.60 | 0.61177 | +0.00118 | −5.58 |

**150 stays.** 100 is indistinguishable from it and heavier shrinkage
toward the own level hurts, monotonically: a better level to shrink toward
is not a reason to shrink harder. Shipped since today: prior_mode "own",
prior_weight 150.

### The sweep that came back four times the same — rule 31

That table is the second attempt. The first prior_weight sweep returned
four IDENTICAL walks — 0.61059, t 0.00, for 100, 150, 300 and 600, the
same log loss to five places. Identical to five places is not flat; it is a
knob that is not connected. `backtest.py` read PRIOR_W (and HALF_LIFE) from
`fitted_params.json` itself instead of from `weights.py`, so the new
`TENNIS_PRIOR_WEIGHT` override moved the live derivation and not the
harness: the harness passes the weight into the fit by hand
(`_fit_block(..., HALF_LIFE, PRIOR_W, ...)`), and its copy said 150
whatever the variable said. prior_mode had not been caught by this because
`weights.derive` reads PRIOR_MODE itself and the harness goes through
`derive`; the weight was the one constant with two homes. Fixed the same
day: `backtest.HALF_LIFE = weights.HALF_LIFE` and `backtest.PRIOR_W =
weights.PRIOR_WEIGHT`, one source for the rating-layer constants (rule 19).
The harness == `weights.json` gate (`backtest.py --gate`) still passes —
and it would have failed under the override, had a sweep run it, which a
sweep does not. The gate compares two derivations of the same constants;
it cannot see that they read them from two places until the places
disagree.

Rule 31: a sweep whose values all score identically is a broken knob, not
a flat one. Check that the override reaches the code that fits before
reading a sweep as flat. The 09-12 sweeps are not in doubt — their values
differ, and each was paired on walks that visibly moved — but the flat ones
among them (the surface half-life, the long window) were read as flat on
values 0.00004 to 0.00015 from the shipped one, and a broken knob would
have read the same way at 0.00000. Rule 31 is the cheap check that tells
the two apart.

### The refit chain on the refreshed archive, with the own prior

`tools/refit_chain.sh`, in the HANDOFF order — fit, the harness gate, backtest,
`pathsweep all`, `curves build / loo / antisym / fit / write`, `confidence
fit`, `m4` for both seasons, gates again — on the refreshed archive with
prior_mode own. The walk: **634** refits (counted in the log), 389 s for
the four pricing paths, 43,075 scorable matches, train 20,648 / test
**22,427**:

| rung | log loss | vs previous | t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo K=4, results only | 0.66280 | | |
| tour-wide single rating, form_sd 0.040 | 0.61597 | | |
| + calibration (slope 1.014) | 0.61608 | +0.00011 | −3.17 |
| per-player surface + form (scale 0.70) | 0.61266 | | |
| + in-event update (w = 2) | 0.61069 | −0.00197 | +6.32 |
| + air density (w = 0.40) | **0.61059** | −0.00010 | +4.46 |
| + calibration (slope 1.007, measured, not shipped) | 0.61066 | +0.00007 | −3.68 |
| three-stage serve ON (measured, not shipped) | 0.61478 | +0.00418 vs shipped | −6.41 |

Headline **0.61059**, Elo 0.66280 on the same 22,427 — a gap of 0.0522,
against 0.0515 two days ago, 0.0499 at 21 days and 0.0453 at 91. form_sd
fits 0.040 and form_scale 0.70, both under the own prior (0.030 / 0.50
under the tour one). Calibration stays OFF by its own test: the measured
slope is 1.007 and applying it costs +0.00007 at t −3.68 — the fourth
reading in four sessions within a few parts in a thousand of identity, and
the first of them that did not flip the decision. `calibration_b` is 1.0
with 1.007 kept beside it.

Not comparable to 0.61140: that was 22,420 test matches on the archive
before the refresh, with the tour prior. Both moved — the scorable set to
43,075 with the four rows and 81 stat lines, the prior with the sweep — and
the paired number for the prior is the honest one, −0.00091 at t +2.92 on
43,075 identical matches. The headline is the state; the paired number is
the measurement.

Every knob of the shipped path flipped alone (`tools/pathsweep.py all`,
43,075 matches, test 22,427, one walk of 383 s uncontended for six
configurations — which makes the hour the same sweep took two days ago look
like the 3-day walk that ran beside it), with the tour-prior value beside
each:

| config | scale | vs shipped | t | tour prior, 09-12 |
|---|---|---|---|---|
| three-stage serve ON | 0.30 | +0.00315 | −5.81 | +0.00209, t −8.92 |
| in-event update OFF | 0.70 | +0.00194 | −6.25 | +0.00159, t −5.27 |
| both of those flipped | 0.40 | +0.00446 | −7.81 | +0.00359, t −9.89 |
| surface carry-over OFF | 0.85 | **+0.01584** | **−13.29** | +0.01508, t −11.28 |
| no surface split at all | 0.60 | +0.00398 | −4.69 | +0.00329, t −3.63 |

Same ordering, every cost larger: each layer costs more to remove under
the own prior than it did under the tour one, and the carry-over is still
the largest thing the model is made of.

The correction layer, eight curves, refitted on the new cache
(`tools/residuals.json` rebuilt at the 7-day cadence with the own prior on
the refreshed archive, 56,910 player-rows), k = 1.0. Alone (single split),
the cost of dropping (leave-one-out, 4 folds of 4), and the cost two days
ago with the tour prior:

| curve | alone | to drop | to drop, 09-12 |
|---|---|---|---|
| age | −0.00148 | **+0.00227** | +0.00183 |
| entry | −0.00040 | **+0.00105** | +0.00049 |
| resid_prior | −0.00066 | +0.00093 | +0.00152 |
| event_gwp | −0.00080 | +0.00091 | +0.00086 |
| matches_28d | −0.00050 | +0.00085 | +0.00118 |
| form_spw | −0.00031 | +0.00027 | +0.00029 |
| event_sets_lost | −0.00019 | +0.00021 | +0.00019 |
| home | −0.00009 | +0.00015 | +0.00011 |

The set is worth **−0.00738** at k = 1, 4 folds of 4 — no curves 0.61064,
with them 0.60326 (k 1.25 −0.00763; k 1.5 −0.00727; k 2 −0.00475; the scale
chosen on each fold's train half scores 0.60327 against 0.60326 at k = 1,
so k stays 1). It was −0.00735 at 7 days with the tour prior, −0.00807 at
21 days, −0.00999 at 91: the layer as a whole is where it was, to three
parts in a hundred thousand, and every curve still earns its place. Inside
it, three curves traded places and a fourth grew, and the moves are the prior's. resid_prior
and matches_28d each cost less to drop (+0.00152 → +0.00093, +0.00118 →
+0.00085): the likely reading is that a player who "beat the point model"
was often a player shrunk too far toward the tour, and the own prior now
does part of what the residual trait did. Entry doubled because the
reconstructed rows — the newest matches, so the last fold's test half — now
carry codes. And age grew, which is the finding of the day.

Age buckets on the new cache, shrunk (under 21, 21–24, 24–27, 27–30,
30–33, 33+): +0.050 (n 3,736), +0.030 (9,613), +0.008 (13,864), −0.011
(14,196), −0.024 (8,744), −0.035 (6,757), monotone; youngest minus oldest
**+0.085**, against +0.075 with the tour prior, +0.078 at 21 days, +0.097
at 91 and +0.123 before the age half-life. It had fallen at every step for
a week and today it grew, and the prior is why: a declining player is now
shrunk toward his own long-window level — a better past — where the tour
average pulled him toward the middle, so the 33+ bucket misses its price
by 3.5 points instead of 2.8 and the age curve corrects it after the fact.
That is the wrong place to do it, because the curve can only correct on
average what the prior mis-sets per player. An AGE-DEPENDENT PRIOR — own
for the young and the prime years, the tour average or a decayed own level
past about 30 — is the next candidate: one knob in `weights.derive`,
measured with `tools/knobsweep.py` the way prior_mode was.

Entry buckets, shrunk: main draw −0.005 (n 46,743), Q **+0.037** (5,740),
WC +0.004 (2,582), LL −0.009 (1,218), PR +0.000 (369, thin), SE −0.001
(189); the seventh bucket, "other" — Alt and anything else the archive
spells — is −0.005 on 69 rows, too thin to read. Qualifiers beat their
price by 3.7 points now, against 2.3 before, and it is the same prior from
the other side: a qualifier's history is thin and low, the own prior
shrinks him toward it where the tour average pulled him up, and the curve
corrects the difference. Lucky losers miss by 0.9 (1.8 before).
resid_prior runs −0.033 below −0.04 to +0.028 above +0.04, monotone apart
from the flat middle. `data/player_traits.json` carries 384 players.

Confidence bands, refitted on the final residuals: GOOD **0.59021**
(n 10,238), FAIR 0.64117 (3,280), LOW 0.76423 (710). Monotone; GOOD lower
than two days ago (0.59458), FAIR and LOW higher (0.63616, 0.74471), each
on a slightly different set.

M4 against the Pinnacle closing line, final configuration, before the
curve layer, `data/market_check.json` rewritten. 2025: 2,388 matches,
model 0.62400, closing (devigged) 0.60373, gap **+0.02027** (was +0.02159
with the tour prior, +0.02252 at 21 days). By distance from the market:
0–2% n 488 +0.0004; 2–5% n 666 +0.0078; 5–10% n 679 +0.0211; 10%+ n 555
**+0.0516**. The 10%+ bucket shrank from 602 to 555 matches — fewer
confident disagreements — while its gap grew a little from +0.0484. 2024:
2,512 matches, model 0.60787, closing 0.58556, gap **+0.02230** (was
+0.02228 with the tour prior: flat; +0.02382 at 21 days); 0–2% n 507
−0.0001; 2–5% n 704 +0.0012; 5–10% n 761 +0.0164; 10%+ n 540 **+0.0791** —
that bucket shrank too, from 597 to 540, but its gap grew from +0.0712.
The prior helped 2025 and left 2024 where it was, and that is the honest
summary: the paired walk-forward number is the measurement (−0.00091,
t +2.92, 43,075 matches) and the market checks are two seasons of it, one
of which moved. The eight-curve layer (−0.0074 walk-forward) is applied
downstream, so the live gap is roughly +0.013 in 2025.

All six gates pass at the end of the chain — simulator against the exact
recursion; estimator recovery, no leakage and vectorised == reference, now
with the priors case; data integrity and the tour average (0.6320 over
11,619,664 service points, 73,014 of 80,150 passing the identities); name
resolution and line parsing (22/22, 19/19 against 1,515 real players,
14/14); workload derivation (live pricing supplies all eight curve inputs;
63,983 player-match rows); and the harness derivation equal to
`weights.json` — and the log ends ALL GATES PASS, == DONE. Rebuilt, in
order: `weights.json`; `fitted_params.json`, with `prior_mode_note` and
`trait_k_note` new and the test_log_loss, three_stage, event_update,
surface_carry and curves notes carrying today's numbers with the tour-prior
ones kept as history (`knob_sweep_note` untouched);
`tools/_pathsweep/all.json`; `tools/residuals.json`; `fitted_curves.json`
with `data/player_traits.json`; `confidence_model.json`;
`data/market_check.json`.

### The app

The app shows entry codes by name. `web/app.js` carries `ENTRY_NAMES` by
the same index as `features.ENTRY` — main draw, qualifier, wild card,
lucky loser, protected ranking, special exempt, other — and the player
line and the workload table print "entered as qualifier" rather than a
code; when the archive has no row at the event yet the table says so
("unknown until they have played here, or until you say"), and now that the
feed carries the codes, that is the line a player gets only before his
first match at an event. The two selects stay for that match. The server
was restarted on the final model after the chain (`app.py --no-open --port
8765`).

### The shipped configuration

| knob | value | knob | value |
|---|---|---|---|
| half_life_days | 270 | age (young, old) | 0.50, 0.85 |
| **prior_mode** | **own** (was tour) | AGE_KNOTS | 22, 28, 34 |
| prior_weight | 150 (re-swept under own; stays) | qc_supplement | on, k 1.0 |
| train_years / long_years | 5 / 12 | surface_carry | on, carry_cap 0.08 |
| surface_half_life_days | 1095 | event_update_w | 2.0 |
| refit_days | 7 | three_stage_serve | off |
| form_scale | **0.70** (was 0.50) | calibration_b | 1.0 = off (measured 1.007) |
| form_sd (tour) | **0.040** (was 0.030) | dens_w | 0.40 |
| TRAIT_K / TRAIT_MIN | 40 / 15 (swept; stay) | curves | eight, k 1.0 |
| news_w | 1.0, a prior | test_log_loss / test_matches / Elo | 0.61059 / 22,427 / 0.66280 |

### Where this leaves it

The one change that moved the number today is again per-player and
trend-shaped: shrink a player toward who he was, not toward the tour. It
is worth −0.00091 at t +2.92 on 43,075 matches, it helped one of the two
market seasons and left the other flat, and it grew the age effect — which
is the next thing to fix, and the reason to fix it at the prior rather than
at the curve. The 10%+ bucket is still where the gap lives: 2025 +0.052 on
555 matches, 2024 +0.079 on 540; the prior narrowed the bucket without
closing it.

0. Refresh weekly: `python3 update.py`, then `tools/refit_chain.sh`. Rule
   30; today was the first one.
1. An AGE-DEPENDENT PRIOR: the own prior grew the age effect (youngest
   minus oldest +0.075 → +0.085) because a declining player is now shrunk
   toward a better past. Candidate: own prior for the young and prime,
   tour average (or a decayed own level) past ~30 — one knob in
   `weights.derive`, measured with `tools/knobsweep.py` like prior_mode.
   Then the rest of the 10%+ bucket (2025 +0.052 on 555 matches, 2024
   +0.079 on 540): a per-player refit cadence; a draw feed for a player's
   first match at an event — later matches read the code from the feed
   since today.
2. Totals odds, the unchanged blocker.
3. Fit `news_w` from `data/news_applied.jsonl` once a few hundred matches
   carry news.
4. Or accept it as a study.

## Session 2026-09-15 — an age-dependent prior, and what the curves were hiding

Item 1 of yesterday's list, done. The prior the 270-day rating is shrunk
toward now depends on age, and by the harness's own measure it is the
largest rating-layer gain of the week: **−0.00175 at t +6.94** on 43,075
identical matches, against yesterday's flat own prior. The honest headline
of the day is the second measurement, the one I had not made before: on
the price a person actually sees, after the eight correction curves, the
same change is **+0.00016 at t −0.80** — nothing. The curves were already
correcting most of what the prior fixes. It ships anyway, for reasons
below, but "the price moved" would have been false, and that is now rule
33. The sweep also got wide enough — fourteen values — to need a guard
against reading a winner off one half of the data, which is rule 32. The
sweep ran 21:20 to 22:28 in four batches and the chain 22:33 to 23:01.

### Why: the own prior made the age curve bigger

Yesterday's change shrank each player's 270-day rating toward his own
12-year rating instead of toward the tour average, won −0.00091 at
t +2.92 — and made the age curve LARGER, youngest minus oldest +0.075 →
+0.085, after a week of that number falling at every step. I wrote then
that the curve was the wrong place to fix it. The mechanism is plain
enough once stated: the 12-year window holds a declining player's peak,
so the own prior over-states him, and it holds a rising player's junior
years, so it under-states him. And the prior only bites where the 270-day
window is thin — arriving, winding down, or back from an injury — which
is exactly where a stale level does the most damage. At the shipped as-of
day, **263 of the 292 rated players past 34 are under 1,500 service
points, and 421 of the 436 under 22** (counted for `prior_age_note`). The
players the prior moves most are the players whose own history describes
them least.

So: keep the own prior where it is right, and blend it back toward the
tour average at the ends of a career.

### The knob

`weights.PRIOR_AGE = (young, old)`: how much of a player's own DEVIATION
from the tour average survives into the prior at each end of a career.

    prior = tour + w(age) × (own − tour)

`w` is the piecewise-linear age ramp the model already has —
`ratings.age_multiplier` on `AGE_KNOTS` (22, 28, 34) — **pinned to 1.0 at
the prime**, so the knob only ever changes the ends, and so "when is a
player young, prime or old" still has exactly one answer in this project
(rule 19). Reusing the ramp was not laziness: a second definition of
young would be a second thing to sweep and a second thing to disagree
with the age-dependent half-life. A player with no birthday keeps the own
prior, the same fallback the half-life makes.

(2, 0) therefore reads: double the deviation at 22 and under, the
player's own level at 28, the tour average at 34 and over.

**(1, 1) is exactly `prior_mode` "own"** — the ramp is 1.0 everywhere, so
the blend is the identity. I checked that to 0.0 *before any walk ran*,
which is rule 31 made into a habit rather than a lesson: a knob that
cannot reproduce the value it replaces is a knob that is not connected.
The sweep then confirmed it the expensive way: the (1, 1) walk scores
**0.61059**, yesterday's own-prior headline to five places, on the same
22,427 test matches.

Plumbing, as usual: `weights._priors` grew the "age" branch,
`TENNIS_PRIOR_AGE` overrides it, `backtest.py` writes `prior_age` back to
`fitted_params.json` (rule 7), and `tools/knobsweep.py` carries it as a
knob (`TENNIS_PRIOR_MODE=age python3 tools/knobsweep.py run prior_age
1,0 0.5,0 0,0`), reading the shipped value from `weights.py` so an
adopted value becomes the next sweep's baseline.

### The sweep

Fourteen values, one full walk-forward each in its own subprocess, five
at a time, paired on 43,075 identical matches (train 20,648 / test
22,427) against (1, 1). Four batches, 21:20 to 22:28, each re-running the
baseline (`run()` puts the shipped value first, once) and each going
where the last one pointed: first the two damping directions, then the
negative old end and a first step up on the young one, then 2 and 3, and
finally 2.5 and 4 to find where it turns over.

| prior_age (young, old) | form_scale | test log loss | vs (1,1) | t |
|---|---|---|---|---|
| 0, 0 | 0.60 | 0.61142 | +0.00083 | −3.42 |
| 0.5, 0.5 | 0.60 | 0.61092 | +0.00033 | −2.90 |
| 0.5, 0 | 0.60 | 0.61052 | −0.00007 | +0.36 |
| **1, 1** | **0.70** | **0.61059** | shipped | |
| 1, 0.5 | 0.60 | 0.61027 | −0.00032 | +3.06 |
| 1, 0 | 0.60 | 0.60984 | −0.00075 | +4.31 |
| 1, −0.5 | 0.60 | 0.60964 | −0.00095 | +3.63 |
| 1, −1 | 0.60 | 0.60966 | −0.00094 | +2.62 |
| 1.5, 0 | 0.60 | 0.60938 | −0.00121 | +5.76 |
| 2, −0.5 | 0.60 | 0.60886 | −0.00174 | +5.20 |
| **2, 0** | **0.70** | **0.60885** | **−0.00175** | **+6.94** |
| 2.5, 0 | 0.70 | 0.60868 | −0.00191 | +5.97 |
| 3, 0 | 0.70 | 0.60870 | −0.00189 | +4.73 |
| 4, 0 | 0.85 | 0.60861 | −0.00198 | +3.84 |

Two readings, and only one of them was the hypothesis. **Damping the old
end helps** — that was the point, and (1, 0), which changes nothing but
the old end, is already worth −0.00075.
**Damping the young end hurts**, monotonically: (0.5, 0) is a wash and
(0, 0) is worse than shipping nothing. The young end does not want the
tour average, it wants MORE of the player's own deviation than the own
prior gives it — which reads, after the fact, as the 12-year window
being a thin and stale description of a 20-year-old rather than a wrong
one: it holds his junior years, so doubling the distance from the tour
average is a crude way of saying "he is further from average than his
history has had time to show". Both edges were probed until they turned
over (rule 26). The old end turns over in the loss itself: (1, −1) is no
better than (1, −0.5), so overshooting past the tour average buys
nothing. The young end turns over in everything except the loss, which
flattens at 2 and then wanders by 0.0002 either way while the t falls and
`form_scale` climbs — which is the next paragraph.

**(2, 0) ships, not (4, 0).** Everything from 2 upward is a plateau —
0.60885, 0.60868, 0.60870, 0.60861, a spread of 0.00024 across a
doubling and a half of the knob — while the t falls away from +6.94 to
+3.84 and `form_scale` starts climbing, 0.70 through the plateau and
**0.85 at (4, 0)**. That last is the tell I have learned to read: when a
knob needs more form volatility on top to stay honest, it is buying its
gain by making the rating itself less trustworthy. So the plateau begins
at 2 and the smallest change with the highest t ships, exactly as
`carry_cap` did.

### The guard — rule 32

Fourteen values read off one test half is fourteen chances to be lucky,
and I noticed it only because this sweep was twice as wide as any before
it. The cheap guard: score every value on BOTH halves and require that a
value winning on test also wins on train.

Prototyped in the scratchpad (`bothhalves.py`), then folded into the
tool, because a guard I have to remember to run is not a guard.
`tools/knobsweep.py compare` now fits `form_scale` on the train half and
prices *both* halves with it, prints the train column and its t beside
the test ones, and tags a value that wins on test while losing on train
`TEST ONLY -- flag`. It is not a flag I can turn off; it always reports
both.

| value | train vs (1,1) | t | test vs (1,1) | t | verdict |
|---|---|---|---|---|---|
| 4, 0 | −0.00107 | +2.47 | −0.00198 | +3.84 | both halves |
| 2.5, 0 | −0.00116 | +4.41 | −0.00191 | +5.97 | both halves |
| 3, 0 | −0.00122 | +3.68 | −0.00189 | +4.73 | both halves |
| **2, 0** | **−0.00096** | **+4.85** | **−0.00175** | **+6.94** | **both halves** |
| 2, −0.5 | −0.00096 | +3.52 | −0.00174 | +5.20 | both halves |
| 1.5, 0 | −0.00067 | +3.70 | −0.00121 | +5.76 | both halves |
| 1, −0.5 | −0.00033 | +1.82 | −0.00095 | +3.63 | both halves |
| 1, −1 | −0.00026 | +1.08 | −0.00094 | +2.62 | both halves |
| 1, 0 | −0.00030 | +2.21 | −0.00075 | +4.31 | both halves |
| 1, 0.5 | −0.00017 | +1.46 | −0.00032 | +3.06 | both halves |
| 0.5, 0 | +0.00021 | −1.60 | −0.00007 | +0.36 | **TEST ONLY — flag** |
| 0.5, 0.5 | +0.00034 | −3.24 | +0.00033 | −2.90 | worse on both |
| 0, 0 | +0.00087 | −4.98 | +0.00083 | −3.42 | worse on both |

Ten of the thirteen win on both halves, and the ranking is the same on
both apart from the three at the top of the plateau trading places
between themselves (train likes 3, 0 best, test likes 4, 0) and 1, 0
swapping with 1, −1 near the bottom — which is what a plateau looks like
and not what a fluke looks like. The one flagged row is **0.5, 0**, and
it flags on a gain of 0.00007: exactly the size of thing that would have
been quietly listed as "a small improvement" if I had only ever looked at
the test half. Nothing was adopted on it. Rule 32 costs two extra columns
and one more `paired_t` call per value; the walks themselves are
unchanged.

### The honest result — rule 33

The harness measures the rating layer *without* the curves, because the
curves are fitted on its residuals. That is the right way round for
fitting and the wrong way round for claiming: a rating change that the
curves were already papering over will look like a gain in the harness
and be worth nothing in the price `price.py` prints. Rule 23 says a layer
measured alone is not measured; this is rule 23 pointed downward.

So I measured it both ways, with `curvepair.py` in the scratchpad. Two
residual caches, both 56,910 player-rows: the age-prior one the chain had
just built, and a second one rebuilt **on purpose with yesterday's flat
own prior** (`curves build` under `TENNIS_PRIOR_MODE=own`, 23:01–23:05,
the shipped cache restored afterwards). For each cache the eight curves
are fitted on every fold's train half and applied to its test half
exactly as `price.py` applies them — antisymmetric, in log-odds, at the
shipped magnitude — and every match's loss is kept, so the two can be
paired on **22,759 identical matches**:

| | log loss | vs A | paired t |
|---|---|---|---|
| A own prior, ratings alone | 0.61068 | — | |
| B age prior, ratings alone | 0.60887 | **−0.00181** | **+7.17** |
| A own prior + the eight curves | 0.60330 | −0.00737 | +11.00 |
| B age prior + the eight curves | 0.60346 | −0.00721 | +10.36 |

B against A after the curves: **+0.00016 at t −0.80**. Nothing, and if
anything the wrong sign. The two caches also reproduce both chains'
curve layers from the inside — −0.00738 under the own prior, −0.00541
under the age one — which is the same fact stated the other way: the
prior took −0.0018 off the ratings and the curve layer gave back −0.0020
less.

It ships anyway, and the reasons are not "but the t was 7":

1. **The market gap improved on both seasons**, measured before the curve
   layer (2025 +0.02027 → +0.01857, 2024 +0.02230 → +0.02012), and the
   10%+ disagreement bucket shrank in both (555 → 495, 540 → 497).
2. **The totals path never sees the curves.** It takes the serve
   probabilities directly, so the −0.0018 is not hidden there at all —
   the one place this session's gain is fully real.
3. **Less of the answer is a fitted residual shape.** The correction
   layer fell from −0.00738 to −0.00541. A model that needs less
   correction is the point of the exercise.
4. **The age curve, which is what prompted this, halved**: the
   youngest-minus-oldest spread from +0.085 costing +0.00227 to drop, to
   **+0.056 costing +0.00091**. The prior is now doing at the player
   level what the curve could only do on average.

Rule 33: a fitted corrector hides an improvement underneath it. Measure a
rating-layer change both ways before claiming it, and say which number
the claim is. Mine is −0.00181 on the ratings and +0.00016 on the price.

### After the refit chain

`tools/refit_chain.sh` in the HANDOFF order on the archive refreshed
yesterday, `prior_mode` age (2, 0). **634 refits** counted in the log,
43,075 scorable matches, train 20,648 / test **22,427**:

| rung | log loss | vs previous | t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo K=4, results only | 0.66280 | | |
| tour-wide single rating, form_sd 0.040 | 0.61418 | | |
| + calibration (slope 1.012) | 0.61425 | +0.00007 | −2.70 |
| per-player surface + form (scale 0.70) | 0.61066 | | |
| + in-event update (w = 2) | 0.60893 | −0.00173 | +5.67 |
| + air density (w = 0.40) | **0.60885** | −0.00009 | +4.04 |
| + calibration (slope 1.009, measured, not shipped) | 0.60891 | +0.00007 | −3.09 |
| three-stage serve ON (measured, not shipped) | 0.61499 | +0.00615 | −8.85 |

Headline **0.60885**, Elo 0.66280 on the same 22,427 — the model beats
tuned Elo by **0.0540** nats, against 0.0522 yesterday and 0.0453 at the
91-day cadence. Calibration is OFF by its own test again: the measured
slope is 1.009 and applying it costs +0.00007 at t −3.09 — the fifth
reading in five sessions within a few parts in a thousand of identity.
`calibration_b` stays 1.0 with the measurement beside it.

**Not comparable** to 0.61059 (same archive, flat own prior) or to
0.61140 (the archive before the refresh, tour prior). Nothing in the
scorable set moved today, but the headline is a state and the paired
number is the measurement: −0.00175 at t +6.94 for the ratings, +0.00016
at t −0.80 for the price.

Every knob of the shipped path flipped alone (`tools/pathsweep.py all`,
one walk of **445 s** over six configurations, 43,075 matches, test
22,427), with yesterday's own-prior value beside each:

| config | scale | vs shipped | t | own prior, 09-14 |
|---|---|---|---|---|
| three-stage serve ON | 0.30 | +0.00505 | −8.54 | +0.00315 |
| in-event update OFF | 0.70 | +0.00170 | −5.60 | +0.00194 |
| both of those flipped | 0.40 | +0.00621 | −9.92 | +0.00446 |
| surface carry-over OFF | 0.85 | **+0.01789** | **−14.00** | +0.01584 |
| no surface split at all | 0.60 | +0.00400 | −4.75 | +0.00398 |

Same ordering, and every layer but one costs MORE to remove than it did
yesterday — the second session running in which that is the summary. A
better rating layer makes the structure around it matter
more, and the carry-over is still by a distance the largest thing this
model is made of. (The in-event update is the exception, +0.00194 →
+0.00170: the prior has taken a little of what it was doing.)

The correction layer, eight curves, refitted on the new cache (56,910
player-rows = 28,455 matches), `fitted_curves.json` k = 1.0. Alone
(single split), the cost of dropping (leave-one-out, 4 folds of 4), and
the same cost yesterday:

| curve | alone | to drop | to drop, 09-14 |
|---|---|---|---|
| entry | −0.00045 | **+0.00100** | +0.00105 |
| age | −0.00060 | +0.00091 | **+0.00227** |
| event_gwp | −0.00083 | +0.00090 | +0.00091 |
| resid_prior | −0.00045 | +0.00088 | +0.00093 |
| matches_28d | −0.00040 | +0.00083 | +0.00085 |
| form_spw | −0.00026 | +0.00026 | +0.00027 |
| event_sets_lost | −0.00017 | +0.00022 | +0.00021 |
| home | −0.00010 | +0.00015 | +0.00015 |

The set is worth **−0.00541** at k = 1, 4 folds of 4 and all four helped
— no curves 0.60883, with them 0.60341 (k 1.25 −0.00564; k 1.5 −0.00543;
k 2 −0.00372 and only 3 of 4 folds; the scale chosen on each fold's train
half scores 0.60340 against 0.60341, so k stays 1). It was −0.00738
yesterday, −0.00735 at 7 days with the tour prior, −0.00807 at 21 days,
−0.00999 at 91. Every curve still earns its place — but the shape of the
layer has changed as well as its size: **`entry` is now the largest thing
in it**, and `age`, which was the largest yesterday and on 09-12 and
09-11, has halved. It still comes second, by a hair over `event_gwp` and
`resid_prior` — the four of them now sit inside 0.00012 of each other,
where yesterday `age` stood 0.00122 clear of the field. Everything except
`age` is within 0.00005 of its value yesterday. One curve moved; the rest
of the layer did not notice.

Age buckets on the new cache, shrunk (under 21, 21–24, 24–27, 27–30,
30–33, 33+): **+0.037** (n 3,736), +0.019 (9,613), +0.005 (13,864),
−0.009 (14,196), −0.016 (8,744), **−0.019** (6,757), monotone; youngest
minus oldest **+0.056**, from +0.085 yesterday, +0.075 with the tour
prior, +0.097 at 91 days and +0.123 before the age half-life. The prior
now absorbs what the curve was correcting — the third time this has
happened to the same curve in a week, after the age half-life on 09-09
and the refit cadence on 09-12, and the first time it was done on
purpose.

Entry buckets, shrunk: main draw −0.005 (n 46,743), Q **+0.036** (5,740),
WC +0.005 (2,582), LL −0.009 (1,218), PR +0.006 (369, thin), SE −0.001
(189), other −0.005 (69, too thin to read). The qualifier bucket is where
it was yesterday (+0.037): the age prior does not touch it, which is
consistent — a qualifier is thin at any age. `resid_prior` runs −0.028
(below −0.04) to +0.024 (above +0.04), monotone apart from the flat
middle, both ends a little smaller than yesterday's −0.033 / +0.028.
`data/player_traits.json` carries 384 players.

Confidence bands, refitted on the final residuals: GOOD **0.58777**
(n 10,238), FAIR 0.64113 (3,280), LOW 0.76531 (710). Monotone; GOOD
lower than yesterday (0.59021), FAIR flat (0.64117), LOW a little higher
(0.76423) — the confident band got better and the hopeless one did not,
which is the direction to want.

M4 against the Pinnacle closing line, before the curve layer,
`data/market_check.json` rewritten. **2025**: 2,388 matches, model
0.62230, closing (devigged) 0.60373, gap **+0.01857** (was +0.02027 with
the flat own prior, +0.02159 with the tour prior); by distance from the
market, 0–2% n 510 +0.0005; 2–5% n 697 +0.0058; 5–10% n 686 +0.0196;
10%+ n 495 **+0.0537**. **2024**: 2,512 matches, model 0.60568, closing
0.58556, gap **+0.02012** (was +0.02230, +0.02228); 0–2% n 555 −0.0019;
2–5% n 718 +0.0043; 5–10% n 742 +0.0173; 10%+ n 497 **+0.0718**. Both
seasons improved this time — yesterday's prior helped 2025 and left 2024
flat — and the 10%+ bucket shrank in both, 555 → 495 (−11%) and 540 → 497
(−8%), in a single session and on top of yesterday's 602 → 555 and
597 → 540. That bucket is still where the whole gap lives: the model
disagrees confidently with the market about a sixth less often than it
did two days ago, and when it does it is still wrong by +0.054 and
+0.072.

**All six gates pass** at the end of the chain — simulator against the
exact recursion; estimator recovery, no leakage and vectorised ==
reference (max diff 1.46e-11); data integrity and the tour average; name
resolution and line parsing; workload derivation (63,983 player-match
rows, live pricing supplies all eight curve inputs); and the harness
derivation equal to `weights.json` — and the log ends ALL GATES PASS,
== DONE. Rebuilt in order: `weights.json`; `fitted_params.json`, with
`prior_age_note` new (it carries the whole sweep, the guard and the
both-ways result) and the test_log_loss, three_stage, event_update and
surface_carry notes on today's numbers; `tools/_pathsweep/all.json`;
`tools/residuals.json`; `fitted_curves.json` with
`data/player_traits.json`; `confidence_model.json`;
`data/market_check.json`.

One thing to fix next session rather than tonight: the `curves_note` in
`fitted_params.json` and the `_note` inside `fitted_curves.json` still
describe the layer as −0.00738 with `age` the largest at +0.00227. The
chain rewrote both files at 22:54 and 23:06 but not those two strings, so
the numbers above and the prose beside them disagree. Rule 7 says one
derivation and everything reads it; a hand-written note inside a
generated file is the exception that keeps escaping.

### The shipped configuration

| knob | value | knob | value |
|---|---|---|---|
| half_life_days | 270 | age multipliers (young, old) | 0.50, 0.85 |
| prior_mode | **age** (was own) | AGE_KNOTS | 22, 28, 34 |
| **prior_age** | **2, 0** (new) | qc_supplement | on, k 1.0 |
| prior_weight | 150 | surface_carry | on, carry_cap 0.08 |
| train_years / long_years | 5 / 12 | event_update_w | 2.0 |
| surface_half_life_days | 1095 | three_stage_serve | off |
| refit_days | 7 | calibration_b | 1.0 = off (measured 1.009) |
| form_scale | 0.70 | dens_w | 0.40 |
| form_sd (tour) | 0.040 | news_w | 1.0, a prior |
| TRAIT_K / TRAIT_MIN | 40 / 15 | curves | eight, k 1.0 |
| test_log_loss / test_matches | 0.60885 / 22,427 | elo_log_loss | 0.66280 |

Unchanged from yesterday apart from the prior: `form_scale` 0.70 and
`form_sd` 0.040 both refit to the same values under the age-dependent
prior as under the flat own one, which is worth recording — the (2, 0)
walk did not need more volatility on top, and (4, 0) would have.

### One more thing the refit does not refresh

Chasing the age curve turned up a second number nobody was re-measuring.
A price prints its confidence band and, beside it, that band's measured
deficit against Pinnacle closing — four constants in `confidence.py`. The
refit chain rewrites the band's realised log loss every time, but those four
deficits were measured once, in the M4-era odds study, and have ridden
through every model change since: the age half-life, the cadence, the
refresh, both priors. They are what the tool tells a user about how far to
trust a price, and they were about a year of model out of date.

`tools/odds/disagree.py` already had the machinery — it joins odds, prices
and workload features into a cache — so it got a `bands` command, and the
refit chain now runs it. Rebuilt at the shipped model, 4,966 joined matches
across 2024–2026:

| band | n | model | market | deficit | shipped before |
|---|---|---|---|---|---|
| HIGH | 479 | 0.6023 | 0.5800 | **+0.0223** | +0.0143 |
| GOOD | 2,570 | 0.6250 | 0.6061 | **+0.0190** | +0.0225 |
| FAIR | 1,552 | 0.5993 | 0.5814 | **+0.0179** | +0.0307 |
| LOW | 365 | 0.6203 | 0.5900 | **+0.0303** | +0.0627 |

Every deficit fell, which is the model improving and is the least
interesting part. The interesting part is that **the ordering is gone**. The
original reading was +0.014 / +0.023 / +0.031 / +0.063, a clean 4.4× from
HIGH to LOW, and that ordering is the band's whole claim. Today LOW is still
the worst, but HIGH is no longer the best — it sits above GOOD and FAIR.

I think the explanation is not that the band broke but that the measure did.
The deficit is model minus market, and the band only describes the model.
HIGH means both players are well measured and match fit, which is another
way of saying the match is a marquee one, and a marquee match is exactly
where Pinnacle is sharpest. So a small model error is being compared against
a very small market error. That is rule 16 turning up one level higher than
it was written: raw log loss cannot separate "the model is bad here" from
"this is hard for anyone", and the deficit cannot separate "the model is bad
here" from "the market is unusually good here".

What I changed rather than papered over: the four constants now carry the
current measurement and a comment saying the ordering has broken down; the
chain re-measures them; and the app leads the band with the realised log
loss, which `confidence.py fit` refreshes every time and does still sort,
with the deficit printed underneath and the caveat attached to it. What I
did not do is re-derive the band. That wants its own session, and it should
start from the question of what the band is actually for — if it is "how far
to trust this price" then the realised loss is the honest target, and if it
is "where does the model lose to the market" then it needs a market-sharpness
term it does not have.

### Where this leaves it

The change of the day is the same shape as every change that has worked
this week: per-player, trend-shaped, and moved from a corrector into the
model that gets corrected. What is new is the second measurement. I have
been quoting harness numbers for a rating change all week as though they
were the price, and today is the first time I checked — the curves were
eating most of it, and on this one they ate all of it. The gain is real
in the market check, real in the totals path, and real in how little
correction the model now needs; it is not in the moneyline.

0. Refresh weekly: `python3 update.py` then `sh tools/refit_chain.sh
   <log>` (~25 min uncontended) — rule 30.
1. The curves now hide rating-layer gains (rule 33). Two directions:
   measure the next rating change BOTH ways as a matter of course; and
   ask whether the curve set should be re-derived now that it is only
   −0.00541 — every curve still earns its place, but `entry` is now the
   largest and `age` has halved.
2. The 10%+ bucket is still where the gap lives (2025 +0.054 on 495
   matches, 2024 +0.072 on 497). Candidates: a per-player refit cadence;
   a draw feed for a player's FIRST match at an event (later matches read
   the code from the feed since 2026-09-14).
3. Get totals odds (unchanged blocker) — and note that the totals path is
   where this session's gain is NOT hidden by the curves.
4. Fit `news_w` from `data/news_applied.jsonl` once a few hundred matches
   carry news.
5. Or accept it as a study: the model beats tuned Elo by 0.0540 nats.

---

## Session 2026-09-16 — re-deriving the confidence band, and what it found underneath

Yesterday closed with a number I had caught going wrong and deliberately not
fixed: the band's measured deficit against Pinnacle closing had stopped
sorting — HIGH +0.0223 sitting above GOOD +0.0190 and FAIR +0.0179 — and I
wrote that re-deriving the band wanted its own session, starting from the
question of what the band is actually for. This is that session, and the
choice it opened with was a small one: re-derive the band, or retire the
deficit constant that no longer ordered. It turned out to be neither, not
first, because the thing being measured was not the thing that ships.

**The model did not change today.** No refit chain ran. `weights.json`, the
`fitted_params` ladder, `fitted_curves.json` and `data/market_check.json` are
exactly as the 09-15 chain left them; the headline is still **0.60885 on
22,427 test matches** against Elo's 0.66280; the eight curves, the age and
entry buckets and both market seasons are yesterday's numbers, unread and
unmoved. What changed is the confidence band, two caches that were lying about
their inputs, and the tooling around them. The residual cache was rebuilt and
**the eight curve values were verified byte-identical afterwards** — same
keys, same payloads — which is the check that lets me say the paragraph above
without hedging.

### 1. The fit was measuring a different band from the one that ships

I went to re-derive the band and could not, because `confidence.fit` was not
reading the band's inputs. The residual cache carried no service-point count,
so the fit **substituted a recent-match count** for "how well measured is this
player" and **pinned the volatility term to the constant 1**. Two of the four
inputs a live price computes were proxies, and one of them was a constant.

The tell had been sitting in `confidence_model.json` the whole week and I had
read past it every time: **HIGH was unreachable, n = 0**. A band that cannot
produce its own top level is not a band with an empty tail; it is a scoring
function that is not the one being scored. The numbers the chain refreshed
each night described a band a live price never computes. That is rule 19 —
two derivations of one quantity will drift — one level below where it was
written, and this time the two derivations were the harness's and the app's.

The fix is in the shipped modules, not the scratchpad. `backtest.walk_forward`
takes an optional `book_out` dict and sets it to `{"book": book}` before every
yield, so a caller can read the block each match was **priced from** — the
service points behind each rating as of that match, not as of today. Its
docstring says why in one line: a band fitted on a proxy for them is a band
nobody ships. `tools/curves.py build` now stores `den` and `form_sd` on every
cache row, straight off the block and off the walk's own yield, so the band
can finally read the model saying "I am unsure about this one". Cache rebuilt,
**56,910 player-rows**, and the curve values identical after.

Then the same class of bug one level down. `tools/odds/disagree.py build` —
the cache the deficit check is measured on — read its service points **out of
the shipped `weights.json`**: today's numbers, for a match played two years
ago. A player who is well measured now was scored as well measured in 2024,
when the model had a fraction of his history. That put well-measured players
in the thin bucket and made the band's own check wrong. Same fix, same
`book_out`, cache rebuilt: 26,017 matches priced, **4,966 joined**.

Both bugs are the same shape as rule 31's broken knob, from the other side. A
knob that is not connected reads as flat; an input that is not connected reads
as a band, and it reads as a plausible one.

### 2. What the band is for, decided before anything was fitted

I wrote the target down before fitting, because the whole reason yesterday's
reading was confusing is that nobody had.

The band answers **"how much larger than usual is this model's error on a
match like this one"**. So:

**Raw log loss cannot be the target.** A coin flip scores badly for everyone —
rule 16, and the reason the band already keeps `tightness` outside itself and
prints it alongside.

**The market deficit cannot be the target either.** It is a difference between
two models, and the band describes only one of them. That is exactly how the
old ordering broke: HIGH means both players are well measured and match fit,
which is another way of saying the match is a marquee one, and a marquee match
is where Pinnacle is sharpest. A small model error against a very small market
error looks like a bad band.

So the target is **SURPRISE**: the loss minus the entropy of the model's own
price,

    surprise = -log p(outcome) - H(p)

Zero when the model is calibrated at whatever confidence it chose, positive
when it was more confident than it turned out to deserve. It needs no second
model, and it is invariant to the thing rule 16 complains about — a genuine
coin flip that the model priced as a coin flip costs nothing.

Its blind spot, stated plainly in the derivation tool rather than discovered
later: **surprise does not punish under-confidence.** A model that says 50%
when the truth is 70% pays nothing. That is precisely why the market deficit
is kept — demoted from target to **out-of-sample CHECK**. A band fitted on
surprise has to sort the deficit too, or it is only measuring itself. (And the
blind spot bit within the hour: see section 5.)

### 3. What survived, on the held-out half

`bandfit_final.py shapes` in the scratchpad: 28,455 matches from the rebuilt
cache, split in half by day, every candidate read on the train half and every
number below reported on the half it was not fitted on.

**comeback** — kept, and it is still the heaviest term. It is now the **count**
rather than a flag, because both players back from a layoff is worse than one:

| players 60+ days out | surprise |
|---|---|
| none | +0.0053 |
| one | +0.0185 |
| both | +0.0304 |

**cold** — kept. Weak but monotone, on the thinner side's matches in 28 days:
+0.0007 (4+), +0.0053 (2–3), +0.0102 (0–1).

**thin** — **dropped**, for two reasons, and the second is the better one.

| service points, thinner side | surprise |
|---|---|
| 4,400+ | +0.0120 |
| 3,000–4,400 | −0.0016 |
| 1,500–3,000 | +0.0134 |
| below 1,500 | never scored |

Above the harness's 1,500-point floor it does not sort — the best-measured
bucket carries more surprise than the middle one. And the old thresholds
(**6,000 / 3,000 / 1,000**) were set against a service-point scale this model
no longer has: at match time the **thinner** of two players runs 1,501 to
6,978 with a 99th percentile of 5,934, so "well measured" required the weaker
player above the 99th percentile and essentially never fired. That is the
second reason HIGH was unreachable — the bug in section 1 made the top band
hard to reach, and the stale thresholds made it impossible. The fourth row of
that table is empty by construction: `backtest.MIN_PTS` is 1,500 and the
harness never scores a match below it.

So what remains of `thin` is **not a fitted claim but a floor**: below 1,500
points there is no measurement at all, so a live price there takes +2 on the
score and is labelled unmeasured. The band assumes the worst in the only
direction that is safe.

**form_sd** — **dropped, sign backwards.** Steady players carry *more*
surprise: **+0.0248** at .030–.040 against **−0.0004** at .055+. Read plainly,
that is the model's own volatility term already doing its job inside the
price — when the model says a player is volatile it prices him less
confidently and is duly less surprised — so `form_sd` is not a signal *about*
the price, it is a part of it, measured twice. The one input I had been most
annoyed the cache lacked turned out to be the one input that had to go.

**best_of** — dropped from the band, and it is the finding of the day.
Section 5.

### 4. The band that ships: three levels, not four

    features(min_pts, matches_28d_min, comeback) -> {unmeasured, cold, comeback}
    score = cold + 2*comeback + 2*unmeasured
    BANDS = [(0, 0, "GOOD"), (1, 2, "FAIR"), (3, 99, "LOW")]

The fourth level is gone because it claimed a resolution the data does not
support: on the test half the old top two bands sat **within 0.004 nats of
each other and in the wrong order**. Three levels are monotone on **both**
halves of the residual cache and, independently, on the closing line — which
is rule 32's habit applied to something that is not a knob sweep.

`confidence.py fit`, out of sample on **14,228 matches** (the later half of
28,455):

| band | n | log loss | surprise | accuracy | vs closing |
|---|---|---|---|---|---|
| GOOD | 3,051 | 0.60880 | **+0.0007** | 0.6536 | +0.0132 |
| FAIR | 9,960 | 0.60841 | **+0.0068** | 0.6588 | +0.0201 |
| LOW | 1,217 | 0.61355 | **+0.0198** | 0.6311 | +0.0314 |

Look at the log-loss column: **0.6088 / 0.6084 / 0.6136**, flat, and the
middle band is the lowest. That is **rule 16 in one line**. The band the app
has been leading with for a week was the column that does not sort; the column
that sorts is surprise, 0.0007 → 0.0068 → 0.0198, nearly thirty-fold across
three levels. Accuracy is flat too, and should be — the band is not a claim
about who wins.

The check, re-measured by `tools/odds/disagree.py bands` on the rebuilt odds
cache, and it sorts:

| band | n | deficit vs closing |
|---|---|---|
| GOOD | 996 | **+0.0132** |
| FAIR | 3,518 | **+0.0201** |
| LOW | 452 | **+0.0314** |

The shipped `MEASURED_DEFICIT` constants reproduce that exactly, and the chain
re-measures them. The band it replaces, run on the **same rebuilt cache** so
the comparison is fair, still does not sort:

| old band | n | deficit |
|---|---|---|
| HIGH | 586 | +0.0232 |
| GOOD | 2,342 | +0.0179 |
| FAIR | 1,662 | +0.0190 |
| LOW | 376 | +0.0296 |

Its best level is its second-worst number, which is yesterday's finding
surviving the cache fix — so the ordering really had broken, and not merely
because the cache was reading today's service points. (The fix did move the
counts: HIGH 479 → 586, FAIR 1,552 → 1,662 against yesterday's reading, which
is exactly the well-measured-players-in-the-thin-bucket error coming out.)

A band fitted on surprise sorting a deficit it never saw is the only part of
today I would call evidence rather than bookkeeping.

### 5. A finding worth more than the band: best-of-five

`best_of` was a candidate input and it is the largest effect in the whole
sweep — in the wrong direction:

| format | surprise |
|---|---|
| best of three | **+0.0112** |
| best of five | **−0.0212** |

Negative surprise means the model is **under-confident**: over five sets it
was systematically less sure than it deserved to be. That is surprise's stated
blind spot arriving as a measurement rather than a caveat, and the only reason
I saw it is that the deficit check was still in place.

The obvious objection is that best-of-five is the Slams, and the Slams are the
best-measured matches, so `bo5` would just be `thin` wearing a hat. It is not.
Crossed against how well measured the players are, the effect holds **inside**
each bucket — within the thinnest one, best-of-three **+0.0225** against
best-of-five **−0.0177**.

A model that is under-confident in a known, pre-match-knowable subset has a
calibration error to fix in the price, not a trust level to report in a band.
So `best_of` was kept out of the band and tested directly where it belongs —
on the shipped walk's **cached predictions** (`tools/_knobsweep/prior_age/2,0.pkl`,
no new walk, in memory), fitting `form_scale` per format on the train half:

    best of 3 -> 0.70      best of 5 -> 0.50

Train 21,491 / test 21,584, best-of-five 19.5% of the test half, paired:

| | log loss | vs one scale | t |
|---|---|---|---|
| one form_scale | 0.60927 | — | |
| scale per format | **0.60899** | **−0.00028** | **+2.14** |
| best of 3 (n 17,375) | 0.62770 → 0.62770 | −0.00000 | +0.00 |
| best of 5 (n 4,209) | 0.53321 → **0.53177** | **−0.00144** | +2.14 |

Best-of-three is untouched to five places, which is the shape a real
format-specific effect should have: the overall gain is the best-of-five gain
diluted by its share of the sample, and nothing was taken from the other
format to pay for it.

**Not shipped.** `form_scale` is a scalar read by `price.scaled_form_sd` and
by `backtest.price_player`, so a format-dependent one touches the live pricing
path — plumbing, writeback, a refit chain, and the both-ways check of rule 33,
because a −0.00144 on the ratings is exactly the size of thing the eight
curves have eaten before. Recorded in `fitted_params.json` as `bo5_scale_note`
and put at the top of the next-steps list.

Worth saying out loud: I set out to build a band and the band is the smaller
half of the day. The thing that will move the price came out of a term I
threw away.

### 6. The app

`web/app.js`, the "how far to trust this one" panel. The band row now **leads
with surprise** — "on 1,217 held-out matches this band came out +0.0198 nats
worse than the model's own confidence implied" — and the realised log loss,
which led that row since the band existed, is gone from the panel entirely.
It had to go: 0.6088 / 0.6084 / 0.6136 printed under three different band
names is a number that contradicts the label above it.

The deficit against closing is printed underneath, described as the
independent check rather than what the band was fitted to. The "thinner side"
row says plainly that above 1,500 points it stopped sorting the error when the
band was re-derived and no longer moves the band, and that below 1,500 the
harness never scores a match so the band assumes the worst — a live price
should not imply a measurement that does not exist. `matchup` still says the
coin-flip caveat, now with the band's own reason beside it.

`confidence_model.json` stores surprise and accuracy per band beside the log
loss, and the deficit dict, so the app reads all three from one file (rule 7).
All six gates pass and the app was restarted and verified on the unchanged
model.

Files touched: `confidence.py` rewritten (`features` / `score` / `BANDS` /
`MEASURED_DEFICIT` / `fit`, with the derivation in its docstrings);
`backtest.py` (`walk_forward` gains `book_out`); `tools/curves.py` (the cache
carries `den` and `form_sd`); `tools/odds/disagree.py` (match-time service
points, and `bands` iterates the shipped `BANDS` instead of its own copy);
`app.py` and `web/app.js` (the panel); `confidence_model.json` and the
`bo5_scale_note` in `fitted_params.json`. The derivation itself is
`bandfit_final.py` in the scratchpad — shapes, then score.

### Where this leaves it

Two days ago the band's deficit stopped sorting and I called it a broken
measure rather than a broken band. That was half right. The measure was
wrong — a deficit cannot tell a bad model from a sharp market — but so was
the band, and worse than wrong, it was *unmeasured*: the fit had been reading
proxies for two of its four inputs and reporting a top level no price could
reach. The honest version is smaller and it sorts three ways: on surprise out
of sample, on the closing line it never saw, and on both halves of the cache.

What I did not expect is that the discipline of naming the target first is
what found the best-of-five result. Deciding that raw log loss could not be
the target forced surprise; surprise made under-confidence visible as a
negative number instead of an absence; and keeping the deficit as a check is
the only reason I trust the sign. A term dropped from the band is now item 0
on the list.

0. **Ship the best-of-five `form_scale`** (section 5): −0.00028 overall at
   t +2.14 and −0.00144 on the best-of-five themselves, measured and ready.
   Needs the plumbing, a refit chain and the rule-33 both-ways check.
1. Refresh weekly: `python3 update.py` then `sh tools/refit_chain.sh` — rule 30.
2. The curves hide rating-layer gains (rule 33); and the curve set is only
   −0.00541 now, selected against a rating layer that no longer exists.
3. The 10%+ bucket (2025 +0.054 on 495 matches, 2024 +0.072 on 497): a
   per-player refit cadence; a draw feed for a player's first match.
4. Get totals odds — the unchanged blocker.
5. Fit `news_w` from `data/news_applied.jsonl` once a few hundred matches
   carry news.
6. Or accept it as a study: the model beats tuned Elo by 0.0540 nats.
