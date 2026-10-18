"""Should a rating move DURING a tournament?

    python3 tools/inevent.py            sweep the update weight
    python3 tools/inevent.py 0.0 1.0    just these weights

Ratings are refit every 91 days, so inside a tournament nobody's rating
moves. A player who has already won three matches here has shown something
the price does not know -- and `tools/round_effect.py` measured it:
underdogs with wins banked beat their price by +0.0195 at 3.7 SE, while
favourites with wins banked miss theirs.

The curve layer captures a piece of that through `event_gwp` and
`event_sets_lost`, which are match-margin summaries put through a bucketed
residual correction. This asks the structural version instead: update the
RATING from the points actually won at this event, before pricing.

    residual = (points won here) - (points the model expected here)
    serve   += w * residual / (den + points here)

`w` is the one free parameter. w = 0 is the shipped model exactly. The
shrinkage denominator is the rating's own effective sample size, so a player
with a long record barely moves and a thin one moves a lot, which is the
correct behaviour and needs no separate tuning.

Crucially the expectation is OPPONENT-ADJUSTED: a player who won 65% of
serve points against a weak returner has not shown what a player who did it
against a good one has. Comparing raw rates to a tour average would mostly
measure who they drew.

!! SUPERSEDED, and the first published numbers were WRONG.  This sorted
matches by (date, event) and banked them in FILE order, and the archive
lists some seasons alphabetically by round -- F, QF, R128 ... -- so a
first-round price had the final already folded in.  The sort now uses
ROUND_ORDER.  It also prices the single-number model with no surface, form
or stages.  The measurement that decides event_update_w is
`python3 tools/pathsweep.py event_w 0 0.5 1 2 4`, which sweeps the weight
inside the full shipped pricing path, paired.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from fastmatch import win_prob                                    # noqa: E402
from features import ROUND_ORDER                                  # noqa: E402
from fit import to_day                                            # noqa: E402
from load import load                                             # noqa: E402
from ratings import fit_iterative, TOUR_AVG                       # noqa: E402

HALF_LIFE, PRIOR, MIN_PTS = 270, 150, 1500


def expected(bk, a, b):
    """The model's serve rate for A against B, before any in-event update."""
    avg = bk["avg"]
    sa = bk["serve"].get(a, avg)
    rb = bk["ret"].get(b, 1 - avg)
    return min(max(avg + (sa - avg) - (rb - (1 - avg)), 0.05), 0.95)


def adjusted(bk, pid, run, w):
    """(serve, ret) for this player with the event so far folded in."""
    avg = bk["avg"]
    sa = bk["serve"].get(pid, avg)
    ra = bk["ret"].get(pid, 1 - avg)
    if not w or pid not in run:
        return sa, ra
    den = bk["den"].get(pid, 0.0)
    s_pts, s_res, r_pts, r_res = run[pid]
    if s_pts:
        sa += w * s_res / (den + s_pts)
    if r_pts:
        ra += w * r_res / (den + r_pts)
    return min(max(sa, 0.30), 0.92), min(max(ra, 0.08), 0.70)


def price(bk, a, b, bo, run, w):
    sa, ra = adjusted(bk, a, run, w)
    sb, rb = adjusted(bk, b, run, w)
    avg = bk["avg"]
    pa = min(max(avg + (sa - avg) - (rb - (1 - avg)), 0.35), 0.90)
    pb = min(max(avg + (sb - avg) - (ra - (1 - avg)), 0.35), 0.90)
    return 0.5 * (win_prob(pa, pb, bo) + 1 - win_prob(pb, pa, bo))


def walk(weights, y0=2005, y1=2026, refit_days=91, train_years=5):
    ms, _ = load(y0, y1)
    ms = [m for m in ms if m.has_stats]
    # ROUND order inside an event, not file order -- see the docstring
    ms.sort(key=lambda m: (m.tourney_date, m.tid, ROUND_ORDER.get(m.rnd, 9)))
    days = [to_day(m.tourney_date) for m in ms]
    start = days[0] + 365 * 3
    bk, next_refit = None, start
    runs = {}                       # tid -> {pid: [s_pts, s_res, r_pts, r_res]}
    loss = {w: [] for w in weights}
    n = 0

    for m, t in zip(ms, days):
        if t >= next_refit and t >= start:
            lo = t - 365 * train_years
            train = [(to_day(x.tourney_date), x.w_id, x.l_id, x.w_svpt,
                      x.w_won, x.l_svpt, x.l_won)
                     for x in ms if lo <= to_day(x.tourney_date) < t]
            if train:
                num = sum(r[4] + r[6] for r in train)
                den = sum(r[3] + r[5] for r in train)
                avg = num / den
                s, r_, d, _i = fit_iterative(train, asof=t - 1,
                                             half_life=HALF_LIFE,
                                             prior_weight=PRIOR,
                                             tour_avg=avg, max_iter=400)
                bk = {"serve": s, "ret": r_, "den": d, "avg": avg}
            next_refit = t + refit_days
        if bk is None or t < start:
            continue

        run = runs.setdefault(m.tid, {})
        a, b = m.w_id, m.l_id
        if min(bk["den"].get(a, 0), bk["den"].get(b, 0)) >= MIN_PTS:
            bo = m.best_of or 3
            for w in weights:
                q = price(bk, a, b, bo, run, w)
                loss[w].append(-math.log(max(min(q, 1 - 1e-12), 1e-12)))
            n += 1

        # bank this match into the event run, AFTER pricing it
        ea, eb = expected(bk, a, b), expected(bk, b, a)
        for pid, svpt, won, exp_s, opp_svpt, opp_won, exp_o in (
                (a, m.w_svpt, m.w_won, ea, m.l_svpt, m.l_won, eb),
                (b, m.l_svpt, m.l_won, eb, m.w_svpt, m.w_won, ea)):
            e = run.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
            e[0] += svpt
            e[1] += won - exp_s * svpt
            e[2] += opp_svpt
            # returning: points won receiving = opponent's serve points lost
            e[3] += (opp_svpt - opp_won) - (1 - exp_o) * opp_svpt

    base = sum(loss[weights[0]]) / n
    print(f"\n  {n:,} matches priced at every weight, identical match set\n")
    print(f"  {'w':>6} {'log loss':>10} {'vs w=0':>10} {'paired t':>9}")
    for w in weights:
        v = loss[w]
        mm = sum(v) / n
        d = [x - y for x, y in zip(loss[weights[0]], v)]
        mu = sum(d) / n
        sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else 0
        tt = mu / (sd / math.sqrt(n)) if sd else 0.0
        tag = "  <- shipped model" if w == 0 else ""
        print(f"  {w:>6.2f} {mm:>10.5f} {mm - base:>+10.5f} {tt:>+9.2f}{tag}")


def main():
    args = [float(a) for a in sys.argv[1:] if not a.startswith("-")]
    weights = tuple(sorted(set([0.0] + (args or [0.5, 1.0, 2.0, 4.0]))))
    print(f"  sweeping in-event update weights {weights}")
    walk(weights)
    return 0


if __name__ == "__main__":
    sys.exit(main())
