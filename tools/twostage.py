"""Is a serve one number or three?

    python3 tools/twostage.py

The model rates a server with a single quantity: the share of service points
they win. The archive also records how the point got there --

    first serve in     svpt -> 1stIn
    won on the first   1stIn -> 1stWon
    won on the second  (svpt - 1stIn) -> 2ndWon

and two players with an identical overall rate can have very different
shapes. A big server lands 53% of first serves and wins 87% of them; a
metronome lands 72% and wins 67%.

WHY THIS CANNOT HELP BY ITSELF. Barnett-Clarke consumes one probability per
server. Decompose the serve into stages, recombine them, and if the expected
rate is unchanged the match probability is identical -- exactly as a round
curve cancels to zero. The decomposition can only earn its place if the
stages are OPPONENT-ADJUSTED SEPARATELY: if a returner is differentially
good against second serves, the additive single-number adjustment cannot
express it and a three-stage one can.

So this fits three ratings with the same estimator, recombines them, and
compares the recombined price against the single-number price ON THE SAME
MATCHES.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fit import to_day                                            # noqa: E402
from load import load                                             # noqa: E402
from ratings import fit_iterative                                 # noqa: E402

HALF_LIFE, PRIOR = 270, 150
MIN_PTS = 1500


def stages(matches, asof):
    """Three record sets: serve landed, point won on first, won on second."""
    land, first, second = [], [], []
    for m in matches:
        if not m.has_stats or to_day(m.tourney_date) > asof:
            continue
        t = to_day(m.tourney_date)
        w2d, l2d = m.w_svpt - m.w_1in, m.l_svpt - m.l_1in
        if min(m.w_1in, m.l_1in, w2d, l2d) <= 0:
            continue
        land.append((t, m.w_id, m.l_id, m.w_svpt, m.w_1in,
                     m.l_svpt, m.l_1in))
        first.append((t, m.w_id, m.l_id, m.w_1in, m.w_1won,
                      m.l_1in, m.l_1won))
        second.append((t, m.w_id, m.l_id, w2d, m.w_2won, l2d, m.l_2won))
    return land, first, second


def base_records(matches, asof):
    out = []
    for m in matches:
        if not m.has_stats or to_day(m.tourney_date) > asof:
            continue
        out.append((to_day(m.tourney_date), m.w_id, m.l_id, m.w_svpt,
                    m.w_won, m.l_svpt, m.l_won))
    return out


def avg_of(recs):
    won = sum(r[4] + r[6] - (r[6] - r[6]) for r in recs)   # placeholder
    return won


def fit_all(matches, asof, verbose=True):
    land, first, second = stages(matches, asof)
    out = {}
    for name, recs in (("land", land), ("first", first), ("second", second)):
        num = sum(r[4] + r[6] for r in recs)
        den = sum(r[3] + r[5] for r in recs)
        avg = num / den
        s, r_, d, info = fit_iterative(recs, asof=asof, half_life=HALF_LIFE,
                                       prior_weight=PRIOR, tour_avg=avg,
                                       max_iter=400)
        out[name] = {"serve": s, "ret": r_, "den": d, "avg": avg,
                     "conv": info["converged"]}
        if verbose:
            print(f"    {name:<7} tour rate {avg:.4f}  "
                  f"{len(s):,} players  converged={info['converged']}")
    base = base_records(matches, asof)
    num = sum(r[4] + r[6] for r in base)
    den = sum(r[3] + r[5] for r in base)
    avg = num / den
    s, r_, d, info = fit_iterative(base, asof=asof, half_life=HALF_LIFE,
                                   prior_weight=PRIOR, tour_avg=avg,
                                   max_iter=400)
    out["single"] = {"serve": s, "ret": r_, "den": d, "avg": avg,
                     "conv": info["converged"]}
    if verbose:
        print(f"    {'single':<7} tour rate {avg:.4f}  "
              f"{len(s):,} players  converged={info['converged']}")
    return out


def stage_p(bk, name, a, b):
    """Opponent-adjusted rate for one stage, same additive form as price.py."""
    m = bk[name]
    avg = m["avg"]
    sa = m["serve"].get(a, avg)
    rb = m["ret"].get(b, 1 - avg)
    return min(max(avg + (sa - avg) - (rb - (1 - avg)), 0.02), 0.99)


def p_two(bk, a, b):
    f = stage_p(bk, "land", a, b)
    w1 = stage_p(bk, "first", a, b)
    w2 = stage_p(bk, "second", a, b)
    return f * w1 + (1 - f) * w2, (f, w1, w2)


def p_one(bk, a, b):
    return stage_p(bk, "single", a, b)


def walk(y0=2005, y1=2026, refit_days=91, train_years=5):
    """Rolling refits, both forms fitted from the same prior matches and
    scored on the same ones, paired per match.

    A single train/test split showed three stages ahead by 0.0043, but a
    single split is one draw. This is the harness that decides: the MIN_PTS
    filter uses the SINGLE model's point counts for both forms, so the two
    are scored on an identical match set (rule 1).
    """
    from fastmatch import win_prob
    ms, _ = load(y0, y1)
    ms = [m for m in ms if m.has_stats]
    ms.sort(key=lambda m: m.tourney_date)
    days = [to_day(m.tourney_date) for m in ms]
    start = days[0] + 365 * 3
    bk, next_refit = None, start
    d1, d2, n = [], [], 0

    for m, t in zip(ms, days):
        if t < start:
            continue
        if t >= next_refit:
            lo = t - 365 * train_years
            train = [x for x in ms if lo <= to_day(x.tourney_date) < t]
            if train:
                bk = fit_all(train, t - 1, verbose=False)
            next_refit = t + refit_days
        if bk is None:
            continue
        a, b = m.w_id, m.l_id
        den = bk["single"]["den"]
        if min(den.get(a, 0), den.get(b, 0)) < MIN_PTS:
            continue
        bo = m.best_of or 3
        pa1, pb1 = p_one(bk, a, b), p_one(bk, b, a)
        pa2, pb2 = p_two(bk, a, b)[0], p_two(bk, b, a)[0]
        for pa, pb, sink in ((pa1, pb1, d1), (pa2, pb2, d2)):
            q = 0.5 * (win_prob(pa, pb, bo) + 1 - win_prob(pb, pa, bo))
            sink.append(-math.log(max(min(q, 1 - 1e-12), 1e-12)))
        n += 1

    m1, m2 = sum(d1) / n, sum(d2) / n
    diff = [x - y for x, y in zip(d1, d2)]          # >0 means three stages win
    mu = sum(diff) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in diff) / (n - 1))
    t = mu / (sd / math.sqrt(n))
    print(f"\n  WALK-FORWARD, {n:,} matches scored on both forms")
    print(f"  {'single number':>22} {m1:>12.5f}")
    print(f"  {'three stages':>22} {m2:>12.5f}")
    print(f"  {'difference':>22} {m2 - m1:>+12.5f}   paired t {t:+.2f}")
    return m2 - m1, t


def main():
    if "--walk" in sys.argv:
        walk()
        return 0
    ms, _ = load(2005, 2026)
    ms = [m for m in ms if m.has_stats]
    days = sorted({to_day(m.tourney_date) for m in ms})
    cut = days[int(len(days) * 0.70)]
    train = [m for m in ms if to_day(m.tourney_date) <= cut]
    test = [m for m in ms if to_day(m.tourney_date) > cut]
    print(f"  fit on {len(train):,} matches to day {cut}, "
          f"score {len(test):,} after it\n")
    bk = fit_all(train, cut)

    den = bk["single"]["den"]
    rows = []
    for m in test:
        a, b = m.w_id, m.l_id
        if min(den.get(a, 0), den.get(b, 0)) < MIN_PTS:
            continue
        if m.w_svpt <= 0 or m.l_svpt <= 0:
            continue
        rows.append(m)
    print(f"\n  {len(rows):,} test matches with both players well measured\n")

    # score the SERVE RATE itself, which is what the two forms disagree about
    e1 = e2 = n = 0.0
    for m in rows:
        for a, b, svpt, won in ((m.w_id, m.l_id, m.w_svpt, m.w_won),
                                (m.l_id, m.w_id, m.l_svpt, m.l_won)):
            actual = won / svpt
            e1 += svpt * (p_one(bk, a, b) - actual) ** 2
            e2 += svpt * (p_two(bk, a, b)[0] - actual) ** 2
            n += svpt
    print(f"  {'form':>22} {'weighted MSE of the serve rate':>32}")
    print(f"  {'single number':>22} {e1/n:>32.6f}")
    print(f"  {'three stages':>22} {e2/n:>32.6f}")
    d = (e2 - e1) / n
    print(f"  {'difference':>22} {d:>+32.6f}  "
          f"{'three stages WIN' if d < 0 else 'no gain'}")

    # The measurement that decides. A better serve rate is only worth
    # something if it survives into the match probability, and the match
    # only cares about the DIFFERENCE between the two servers.
    from fastmatch import win_prob
    l1 = l2 = 0.0
    for m in rows:
        bo = m.best_of or 3
        pa1, pb1 = p_one(bk, m.w_id, m.l_id), p_one(bk, m.l_id, m.w_id)
        pa2 = p_two(bk, m.w_id, m.l_id)[0]
        pb2 = p_two(bk, m.l_id, m.w_id)[0]
        # both serve orders, because every row is oriented to the winner
        for pa, pb, acc in ((pa1, pb1, "one"), (pa2, pb2, "two")):
            q = 0.5 * (win_prob(pa, pb, bo) + 1 - win_prob(pb, pa, bo))
            v = -math.log(max(min(q, 1 - 1e-12), 1e-12))
            if acc == "one":
                l1 += v
            else:
                l2 += v
    k = len(rows)
    print(f"\n  {'form':>22} {'match log loss':>32}")
    print(f"  {'single number':>22} {l1/k:>32.5f}")
    print(f"  {'three stages':>22} {l2/k:>32.5f}")
    dd = (l2 - l1) / k
    print(f"  {'difference':>22} {dd:>+32.5f}  "
          f"{'three stages WIN' if dd < 0 else 'NO GAIN on the price'}")
    print("\n  Note what cannot change: under independent points a three-stage")
    print("  serve with the same expected rate gives the SAME marginal point")
    print("  probability, so the games distribution is identical too.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
