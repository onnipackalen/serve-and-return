# Tennis pricing model

> **New session? Read [HANDOFF.md](HANDOFF.md) first**, then `data_plan.md`.
> HANDOFF has current state, the measurement rules, what was already tested and
> failed, and next steps. `data_plan.md` is the full lab notebook.

Point-based (Barnett–Clarke) match pricing with opponent-adjusted serve and
return ratings, per-player surface weights and per-player form volatility.

## Quick start

Run it with no arguments and type two players:

```bash
python3 tennis.py
```

```
[bo3] > Sinner vs Alcaraz clay bo5

Jannik Sinner  vs  Carlos Alcaraz
----------------------------------------------------------------
  as of 2026-09-08   Clay   best of 5
  Jannik Sinner     serve 0.7199  return 0.4756  form_sd 0.0192  surface w=88%
  Carlos Alcaraz    serve 0.6905  return 0.4848  form_sd 0.0320  surface w=90%

  P(Jannik Sinner)  0.6104    fair 1.638
  P(Carlos Alcaraz)  0.3896    fair 2.567
```

(Illustrative output from 2026-09-08; the ratings move with every weekly
refresh.)

Conditions go anywhere on the line: `hard | clay | grass | carpet`,
`bo3 | bo5`, and a date (`Federer vs Nadal grass 2008-07-06` prices it as of
that morning, using only matches played before it). `?` lists the rest.

Or price one matchup and exit:

```bash
python3 tennis.py price Sinner Alcaraz clay bo5
python3 tennis.py Sinner Alcaraz clay bo5     # `price` is optional
python3 tennis.py price Sinner Alcaraz --surface Clay --best-of 5   # flags too
python3 tennis.py find murray             # who matches this name?
python3 tennis.py weights Ruud            # why the model rates him as it does
python3 tennis.py vars                    # every input it accepts
python3 tennis.py gates                   # six gates; prove nothing is broken
```

**Names are forgiving.** Surname, full name, `C Alcaraz`, `Alcaraz, Carlos`,
`del potro` and outright typos (`Alcarez`, `Djokovis`, `Sinnner`) all resolve;
the output says when it read a typo as something else. A shared surname goes to
the more prominent player and names the runner-up (`Zverev` -> Alexander, also
matched Mischa). A name that matches nothing suggests the nearest ones instead
of exiting. `players.py` holds this and is one of the gates.

Multi-word names need quotes or a `vs`: `price "del potro" Sinner`, or
`price Juan Martin del Potro vs Sinner`. Two separate arguments are always two
players, so quoting is never ambiguous.

Every price states the newest match in the data, and flags how many days of
results are missing when that falls behind.

## Injury and player news

The measured gap to the market is **ordering**, and every injury proxy the
match log can produce has measured to zero. What the market has and the log
does not is news. This is the channel for it:

```bash
python3 tennis.py news --prompt "Carlos Alcaraz"   # the prompt to hand an assistant
python3 tennis.py news --add report.json           # store the JSON it returns
python3 tennis.py news                             # what is on file
```

The prompt asks for strict JSON — availability, a fitness severity 0–3, where
the problem is, how well sourced it is — and, since 2026-09-11, an **impact**
block in the model's own units, because the prompt tells the assistant what
those units are worth: one point of serve-points-won taken off a player moves
a coin-flip best-of-three by about 4.4 points of win probability and a
best-of-five by 5.2. A report moves a price through three levers, each in
the unit that thing has:

* **level** — points of serve and return rate the problem costs, entering
  where the ratings do, so best-of, surface and opponent still shape it;
* **uncertainty** — a multiplier on the player's match-day volatility, because
  "in doubt" is a wider range of outcomes, not only a lower mean;
* **retirement risk** — the probability they start and do not finish, folded
  in last; a retirement is a loss.

Every claim that moves a price has to carry a source. Reports decay with a
21-day half-life and are halved again once the player has completed two
matches since.

**These weights are a prior, not a fit, and the code says so everywhere.**
No archive exists of what the news said on the morning of each past match. A
report without an impact block falls back to severity anchors *solved*
against a stated reference — an even best-of-3, the cost split evenly — to
move the price by exactly **2.0, 6.0 and 13.0 points**. Every application is
logged to `data/news_applied.jsonl`, which is the archive that does not exist
yet; once a few hundred matches carry news, that file plus the results makes
the weight measurable. Set `news_w` to 0 to switch the channel off.

`available: false` makes the model **refuse** to price the match. A withdrawal
is not a 95% favourite.

### Working the news channel, step by step

1. **Price the match first**, with nothing on file, and note the number.
   Everything the log knows is already in it; the report is only for what
   the log cannot see.
2. **Get the prompt for each player** — `python3 tennis.py news --prompt
   "Carlos Alcaraz"` — and hand it to an assistant that can browse. Do both
   players: a report on only one side is a thumb on the scale.
3. **Read what comes back before storing it.** The JSON must name a source
   for every claim that moves the price; if the `impact` numbers look larger
   than the reporting justifies, edit them down — you are the last check. An
   empty `sources` list with severity 0 is the most common honest answer.
4. **Store it** — `python3 tennis.py news --add report.json` (or `--add -`
   and paste). Validation rejects impact without sources, impact with
   severity 0, and anything out of range.
5. **Price again.** The output shows exactly what the report did: the
   serve and return shift, the volatility multiplier, the retirement risk
   as a separate line, and the source count. Compare with step 1; the
   difference is the news, and only the news.
6. **Let it age.** A report halves every three weeks on its own and halves
   again once the player completes two matches; you do not need to remove
   it after the match. Use `--clear "Name"` only when it is wrong, and
   re-run the prompt when something new is reported.
7. **Keep the log.** Every priced match with news on file is appended to
   `data/news_applied.jsonl`. After a few hundred of them, that file plus
   the results is what turns `news_w` from a prior into a fitted weight.

In the browser view the same flow is one panel on the player page: copy
the prompt, paste the answer, and the price updates.

## Browsing it

```bash
python3 tennis.py app
```

Opens `http://127.0.0.1:8765/` — the whole tool with a face on it. The
command line is faster once you know whose price you want; this is for when
you do not. It is meant to take three keystrokes' worth of thought:

1. **Type a surname and press Enter.** That is player A. The search uses the
   same forgiving resolver as the CLI, searches *everyone* regardless of the
   data filter (a thin rating is marked, not hidden), and ↑↓ pick a different
   match before Enter. Clicking a name works too.
