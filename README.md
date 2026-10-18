# Serve & Return

A tennis match pricing model. Give it two players and it returns a fair
probability for each, plus a distribution over total games.

It works at the **point** level rather than the match level. Elo learns one bit
per match — who won. A tennis match contains around 150 service points, and the
archive records how many each player served and how many they won, so modelling
the point multiplies the usable information by two orders of magnitude without
collecting anything new. From two point probabilities, the rest is exact
combinatorics: point to game, game to set, set to match (Barnett–Clarke).

```
$ python3 tennis.py
[bo3] > Sinner vs Alcaraz clay bo5

Jannik Sinner  vs  Carlos Alcaraz
----------------------------------------------------------------
  as of 2026-09-15   Clay   best of 5
  Jannik Sinner     serve 0.7199  return 0.4756  form_sd 0.0192
  Carlos Alcaraz    serve 0.6905  return 0.4848  form_sd 0.0320

  P(Jannik Sinner)  0.6104    fair 1.638
  P(Carlos Alcaraz)  0.3896    fair 2.567
```

## Does it work?

Walk-forward, refitting on prior matches only and never training on the week it
prices:

| | log loss |
|---|---|
| coin flip | 0.69315 |
| tuned Elo | 0.66280 |
| **this model** | **0.60885** |

Against the market, on matches joined to Pinnacle's closing line, it loses. The
gap is **ordering, not calibration** — an optimal rescaling of the model's
log-odds closes about 2% of it, so no amount of recalibration helps. Where the
model agrees with the market it *is* the market; essentially all of the loss is
concentrated in confident disagreement.

That is the honest headline. It beats a tuned Elo by a wide margin and it does
not beat a bookmaker.

The repository is as much a record of **what did not work** as what did.
Head-to-head, opponent style, height, ranking, clutch (break points saved),
travel, elevation change, surface switch, and "does he play better against good
players" were all built, measured out of sample, and rejected.
[docs/measurements.md](docs/measurements.md) has the numbers.

## Setup

Python 3.10+ and one dependency.

```bash
pip install -r requirements.txt
```

### The data

**No tennis data is in this repository and none can be** — see [NOTICE](NOTICE).

The model reads Jeff Sackmann's ATP match files: one `atp_matches_<year>.csv`
per season, carrying the result plus serve counts (`w_svpt`, `w_1stIn`,
`w_1stWon`, `w_2ndWon`, and the loser's equivalents). Put them here:

```
data/sackmann/atp/atp_matches_1968.csv
data/sackmann/atp/atp_matches_1969.csv
...
```

**Sackmann withdrew his repositories in 2026** and the canonical source is gone.
This project does not host that data, mirror it, or point you at a mirror — if
you have a legitimate copy, the layout above is all you need. Everything the
model does is reproducible from it; nothing here depends on a particular
distribution of it.

Then:

```bash
python3 update.py --check     # verify the data loaded
python3 tennis.py fit         # derive player weights (a few minutes)
python3 tennis.py gates       # prove nothing is broken
```

Run commands from the repository root. Without data, every command says so and
exits — it will not quietly produce a price from nothing.

## Using it

```bash
python3 tennis.py                      # interactive prompt
python3 tennis.py app                  # browse it: roster, player pages, prices
python3 tennis.py price Sinner Alcaraz clay bo5 --at "Roland Garros"
python3 tennis.py sim Sinner Alcaraz clay bo5    # totals and set scores
python3 tennis.py gates                # five correctness gates
```

Names are forgiving — a surname, initials, `Alcaraz, Carlos`, or a typo all
resolve, and an unmatched name suggests the nearest ones.

`tennis.py app` serves a local page on `127.0.0.1` only.

## How it is built

```
archive CSVs ──> load.py ──> ratings.py ──> weights.py ──> price.py
                  parse +     opponent-      surface +      P(win),
                  validate    adjusted       volatility     total games
                              serve/return
```

The core problem the ratings solve is circular: a player's serve percentage
depends on the returners they faced, and those returners' quality depends on the
servers *they* faced. One correction pass is worse than none (it recovers the
true rating at slope 0.61 against a known answer); alternating both sides to
convergence recovers it at 1.03.

On top sit a small number of residual corrections, each a bucketed *curve*
rather than a coefficient — several of these effects are humps, and a straight
line fitted to a hump reports zero. They are applied antisymmetrically, in
log-odds.

## Reading further

- **[docs/measurements.md](docs/measurements.md)** — every measurement, every
  rejected idea, and why.
- **[docs/handoff.md](docs/handoff.md)** — working notes: current state, the
  rules that keep the measurements honest, and the traps already fallen into.
  Written to a future self, and it reads like it.

## Licence

Code is MIT ([LICENSE](LICENSE)). Data is not distributed here and belongs to
its sources — read [NOTICE](NOTICE) before using this for anything beyond
personal study. The match data's own licence is non-commercial.