2. **Type another, press Enter.** Player B. The call appears: the two
   probabilities, fair odds, and a one-line reading ("Sinner 60.7%, a lean —
   fair odds 1.65; confidence LOW") with a *copy the call* button.
3. **Name the tournament**, optionally. It sets the surface and the format
   from the archive's record of that event ("clay, best of 5 — as last played
   there"), brings in the venue's elevation and cached weather, and lets the
   form/run curves see the draw. Change either control if this edition
   differs.

Everything else is optional and explains itself in place:

* **Bookmaker odds.** Type the two decimal prices and the page shows the
  market's opinion with the margin removed, the model's, and the difference
  in points — with the measured caveat printed beside it: against Pinnacle
  closing the model is about 0.02 nats *behind*, all of it in confident
  disagreement, so a large difference is a question, not an edge. The odds
  are compared with the call, never used in it.
* **Entry type** for each player (main draw, qualifier, wild card, lucky
  loser, protected ranking, special exempt). Since 2026-09-14 the results
  feed carries it for every match already played, so the page shows it once
  a player has played at the event; for a first match it is asked and never
  guessed.
* **How far to trust this one.** The band, and under it what that band
  actually did on held-out matches: how much worse it came out than the
  model's own confidence implied. The deficit against Pinnacle closing is
  printed below that as the independent check. The service-point row says
  plainly that above 1,500 points it no longer moves the band, and below
  them the band assumes the worst because nothing there was ever measured.
* **The address bar carries the match.** Reload, bookmark or paste the link
  and it comes back with the same players and conditions.
* **On a phone** the index sits above the match and folds away once two
  players are in; *change players* brings it back.
* **The roster**, every rated player ranked by what the model says they would
  do against a tour-average opponent — the model evaluated at a fixed
  reference, not a new quantity. Sort by serve, return, volatility or how much
  data is behind the rating; filter to a surface.
* **Totals**, with the fitted bias correction shown *beside* the raw
  simulation rather than instead of it — the gap between the two is the
  correction, and hiding it would make a fitted adjustment look like a fact.
* **A player page** — surface splits with their shrinkage weights, form
  volatility against the tour, the current run, the player's own residual
  against the point model, and recent matches with the rest and workload each
  was played under; plus the injury-news box with the prompt to hand an
  assistant.
* **The model page** reads its numbers from the files the refit writes
  (`fitted_params.json`, `data/market_check.json`) rather than from the page
  source — the typed-in numbers it used to carry were stale within a day.

Every price and every simulation carries a collapsed panel holding the
*literal* output of `tennis.py price` / `tennis.py sim`. The page computes
nothing of its own; if the layout ever disagreed with the tool, that panel is
where you would see it disagree.

It binds to `127.0.0.1` only. The data is CC BY-NC-SA 4.0 — personal,
non-commercial use — and serving it on the network would be redistribution.

## Staying current

```bash
python3 update.py        # mirror + new results + weather, then re-verify
python3 tennis.py fit    # re-derive the weights
sh tools/refit_chain.sh  # or the whole chain, which re-measures every number below
```

**Run both once a week.** The model ships at a 7-day refit cadence, and the
cadence is a commitment, not a setting: the headline below was measured with
ratings that were never more than seven days stale, so the live price is the
measured one only while `update.py` and a refit run weekly (rule 30). Let the
data drift and what ships is a staler cadence than the one measured — the
ladder under *Refit cadence* is the price of that (+0.00080 at 14 days,
+0.00154 at 21, against 7) — and every price prints how many days of results
are missing, so the drift is never silent.

The first weekly refresh ran on 2026-09-14. `update.py` found the mirror
still dead (a no-op), then `tools/ta/refresh.py` fetched 427 player pages
from tennisabstract.com and rebuilt `data/manual_matches.csv`: 969 rows (was
965), 782 of them with full serve stats (was 701; the 2026 US Open now has
127 rows, 91 with stats), dated 2026-05-25 to 2026-08-31 (the archive dates a
match by its tournament's start, so the US Open sits at 2026-08-31). The
weather cache was extended to 2026-09-14 and provenance re-verified — 80,150
matches, 91.1% passing the arithmetic identities, tour average serve 0.6320,
VERIFY PASS — about 15 minutes in all. Then `sh tools/refit_chain.sh`, which
rebuilds every artefact in the order they depend on each other — weights,
the backtest, the path sweep, the residual cache and curves, the confidence
bands, both market seasons, the six gates — and took about 25 minutes
uncontended (22:52 to 23:18 by the chain log's file times; the script's
header now says about 25 minutes uncontended and ~1.5 hours contended, which is what it cost on 2026-09-12 with other
walks sharing the machine, when the path sweep alone took 3,711 s against
383 s this time).

The whole chain was run again on 2026-09-15, on the same archive, when the
rating layer's prior became age-dependent — no new data, every artefact
re-measured under the new prior, all six gates passing again. **Every current
number below is from that chain**; an older measurement quoted beside one
carries its date, cadence or prior.

Sackmann's repos are deleted and the mirror is frozen at 2026-05-25, so new
results come from **tennisabstract.com** via `tools/ta/`. That source publishes
serve *percentages*, not counts; the counts are recovered by solving for the
one denominator all five rates share. Verified exactly against every match the
archive already had:

```bash
python3 tools/ta/gate.py     # 373/373 exact, completeness 0 missing either way
```

First run for a given date derives the ratings (~4s) and caches them; after
that a price is instant.

## What actually drives the number

**Test log loss 0.60885** on 22,427 test matches — one walk-forward over the
43,075 scorable matches, 20,648 of them training, refitting the ratings every
7 days with the **age-dependent** prior, on the archive refreshed 2026-09-14 —
against **0.66280** for an Elo (K = 4, results only) scored on the same
22,427 matches: the model beats Elo by 0.0540 nats. The figure is not
comparable to 0.61059 (the same archive with the flat player-specific prior,
shipped on 2026-09-14), nor to 0.61140 (22,420 test matches on the archive
before the refresh, with the tour-average prior, shipped late on 2026-09-12),
nor to 0.61295 (22,344 at the 21-day cadence) or 0.61227 (22,385 at 14 days,
both superseded that day), nor to 0.61720 (22,012 at 91 days, 2026-09-11),
nor to any earlier headline (0.61797, 0.61929, 0.61400, 0.61791): the
scorable set moves with the archive and the cadence. The honest numbers are
the paired ones. For the prior, −0.00175 at t = +6.94 on 43,075 identical
matches against the flat own prior, which was itself −0.00091 at t = +2.92
against the tour average (the sweep is under *Refit cadence and the other
constants* below; what the curves were already doing about it is directly
after this ladder). For the cadence, each step against the value that had
just shipped —
21 vs 91 −0.00413 at t = +7.06 on 40,374 common matches, 14 vs 21 −0.00074
(t = +2.74), 7 vs 14 −0.00080 (t = +3.72) — and the full ladder against the
shipped 7. The ladder, each layer measured with the ones before it present:

| model | test log loss | vs previous | paired t |
|---|---|---|---|
| coin flip | 0.69315 | | |
| Elo, K = 4, results only | 0.66280 | | |
| one tour-wide rating, form_sd 0.040 | 0.61418 | | |
| one tour-wide rating + calibration | 0.61425 | +0.00007 | −2.70 |
| per-player surface weights + form (scale 0.70) | 0.61066 | | |
| + in-event update (w = 2) | 0.60893 | −0.00173 | +5.67 |
| + air density (w = 0.40) | **0.60885** | −0.00009 | +4.04 |
| + calibration slope 1.009 (measured, not applied) | 0.60891 | +0.00007 | −3.09, so off |
| three-stage serve on (measured, not shipped) | 0.61499 | +0.00615 vs shipped | −8.85 |

**And the correction layer was already doing most of it.** The age-dependent
prior was measured *both ways* — on the ratings, and again after the eight
residual curves — on two residual caches built the same way, paired over the
22,759 matches both price:

| the age-dependent prior, against the flat own prior | change | paired t |
|---|---|---|
| on the ratings alone | **−0.00181** | **+7.17** |
| after the eight correction curves | +0.00016 | −0.80 |

So the moneyline price barely moves: the curves were already correcting most
of what the prior fixes, and a fitted corrector sitting on top of a rating
layer hides an improvement underneath it (rule 33). It ships anyway, on four
counts the after-the-curves number does not capture. The gap to the closing
line, measured *before* the curve layer, improved on both seasons
(+0.02027 → +0.01857 in 2025, +0.02230 → +0.02012 in 2024) and the 10%+
disagreement bucket shrank in both. The games-totals path takes the serve
probabilities directly and never sees the curves, so nothing hides the gain
there. The correction layer itself
shrank from −0.00738 to −0.00541, so less of the shipped answer is a fitted
residual shape. And the age curve — the thing that prompted the change —
halved, from a +0.085 youngest-minus-oldest spread costing +0.00227 to drop,
to +0.056 costing +0.00091. What would have been false is "the price moved".

Live: **surface**, **best-of**, **as-of date**, per-player **form volatility**,
per-player **surface weights**, **air density** (temperature + elevation +
humidity, with indoor venues zeroed), **entry type** when it is known, and
the eight residual **correction curves** below. A calibration slope is fitted
as well and is **off, by its own test**: it measures 1.009, and applying it
moves the test loss from 0.60885 to 0.60891 (+0.00007 at t = −3.09). The
per-player form volatility already absorbs the overconfidence a slope is
built to fix. The decision has flipped with the cadence, always by the same
test: off at 91 days (1.012; 0.61720 → 0.61728), on at 21 days, where it
measured 0.997 and was effectively identity (0.61297 → 0.61295), off again
at 14 days (1.006; 0.61227 → 0.61230), at 7 with the tour-average prior
(1.012; 0.61140 → 0.61147), at 7 with the flat player-specific prior (1.007;
0.61059 → 0.61066) and at 7 with the age-dependent one (1.009; 0.60885 →
0.60891).

Air density is symmetric — both players share the conditions — so it barely
moves the moneyline. It is applied anyway because pricing should match what
the backtest fitted, and because the games-total model needs the same plumbing.

```bash
python3 tennis.py price Sinner Alcaraz clay --at Gstaad     # venue + cached weather
python3 tennis.py price Sinner Alcaraz --temp-c 30 --elevation-m 2640
```

Recorded but *not yet fitted*: wind, rest days, cumulative minutes, level,
round. `price.py` accepts them, prints them, and tells you it ignored them.
It does not pretend.

## Against the market, and how sure a price is

`tools/odds/m4.py` scores the walk-forward model — before the curve layer
and news — against Pinnacle's closing line with the margin removed
proportionally, and since 2026-09-12 writes the result to
`data/market_check.json`, which is where the app's model page reads it. At
the 7-day cadence with the age-dependent prior, on the archive refreshed
2026-09-14:

| season | matches | model | closing | gap (model − closing) |
|---|---|---|---|---|
| 2025 | 2,388 | 0.62230 | 0.60373 | +0.01857 (was +0.02027 with the flat own prior, +0.02159 with the tour-average one, +0.02252 at 21 days, +0.02201 at 14) |
| 2024 | 2,512 | 0.60568 | 0.58556 | +0.02012 (was +0.02230 with the flat own prior, +0.02228 with the tour-average one, +0.02382 at 21 days, +0.02325 at 14) |

This time the prior helped both seasons, which is part of why it ships: the
walk-forward gain it measures on the ratings (−0.00181 at t = +7.17) is
mostly hidden by the curve layer downstream, and this check is taken
upstream of it. The gap lives where the two disagree. By |model − closing|,
2025 runs +0.0005 at 0–2% (n 510), +0.0058 at 2–5% (697), +0.0196 at 5–10%
(686) and +0.0537 at 10%+ (495); 2024 −0.0019 (555), +0.0043 (718), +0.0173
(742) and +0.0718 (497). The 10%+ bucket — where the whole gap lives — shrank
again in both seasons, 555 → 495 and 540 → 497 matches: fewer confident
disagreements each time the rating layer improves. The eight-curve layer
(−0.0054 walk-forward) is applied downstream of this check, so the live gap
is roughly +0.013 in 2025. That is the caveat the app prints beside any
bookmaker odds you type in: a large disagreement is a question, not an edge.

Every price also carries a confidence band (`confidence.py`, written to
`confidence_model.json`), **re-derived on 2026-09-16** after its market
number stopped sorting. The re-derivation found the band had been fitted on
proxies: the residual cache carried no service-point count, so the fit
substituted a recent-match count for "how well measured is this player",
pinned the volatility term to a constant, and produced a score that could not
reach its own top band — HIGH was unreachable, n = 0, so the band being
measured was not the band a live price computed. The cache now carries the
service points behind each rating *as of that match* and the model's own
`form_sd`; the same bug sat one level down in `tools/odds/disagree.py`, whose
cache had been reading today's service points for matches played two years
ago. Both are fixed and rebuilt, and the eight curve values are byte-identical
afterwards.

**What the band is fitted to, decided before anything was fitted.** Not raw
log loss: a coin flip scores badly for everyone (rule 16). Not the deficit
against the market either, which is what the old band used — a deficit is a
difference between two models and the band describes only one of them, so it
cannot separate "the model is bad here" from "the market is unusually good
here", and that is exactly how the old ordering broke. The target is
**surprise**: the loss minus the entropy of the model's own price, zero when
the model is calibrated at whatever confidence it chose and positive when it
was more confident than it deserved. Its blind spot is that it does not
punish under-confidence, so the market deficit is kept as the independent
out-of-sample check.

**Three levels, not four**, measured out of sample on 14,228 matches:

| band | n | log loss | surprise | vs closing |
|---|---|---|---|---|
| GOOD | 3,051 | 0.60880 | +0.0007 | +0.0132 |
| FAIR | 9,960 | 0.60841 | +0.0068 | +0.0201 |
| LOW | 1,217 | 0.61355 | +0.0198 | +0.0314 |

Both measures sort, and the check sorts where the old band's did not
(HIGH +0.0232, GOOD +0.0179, FAIR +0.0190, LOW +0.0296). The fourth level
went because it claimed resolution the data does not support: on held-out
matches the old top two sat within 0.004 nats of each other and in the wrong
order. Note the raw log loss is nearly flat across the bands — that is rule
16 in one line, and it is why a price now leads with surprise and prints the
deficit underneath as the check rather than the target.

**What feeds it**, with the measured reasons. The layoff count survives and is
the heaviest term (+0.0053 / +0.0185 / +0.0304 for neither, one and both
players returning), and is now the count rather than a flag. Cold form
survives, weakly (+0.0007 / +0.0053 / +0.0102 for 4+, 2–3 and 0–1 matches in
28 days on the thinner side). The service-point term was **dropped** on two
counts: above the harness's 1,500-point floor it does not sort at all
(+0.0120 for the best measured, −0.0016, +0.0134), and its thresholds of
6,000 / 3,000 / 1,000 were set against a scale this model no longer has, since
the thinner of two players now runs 1,501 to 6,978 with a 99th percentile of
5,934. What remains of it is a floor rather than a claim: below 1,500 points
nothing was ever measured, so a live price there is assumed to be the worst
case. `form_sd` was dropped because its sign is backwards — steady players
carry *more* surprise, which is the model's own volatility term already
working inside the price rather than a signal about it.

**And the one it refused.** The re-derivation wanted the match format badly:
best-of-five matches carry −0.0212 surprise against +0.0112 for best-of-three,
and it survives conditioning on how well measured the players are. That is not
a trust level. It says the model is systematically *under-confident* over five
sets, which is a calibration error to fix rather than a caveat to print, so it
was kept out and tested directly instead: a volatility scale fitted per format
wants 0.70 for three sets and 0.50 for five, worth −0.00144 on the five-setters
themselves at t = +2.14 and nothing at all on best-of-three. Measured, real,
and **not shipped yet** — it reaches into the live pricing path and wants its
own pass.

## Refit cadence and the other constants

Five constants had been chosen rather than fitted. On 2026-09-12
`tools/knobsweep.py` swept each one: a full walk-forward per value in its own
subprocess (the constants are module-level, read once at import), `form_scale`
fitted per value, every value scored on the intersection of what they all
price and paired against the shipped value with a per-match t. Two moved. On
2026-09-14 the same tool measured what the rating is shrunk *toward*
(`prior_mode`, which moved), re-swept `prior_weight` under the new prior, and
`tools/traitsweep.py` swept the last two chosen constants of the correction
layer (flat). On 2026-09-15 it swept how much of that prior survives at each
end of a career (`prior_age`, which moved), fourteen values scored on both
halves.

* **`refit_days`** — how often the harness refits the rating layer, 91 by
  convenience until 2026-09-12. It was walked down one step at a time, each
  step paired against the value that had just shipped, and the whole chain
  rebuilt at every step that was adopted:

  | step | paired vs the shipped value | t | common / test matches |
  |---|---|---|---|
  | 182 vs 91 | +0.00410 | −5.38 | 40,374 / 21,378 |
  | 45 vs 91 | −0.00135 | +2.61 | 40,374 / 21,378 |
  | 30 vs 91 | −0.00252 | +4.54 | 40,374 / 21,378 |
  | **21 vs 91** | **−0.00413** | **+7.06** | 40,374 / 21,378 — adopted |
  | **14 vs 21** | **−0.00074** | **+2.74** | 41,816 / 21,902 — adopted |
  | **7 vs 14** | **−0.00080** | **+3.72** | 41,803 / 21,899 — adopted, **ships** |
  | 3 vs 7 | −0.00023 | +5.38 | 41,801 / 21,898 — measured, not adopted |

  The full ladder against the shipped 7 on the 41,801 matches every cadence
  prices (21,898 test): 3 −0.00023 (t +5.38); 7 shipped, 0.61112 on that
  intersection; 14 +0.00080 (t −3.72); 21 +0.00154 (t −5.49); 91 +0.00560
  (t −9.30). Monotone all the way down, and the largest single gain of the
  day. `form_scale` is 0.50 at every cadence from 21 days down, from 0.60 at
  91, under the tour-average prior (0.70 under the player-specific priors
  shipped since 2026-09-14, the flat one and the age-dependent one alike):
  fresher ratings need less volatility. **7 ships**, and the chain that
  shipped it ends with all six gates passing. 3 is measured, real (t 5.4)
  and not adopted: the gain is 0.0002 nats, and the cadence is a promise —
  the headline only holds if the live ratings are refreshed at that cadence
  (`update.py`), the results mirror has been frozen (847 reconstructed rows
  then, 969 after the 2026-09-14 refresh), and weekly is the cadence the tool
  can actually keep (rule 30). Switching is
  one refit chain: set `refit_days` in `fitted_params.json` or
  `TENNIS_REFIT_DAYS=3`. Cost: a refit lands on the first tournament day at or past
  the due date, and tournaments start weekly, so the counts are what the
  logs show — 72 refits at 91 days, 258 at 21, 372 at 14, 633 at 7 (392 s
  contended; 634 on the archive refreshed 2026-09-14), 708 at 3 (598 s): a
  3-day cadence buys only the mid-week starts, which is why it costs half
  again as much as 7 rather than twice.
* **`carry_cap`** — the cap on the recent-form shift carried onto the surface
  rating, 0.05 until 2026-09-12. On 42,169 common matches, paired against 0.05:
  0.03 +0.00157 (t −3.98); **0.08 −0.00047 (t +2.17), adopted**; 0.10 −0.00049
  (t 2.01); 0.12 −0.00051 (t 1.96); no cap −0.00053 (t 1.90). A plateau from
  0.08 up; the smallest change with the highest t ships.
* **`surface_half_life_days`** (42,169 common): 730 +0.00015 (t −0.74); 1095
  shipped; 1460 −0.00006 (t +0.84); 2190 +0.00006 (t −0.39). Flat; stays.
* **`long_years`** (42,169): 8 +0.00004 (t −0.45); 12 shipped; 16 +0.00004
  (t −0.95). Flat; stays.
* **`AGE_KNOTS`** (40,960 common): (20, 26, 32) +0.00044 (t −2.94);
  (22, 28, 34) shipped; (24, 30, 36) +0.00005 (t −0.42). Stays.
* **`prior_mode`** — what the 270-day rating is shrunk toward by
  `prior_weight`. The tour average (`tour`) until 2026-09-14; then the
  player's **own** long-window rating (`own`), the 12-year,
  1,095-day-half-life fit that already exists for the surface carry-over, so
  a player back from a layoff is pulled toward who they were rather than
  toward the middle of the tour; and since 2026-09-15 `age`, which keeps only
  an age-dependent share of that own rating — see `prior_age` below. Measured
  inside the
  shipped path (`tools/knobsweep.py run prior_mode own`): two walks at the
  7-day cadence, cap 0.08, on the archive refreshed 2026-09-14, 43,075
  identical matches (train 20,648 / test 22,427) — **own −0.00091 at
  t = +2.92 against tour, adopted**. `form_scale` refits from 0.50 to 0.70
  under it and the tour-wide `form_sd` from 0.030 to 0.040.
  `TENNIS_PRIOR_MODE` overrides it, and `backtest.py` writes it back to
  `fitted_params.json` (rule 7).
* **`prior_age`** — **how much of a player's own deviation from the tour
  average survives into that prior, at each end of a career.** The prior is
  no longer one thing for everyone: it is the tour average plus `w(age)`
  times the player's own deviation from it, and `w` runs on
  `ratings.age_multiplier` with the same `AGE_KNOTS` (22, 28, 34) the
  age-dependent half-life uses — so "young, prime, old" has one definition in
  this project (rule 19) and the knob only ever moves the ends. The shipped
  **(2, 0)** reads: **double the deviation at 22 and under, the player's own
  level at 28, the tour average at 34 and over.** (1, 1) is exactly
  `prior_mode own`, verified equal to 0.0 before any walk ran, which is the
  sweep's own baseline (rule 31); a player with no birthday keeps the own
  prior, the same fallback the age-dependent half-life makes.

  Why an age ramp at all: the own prior of 2026-09-14 made the age *curve*
  bigger, not smaller (youngest minus oldest +0.075 → +0.085), and the
  mechanism was plain. The 12-year window holds a declining player's peak and
  a rising player's junior years, and the prior bites hardest exactly where
  the 270-day window is thin — at the shipped as-of day, 263 of the 292 rated
  players past 34 are under 1,500 service points, and 421 of the 436 under 22.

  Swept by `tools/knobsweep.py run prior_age`: fourteen values, one walk
  each, paired on 43,075 identical matches (test 22,427) against (1, 1).

  | (young, old) | vs the own prior | t |
  |---|---|---|
  | 0, 0 | +0.00083 | −3.42 |
  | 0.5, 0.5 | +0.00033 | −2.90 |
  | 0.5, 0 | −0.00007 | +0.36 |
  | 1, 1 | the own prior itself, shipped 2026-09-14 | |
  | 1, 0.5 | −0.00032 | +3.06 |
  | 1, 0 | −0.00075 | +4.31 |
  | 1, −0.5 | −0.00095 | +3.63 |
  | 1, −1 | −0.00094 | +2.62 |
  | 1.5, 0 | −0.00121 | +5.76 |
  | 2, −0.5 | −0.00174 | +5.20 |
  | **2, 0** | **−0.00175** | **+6.94** — adopted |
  | 2.5, 0 | −0.00191 | +5.97 |
  | 3, 0 | −0.00189 | +4.73 |
  | 4, 0 | −0.00198 | +3.84 |

  Damping the **old** end helps; damping the young end **hurts**, and the
  young end wants amplification. Both edges were probed until they turned
  over (rule 26). From (2, 0) upward the loss flattens while the t falls away
  and `form_scale` starts climbing (0.85 at (4, 0)), so the plateau begins at
  2 and the smallest change with the highest t ships — exactly as `carry_cap`
  did. `TENNIS_PRIOR_AGE` overrides it; `backtest.py` writes it back (rule 7).

  **The guard.** Fourteen values chosen by held-out log loss is fourteen
  draws from one test half, so `tools/knobsweep.py compare prior_age --both`
  now scores every value on **both** halves and flags any that wins only on
  test (rule 32). Every value that won on test also won on train, in the same
  order — the adopted (2, 0) is −0.00096 at t +4.85 on the train half beside
  its −0.00175 at +6.94 on test — and the only `TEST ONLY` row was (0.5, 0)
  at −0.00007, the one value in the sweep small enough to be noise either way
  (+0.00021 at t −1.60 on train).

  **And it was measured both ways** (rule 33): −0.00181 at t = +7.17 on the
  ratings, +0.00016 at t = −0.80 once the eight curves are applied. Why it
  ships anyway is under *What actually drives the number* above.
* **`prior_weight`** (150, fitted against the tour-average prior) — re-swept
  under the own prior, `TENNIS_PRIOR_MODE=own tools/knobsweep.py run
  prior_weight 100 300 600`, all four values on the same 43,075 matches: 100
  −0.00002 (t +0.39); **150 shipped**; 300 +0.00053 (t −4.71); 600 +0.00118
  (t −5.58). Stays 150. The first run of this sweep returned four *identical*
  walks — 0.61059 at t 0.00 for every value — because `backtest.py` read
  `PRIOR_W` (and `HALF_LIFE`) from `fitted_params.json` itself rather than
  from `weights.py`, so the override moved the live derivation and not the
  harness; fixed the same day (one source for the rating-layer constants,
  rule 19, and the harness == `weights.json` gate still passes), and written
  down as rule 31.
* **`TRAIT_K` / `TRAIT_MIN`** (40 / 15) — the shrinkage `n/(n+K)` and the
  row floor of `resid_prior`, the last two chosen constants of the correction
  layer. Swept on 2026-09-14 by `tools/traitsweep.py` on the residual cache
  (56,754 player-rows at the 7-day cadence): each cell re-annotates the cached
  rows, refits the eight curves per fold and scores the shipped antisymmetric
  log-odds application at k = 1, paired per match on 22,697 identical
  matches. K in {10, 20, 40, 80, 160, 320} × MIN in {5, 10, 15, 25, 40} is
  flat: the best cell, (40, 10), is −0.00007 at t +1.07; MIN = 40 costs
  +0.0002–0.0003 at t −1 to −1.5 for every K; K = 320 costs
  +0.00013–0.00032. **(40, 15) stays.**

The `TENNIS_*` environment overrides (`TENNIS_SURFACE_HL`, `TENNIS_LONG_YEARS`,
`TENNIS_CARRY_CAP`, `TENNIS_REFIT_DAYS`, `TENNIS_AGE_KNOTS`, `TENNIS_TRAIT_K`,
`TENNIS_TRAIT_MIN`, `TENNIS_PRIOR_MODE`, `TENNIS_PRIOR_AGE`,
`TENNIS_PRIOR_WEIGHT`) exist for the
sweep, and the backtest writeback now carries `carry_cap`,
`surface_half_life_days`, `refit_days`, `prior_mode` and `prior_age` into
`fitted_params.json` (and, for the app's model page, `test_matches` and
`elo_log_loss`), so a swept value survives the next refit (rule 7). The
cadence is a model parameter, not a convenience: it decides how stale every
rating is between refits (rule 29) — and it is a commitment: the measured
number assumes the shipped ratings are never staler than the cadence, so
ship the cadence you will actually refresh at (rule 30).

## Simulating a match

`price` gives P(win) from an exact recursion. `sim` plays the match point by
point, so you get the whole distribution — total games, set scores, how often
it goes the distance:

```bash
python3 tennis.py sim Sinner Alcaraz clay bo5
python3 tennis.py sim Zverev Fritz --at Cincinnati -n 50000
```

Both paths are fed identical serve probabilities, so the simulator prints the
recursion's answer beside its own and flags any gap wider than simulation
noise. That is a free correctness check on every run, and it is why the
totals below it can be trusted.

## Form and run curves

`fitted_curves.json` holds **shapes, not weights**. A single coefficient on
"wins banked at this event" fits to ~zero because the effect is a hump, and
calling that "no effect" was wrong. `tools/curves.py` fits bucketed curves
with shrinkage and validates them on rolling time folds.

What survived, and what did not:

What decides adoption is not how a curve scores alone but what the set loses
without it (`tools/curves.py loo`) — near-substitutes each look positive and
cancel in company. "Alone" below is a single split on the final residual
cache; "cost of dropping" is leave-one-out from the set of eight, 4 folds.

| covariate | alone | cost of dropping | |
|---|---|---|---|
| **`entry`** | −0.00045 | **+0.00100** | how the player got into the draw; qualifiers beat their price by 3.6 points, lucky losers miss it by 0.9; the cost doubled from +0.00049 once the reconstructed rows carried codes, and it is now the largest of the eight |
| **`age`** | −0.00060 | **+0.00091** | a decaying rating lags a rising player; halved (from −0.00148 / +0.00227) once the prior itself became age-dependent |
| `event_gwp` | −0.00083 | +0.00090 | games-won share so far at this event |
| `resid_prior` | −0.00045 | +0.00088 | the player's own prior walk-forward residual, shrunk: does this player beat the point model |
| `matches_28d` | −0.00040 | +0.00083 | match fitness; cold players underperform |
| `form_spw` | −0.00026 | +0.00026 | 28d serve level vs their own 365d |
| `event_sets_lost` | −0.00017 | +0.00022 | sets dropped getting here |
| `home` | −0.00010 | +0.00015 | playing in your own country |

Applied together, antisymmetrically and in log-odds: **−0.00541 nats, 4 of 4
folds, k = 1** (0.60883 without the curves, 0.60341 with them), fitted on
residuals of the pricing path that actually ships (`tools/residuals.json`:
56,910 player-rows, 28,455 matches, rebuilt on 2026-09-15 at the 7-day
refit cadence with the age-dependent prior, carry cap 0.08 and the shipped
(0.50, 0.85) multipliers, on the archive refreshed 2026-09-14). The same
eight were worth −0.00738 on the 7-day cache with the flat own prior,
−0.00735 with the tour-average prior, −0.00807 on the 21-day cache and
−0.00999 on the 91-day one (where the seven of 2026-09-11 were worth
−0.00941): fresher, better ratings absorb part of what the curves corrected —
the expected direction, and the same thing the age half-life did to the age
curve. The layer has lost more than a quarter of itself in one step,
−0.00738 → −0.00541, and most of that is the age curve halving: the prior now
does at the rating layer what the curve was doing downstream, which is where
it belongs. Every curve still earns its place, but
`entry` has passed `age` as the one the set can least afford to lose. The
magnitude stays at its natural value: k = 1.25 scores −0.00564, k = 1.5
−0.00543, k = 2 −0.00372 and helps only 3 of 4 folds, and the scale chosen on
each fold's train half scores 0.60340 against 0.60341 at k = 1, so k stays 1.
On the six-curve set the train halves had preferred k = 1.5; the seventh
curve absorbed what the larger magnitude was compensating for, so there is no
new tunable.

`resid_prior`, the seventh curve adopted, is the player's mean walk-forward
residual (`y − p`) over their prior cached rows, shrunk by `n/(n+40)`, none
until 15 prior rows (both constants swept on 2026-09-14 and flat — see
*Refit cadence and the other constants*); rows from the same day never see
each other. Split-half
reliability, measured on 2026-09-11 on the 91-day cache, says the trait is
real but modest: +0.243 across all matches (0.391 full-sample, 286 players
with 40+ rows), and only +0.083 / 0.153 on best-of-five alone (97 players).
The shrunk curve as shipped in `fitted_curves.json` runs from −0.028 for the
bucket below −0.04 (4,036 rows) to +0.024 above +0.04 (11,168), the ends
still ordered but the middle buckets no longer sorting cleanly (−0.033 to
+0.028 on the 7-day cache with the flat own prior, −0.032 to +0.035 with the
tour-average one, −0.035 to +0.036 on the 21-day cache): the better the
ratings get, the less of this trait is left to read. At the
extremes of the shrunk trait on the 21-day cache of 2026-09-12: Flavio
Cobolli +0.116 (n 173), Learner Tien +0.108 (101), Alexander Bublik +0.107
(370); Hugo Dellien −0.133 (89), Rogerio Dutra Silva −0.121 (60), Facundo
Bagnis −0.113 (117). Live prices read it from `data/player_traits.json` (384
players, written by `tools/curves.py write`), and the workload gate asserts
that live pricing supplies all eight curve inputs.

`entry`, the eighth, is how the player got into the draw — main draw, Q, WC,
LL, PR or SE. Until 2026-09-14 the reconstructed results feed carried no
entry column (965 rows before the refresh, none with a code); Tennis Abstract does print every
player's draw prefix — "(Q)", "(WC)", "(LL)", "(Alt)", or a seed number — and
`tools/ta/build.py` now reads it instead of stripping it, so 341 of the 969
reconstructed rows carry a code and 579 a seed. When an archive row at the
same event already carries the player's code, the price reads it off those
earlier rows; for a player's first match at an event — the draw is not in the
archive until it is played — it asks instead: `--entry-a Q --entry-b main` on
the command line, `entry a Q` in the prompt (`entry off` clears both), and two
selects, "A entered as" / "B entered as", in the app, which swap with the
players. Otherwise the entry is unknown and there is no adjustment — it is
never guessed as main draw. The shrunk buckets on the
7-day cache with the age-dependent prior, the reconstructed rows carrying
their codes: main draw −0.005 (n 46,743), Q +0.036 (5,740), WC +0.005
(2,582), LL −0.009 (1,218), PR +0.006 (369, thin), SE −0.001 (189), anything
else −0.005 (69). Qualifiers beat their price by 3.6 points (3.7 with the
flat own prior, 2.3 with the tour-average one: a prior built from a player's
own history shrinks a qualifier toward a thin, low record, and the curve
corrects it); lucky losers miss it by 0.9 (1.8 before, 2.0 on the
21-day cache). The cost of dropping the curve doubled with the codes,
+0.00049 → +0.00105, and at +0.00100 it is now the largest of the eight —
not because it grew, but because the others shrank. Adding it to the seven of
2026-09-11 was worth −0.00058
(`tools/curves.py add`, on the 21-day cache), the same forward selection that
rejected the ranking-shaped candidates below.

**Measured and rejected on 2026-09-11 and 2026-09-12.** Each candidate was
added alone to the shipped set (`tools/curves.py add`), the only test that
means anything for a near-substitute: `rank_gap` −0.00080 alone but
**+0.00077 in company**; `seeded` −0.00032 alone, +0.00035 in company;
`bo5_resid_prior` −0.00037 alone, +0.00007 in company; `log_rank` −0.00036
alone and −0.00012 in company, not worth a live input that goes stale;
`elo_vs_model` (+0.00006), `opp_lefty` (+0.00008) and `bo_diff_prior`
(+0.00005) hurt even alone — `elo_vs_model` is a perfectly antisymmetric
±0.022 curve that still loses out of sample. Two trend-shaped substitutes for
`resid_prior`, measured on 2026-09-12: `resid_365`, the player's residual over
the last 365 days only (K = 20, none until 8 rows), −0.00131 alone but
**+0.00092 in company**; `resid_surface`, the residual on this row's surface
only, −0.00038 alone, +0.00119 in company. Both are still computed into
`data/player_traits.json` (`resid_365`, `surf`) and supplied live, so they can
be re-measured. **Entry type** measured −0.00014 alone and −0.00047 in company
on 2026-09-11 (qualifiers +0.020 on 2,825 rows, lucky losers −0.011, protected
rankings −0.003 (thin), wildcards +0.011) and was held back only because a price could not know
it; on 2026-09-12 the price learned to ask, and it shipped as the eighth
curve. The pool trap that had to be found first: leave-one-out over the six
shipped curves plus all six candidates scored 0.61400 against 0.60912 for the
six alone, and every ranking-shaped candidate looked harmful — near-substitutes
cancelling each other. A candidate pool is not a forward selection (rule 27).

**Structural layers, each measured with the others present**
(`tools/pathsweep.py all`: one walk-forward over the 43,075 scorable matches
at the 7-day refit cadence with the age-dependent prior, every config on
the same 22,427 test matches, paired; six configs in one walk, 445 s
uncontended; re-run on 2026-09-15 under the new prior — the numbers from
2026-09-14, at 7 days with the flat own prior, are in brackets):

| layer | cost of switching it off | paired t |
|---|---|---|
| carrying recent form onto the surface rating | **+0.01789** (+0.01584 with the flat own prior) | −14.00 |
| the surface split itself | +0.00400 (+0.00398) | −4.75 |
| ratings updating *during* a tournament (w=2) | +0.00170 (+0.00194) | −5.60 |
| qualifying + Challenger matches in the fit | +0.00450 (at MIN_PTS 300; measured 2026-09-11 at the 91-day cadence, not re-run) | −4.48 |
| the three-stage serve | **switching it ON costs +0.00505** (+0.00315) | −8.54 |
| in-event update off *and* three-stage serve on | +0.00621 (+0.00446) | −9.92 |

Every layer here but one costs **more** to remove than it did under the flat
own prior: a better rating layer makes the structure around it matter more,
and the carry-over — already the largest single layer — grew the most. The
exception is the in-event update, which gives 0.0002 back (+0.00194 →
+0.00170) and is still worth more than it was at the tour-average prior
(+0.00159).

The in-event weight is interior — w=0.5 −0.00048, w=1 −0.00075, w=2 −0.00130,
w=4 −0.00093 — measured on 2026-09-11 at (0.70, 0.85) and the 91-day cadence,
not re-run. The archive ships 49 qualifying/Challenger files the loader never
opened — 3.2× the main-tour volume, and 28× more service points for the
players the confidence bands call thin. The harness refits every 7 days
(quarterly until 2026-09-12, then 21, 14 and 7 the same day), so between
refits a player who has won three matches at an event would otherwise carry
the rating they arrived with; the in-event update is still worth +0.00170 at
the weekly cadence. The three-stage serve was worth −0.00195 measured *alone*
and costs +0.00505 in company, so it is off: a near-substitute for what the
surface layer already carries, and one that the improving rating layer keeps
making more redundant (+0.00209, +0.00315, +0.00505 across the last three
priors).

**The harness prices through the same code the CLI does.** `weights.derive`
is the one derivation and `price.serve_probs` the one matchup function;
`backtest.py --gate` asserts a harness refit equals `weights.json`. Until
2026-09-11 the two had drifted in six places, and the largest layer above
had never shipped.

**The half-life is age-dependent.** Each player's history decays at their own
rate — `base × multiplier(age)`, shorter at both ends, because an
exponentially weighted mean lags a trend by about `slope × half_life / ln 2`
and young players are rising while old ones are falling. Re-swept on
2026-09-11 inside the shipped path, nine configs paired on 40,181 common test
matches (`tools/agehl.py`): the shipped **(0.50, 0.85)** is **−0.00183 at
t = +6.32** against a single global half-life and **−0.00053 at t = +3.95**
against the previously shipped (0.70, 0.85). The grid is interior in both
directions: 0.40 on the young side is no better than 0.50 and at lower t;
0.70 on the old side is worse than 0.85. At the 91-day cadence the shorter
young memory priced 42,169 matches instead of 43,514 because it qualifies
fewer players — a scoring artefact, not a model cost (the scorable set is
43,075 at the 7-day cadence on the archive refreshed 2026-09-14; it was
42,997 before the refresh and 42,838 at 21 days). Run
`python3 tools/agehl.py compare` to see it. Only the main rating is
age-decayed; the surface-contrast fits keep their long memory.

**Age is no longer the largest effect in the correction layer** — the
age-dependent prior took most of what was left of it into the ratings, and
`entry` now costs more to drop. On the final residual cache (7-day cadence,
age-dependent prior) the shrunk curve in
`fitted_curves.json` runs +0.037 for under-21s (3,736 rows), +0.019 (9,613),
+0.005 (13,864), −0.009 (14,196), −0.016 (8,744), −0.019 at 33 and over
(6,757), monotone across every bucket. Youngest minus oldest is +0.056, from
+0.085 on the 7-day cache with the flat own prior,
+0.075 with the tour-average one, +0.078 on the 21-day
cache, +0.097 on the 91-day cache and +0.123 before the age half-life: each
change that freshened the ratings took part of the age effect out of the
curve and into them; the own prior put part of it back — a declining player
was being shrunk toward a better past — and the age ramp on that prior took
it out again, at the place it belongs. The curve that is left is half the
size and costs +0.00091 to drop, from +0.00227. On the
earlier cache it was monotone across every era, 9.3 SE end to end, and the
gain grew with the age gap in a match, from −0.007 at 0–3 years to −0.023 at
10+. The mechanism is structural: the ratings are a
decayed average over a 270-day half-life, so a rising player's rating lags
and a falling player's over-states. It is *not* thin data wearing an age
mask — that was tested with the exact quantity that drives the shrinkage,
and dropping `age` still cost +0.0035 with it controlled.

Built and rejected, each because it makes the set worse or adds nothing:
`bp_form` (break points saved — clutch is noise), `event_opp_rank`,
`rank_change`, `peak_gap`, `career_matches`, `career_pts`, `home_km`,
`event_matches`. The last four are near-substitutes for something already in.

**"Plays better against good players" is a real trait and a useless
feature.** The opponent adjustment is additive — it assumes a player's edge
is the same shift against everyone — so per-player *sensitivity* to opponent
calibre is genuinely new ground. Split-half reliability says the trait
exists: 0.31 for players with 100+ matches, 0.52 at 250+, against 0.93 for
serve level as a control. But below 40 matches the two halves are
**uncorrelated**, and every version of the feature hurts out of sample. The
two players in a match land on opposite sides of it 47.6% of the time — a
coin flip — so it is not a matchup quantity at all. With reliability ~0.3,
the usable third of the deviation, multiplied by a small opponent-distance
term, lands under the noise floor. Full write-up in `HANDOFF.md`; the code
lives behind `features.EXTRA_FEATURES` so it can be re-measured.

The adjustment must be antisymmetric — a match's two probabilities sum to
one, so what A gains B loses. Applying each side's raw curve independently
scores better on winner-oriented rows and is nonsense: it adds probability
mass without removing any.

It is applied as a shift in **log-odds**, not added to the probability.
Additive cannot be right in the tails: a −0.076 shift on a 3.3% underdog
takes the price negative, and the clamp then quotes a million to one. That is
not hypothetical — one such match cost 13.8 nats and on its own decided a
test fold. A log-odds shift of `4*adj` reproduces the fitted residual where
the curves were fitted and tapers away from there.

**Home advantage.** Home players win only **46%** of their matches, because
they are disproportionately wildcards — but they beat *their own price* by
**+1.9 points** when the curve was first fitted (2026-09-09: 3,505 rows, 9 of
12 years positive); on the shipped 7-day cache the shrunk `home` bucket is
+0.018 on 6,799 rows. Nationality comes from the match log, host nations from
`venues.COUNTRY`, and that map is validated against the data: the mapped
country is over-represented at its own event in **79 of 79** venues with
enough rows, median 4.8x.

```bash
python3 tennis.py price Michelsen Tiafoe hard bo5 --at "US Open"
python3 tennis.py price Alcaraz Ruud clay --at Barcelona   # Alcaraz is home
python3 tennis.py price Alcaraz Djokovic hard bo5          # 23 vs 39
python3 tennis.py price Michelsen Tiafoe hard --at "US Open" --entry-a Q   # A qualified
python3 tennis.py price Michelsen Tiafoe --no-curves       # toggle off
```

`--at` does double duty: it selects the venue's conditions *and* tells the
model which event the players are currently in.

## Workload

```bash
python3 tennis.py workload Alcaraz
```

Matches and minutes already played at the current event (exact, from round
order) plus days since the previous event (approximate — the archive dates a
match by when its *tournament* started). Derived from the match log, so there
is no source to break. **Part of this moves a live price**: matches at the
current event feed the `event_gwp` and `event_sets_lost` curves and the 28-day
match count feeds `matches_28d` — three of the eight correction curves above.
`live_workload` supplies the curve inputs (`resid_prior`, `entry`, `log_rank`
and `bo5_resid_prior` among them), and the workload gate asserts that live
pricing supplies all eight. Only minutes and days since the previous event
are not yet fitted: like style and h2h before them, they get a fitted weight
first, and those two both fitted to zero.

Deliberately ignored: **head-to-head**. Near-zero predictive power once ability
is controlled — the market overweights it, which is the edge.

## Files

| file | role |
|---|---|
| `tennis.py` | front door; no args opens the prompt, else dispatches below |
| `app.py` + `web/` | the browser view; stdlib server, computes nothing itself |
| `news.py` | injury and player news: prompt, schema, weights, applied log |
| `price.py` | price a matchup; holds the interactive prompt |
| `players.py` | name resolution -- typos, initials, surnames; its own gate |
| `tools/ta/` | results refresh from tennisabstract.com, with its own gate |
| `weights.py` | **derives per-player weights** — the fitting entry point |
| `ratings.py` | the two-way opponent-adjusted estimator + its gates |
| `tennis_sim.py` | match simulator (Barnett–Clarke) |
| `check.py` | gate: simulator vs an independent exact recursion |
| `fastmatch.py` | tabulated match probabilities (exact stays the source of truth) |
| `backtest.py` | walk-forward harness; fits form scale and calibration |
| `load.py` | CSV parsing + arithmetic validation |
| `update.py` | refresh data, re-verify provenance, invalidate caches |
| `interactions.py` | opponent-style + H2H effects (both measured, both fit to zero) |
| `venues.py` | 110 venues: lat/lon/elevation/indoor, air density, host nation |
| `tools/pathsweep.py` | **flip one knob of the shipped path, paired, in one walk** |
| `tools/knobsweep.py` | sweep a chosen constant (`refit_days`, `carry_cap`, `surface_hl`, `long_years`, `age_knots`; since 2026-09-14 `prior_mode` and `prior_weight`; since 2026-09-15 `prior_age`): one walk per value in a subprocess, paired on the intersection — and `compare` now scores every value on **both** halves and flags one that wins only on test (rule 32) |
| `tools/curves.py` | the residual curves: `build` (one walk-forward at the shipped cadence — about 8 minutes at 7 days, 413 refits in the chain log of 2026-09-14, against ~2 minutes at 21 days; longer still with `TENNIS_EXTRA=1`, which took ~15 minutes when the walk was ~2; since 2026-09-16 the cache also carries the service points behind each rating at match time and the model's own `form_sd`, which is what the confidence band is fitted on), `add` (forward selection onto the shipped set), `loo`, `reliability` (split-half), `write` |
| `data/player_traits.json` | per-player `resid_prior` trait (plus `resid_365` and per-surface residuals, measured and not adopted) read by live prices; 384 players, written by `tools/curves.py write` |
| `tools/agehl.py` | the age half-life grid, paired against a true global baseline |
| `tools/traitsweep.py` | the `TRAIT_K` / `TRAIT_MIN` grid for `resid_prior`: re-annotates the cached residual rows per cell, refits the eight curves per fold, paired on identical matches |
| `tools/odds/m4.py` | the market check: the walk-forward model against Pinnacle closing, devigged proportionally; writes `data/market_check.json` for the app's model page |
| `tools/odds/disagree.py` | where the model loses to the market, by player and by match. `build` joins odds, walk-forward prices and workload, recording the service points behind each rating **as of that match** (it used to read today's, for a match played two years ago); `bands` re-measures `confidence.MEASURED_DEFICIT`, and the refit chain runs it |
| `confidence.py` | the confidence band, re-derived 2026-09-16: fitted on surprise, checked against the closing line, three levels. `fit` reads the band's real live inputs from the residual cache and writes `confidence_model.json` |
| `tools/qcthin.py` | the Challenger supplement, scored where it is meant to help |
| `tools/twostage.py`, `tools/inevent.py` | single-number-model tools, superseded by `pathsweep` |
| `weather.py` | Open-Meteo historical weather, cached |
| `tools/` | one-off hyperparameter sweeps and paired comparisons |
| `fit.py` | one-off rating fit + top-player report |
| `data_plan.md` | the plan, and every finding so far |

## Rules that keep it honest

1. **Never trust an unconverged fit.** `fit_iterative` returns
   `info["converged"]`. A silent iteration cap returns ratings attenuated ~20%
   that look entirely plausible.
2. **Gate before you judge a feature.** A miscalibrated model punishes
   improvements — the opponent adjustment looked harmful until calibration was
   fixed.
3. **Per-player values are always shrunk.** Every one is a population estimate
   plus a deviation weighted by that player's own sample size.
4. **Re-verify the data on every update.** The source is a third-party mirror;
   `update.py` re-runs the arithmetic and surface-ordering checks each pull.
5. **Refit after any model change.** `tennis.py backtest` rewrites
   `fitted_params.json`.
6. **One derivation, one pricing path.** `weights.derive` and
   `price.serve_probs` are the only places a rating is built or a matchup
   formed; `backtest.py --gate` (the sixth gate) asserts the harness and the
   shipped weights agree. Add a layer there and nowhere else.
7. **A layer measured alone is not measured.** Switch it on inside the
   shipped path with everything else present (`tools/pathsweep.py`) before
   shipping it.

The full list, 1–33, is in `HANDOFF.md`. Added on 2026-09-11 (27, 28),
2026-09-12 (29, 30), 2026-09-14 (31) and 2026-09-15 (32, 33):

27. **A candidate pool is not a forward selection.** Leave-one-out over
    overlapping candidates makes every one look harmful; add each alone to
    the shipped set (`tools/curves.py add`), then leave-one-out the result.
28. **A curve a live price cannot evaluate must not ship.** Entry type
    waited a day on this: it shipped once the price could ask for it and read
    it from the archive's rows at the event, and an unknown entry gets no
    adjustment; the workload gate is what enforces this.
29. **A walk-forward's refit cadence is a model parameter, not a
    convenience.** It decides how stale every rating is between refits, so
    it is swept like any other constant (`tools/knobsweep.py refit_days`):
    91 days cost +0.00413 against 21, and +0.00560 against the shipped 7.
30. **The refit cadence is also a commitment.** The measured number assumes
    the shipped ratings are never staler than the cadence, so ship the
    cadence you will actually refresh at. 7 days ships because weekly is
    what `update.py` and a refit can keep; 3 days is measured (−0.00023 at
    t +5.38), real, and not adopted — one refit chain away
    (`TENNIS_REFIT_DAYS=3`) if the feed ever supports it.
31. **A sweep whose values all score identically is a broken knob, not a
    flat one.** The first `prior_weight` sweep returned four walks at the
    same log loss to five places because the harness read the constant
    separately from `weights.py`; check that an override reaches the code
    that fits before reading a sweep as flat.
32. **A wide sweep is a wide set of chances to be lucky.** `prior_age` was
    fourteen values chosen by held-out log loss. `tools/knobsweep.py
    compare` now scores every value on both halves, and a value that wins
    on test must also win on train, in the same order, or it was read off
    the half it is scored on.
33. **A fitted corrector hides an improvement underneath it.** The
    age-dependent prior is −0.00181 at t +7.17 on the ratings and +0.00016
    at t −0.80 once the eight curves are applied. Measure a rating-layer
    change both ways before claiming it, and say which number the claim is.
