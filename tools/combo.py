"""Do the two structural fixes overlap, or add?

    python3 tools/combo.py

Two changes measured separately, each large:

    three-stage serve   -0.00195   t +12.32
    in-event update     -0.00267   t  +6.82

Both sharpen the same quantity -- the serve rate the recursion consumes --
so they could easily be the same win counted twice. Every near-substitute
this project has tested has looked positive alone and cancelled in company.
This runs the 2x2 on one identical match set, paired.

!! SUPERSEDED, and the first published in-event numbers were WRONG: matches
were banked in FILE order, and some seasons of the archive list rounds
alphabetically (F first), so early-round prices had the final folded in.
The sort now uses ROUND_ORDER.  The 2x2 that decides is
`python3 tools/pathsweep.py combo`, on the full shipped pricing path.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fastmatch import win_prob                                    # noqa: E402
from features import ROUND_ORDER                                  # noqa: E402
from fit import to_day                                            # noqa: E402
from load import load                                             # noqa: E402
from ratings import fit_iterative                                 # noqa: E402
from twostage import fit_all, stage_p                             # noqa: E402

HALF_LIFE, PRIOR, MIN_PTS = 270, 150, 1500
W = 2.0                                   # in-event weight, from tools/inevent


def rate(bk, name, a, b, run, w):
    """One stage's opponent-adjusted rate, with the event so far folded in."""
    m = bk[name]
    avg = m["avg"]
    sa = m["serve"].get(a, avg)
    rb = m["ret"].get(b, 1 - avg)
    if w and run is not None:
        ea, eb = run.get((name, a)), run.get((name, b))
        if ea and ea[0]:
            sa += w * ea[1] / (m["den"].get(a, 0.0) + ea[0])
        if eb and eb[2]:
            rb += w * eb[3] / (m["den"].get(b, 0.0) + eb[2])
    return min(max(avg + (sa - avg) - (rb - (1 - avg)), 0.02), 0.99)


def serve_p(bk, a, b, run, w, three):
    if not three:
        return min(max(rate(bk, "single", a, b, run, w), 0.35), 0.90)
    f = rate(bk, "land", a, b, run, w)
    w1 = rate(bk, "first", a, b, run, w)
    w2 = rate(bk, "second", a, b, run, w)
    return min(max(f * w1 + (1 - f) * w2, 0.35), 0.90)


STAGE_COUNTS = {
    "single": lambda m, win: ((m.w_svpt, m.w_won, m.l_svpt, m.l_won) if win
                              else (m.l_svpt, m.l_won, m.w_svpt, m.w_won)),
    "land":   lambda m, win: ((m.w_svpt, m.w_1in, m.l_svpt, m.l_1in) if win
                              else (m.l_svpt, m.l_1in, m.w_svpt, m.w_1in)),
    "first":  lambda m, win: ((m.w_1in, m.w_1won, m.l_1in, m.l_1won) if win
                              else (m.l_1in, m.l_1won, m.w_1in, m.w_1won)),
    "second": lambda m, win: ((m.w_svpt - m.w_1in, m.w_2won,
                               m.l_svpt - m.l_1in, m.l_2won) if win
                              else (m.l_svpt - m.l_1in, m.l_2won,
                                    m.w_svpt - m.w_1in, m.w_2won)),
}


def walk(y0=2005, y1=2026, refit_days=91, train_years=5):
    ms, _ = load(y0, y1)
    ms = [m for m in ms if m.has_stats]
    ms.sort(key=lambda m: (m.tourney_date, m.tid, ROUND_ORDER.get(m.rnd, 9)))
    days = [to_day(m.tourney_date) for m in ms]
    start = days[0] + 365 * 3
    bk, next_refit = None, start
    runs = {}
    configs = [("single, no update", False, 0.0),
               ("single, in-event", False, W),
               ("three stages, no update", True, 0.0),
               ("three stages + in-event", True, W)]
    loss = {c[0]: [] for c in configs}
    n = 0

    for m, t in zip(ms, days):
        if t >= next_refit and t >= start:
            lo = t - 365 * train_years
            train = [x for x in ms if lo <= to_day(x.tourney_date) < t]
            if train:
                bk = fit_all(train, t - 1, verbose=False)
            next_refit = t + refit_days
        if bk is None or t < start:
            continue

        run = runs.setdefault(m.tid, {})
        a, b = m.w_id, m.l_id
        if min(bk["single"]["den"].get(a, 0),
               bk["single"]["den"].get(b, 0)) >= MIN_PTS:
            bo = m.best_of or 3
            for lbl, three, w in configs:
                pa = serve_p(bk, a, b, run, w, three)
                pb = serve_p(bk, b, a, run, w, three)
                q = 0.5 * (win_prob(pa, pb, bo) + 1 - win_prob(pb, pa, bo))
                loss[lbl].append(-math.log(max(min(q, 1 - 1e-12), 1e-12)))
            n += 1

        # bank this match into every stage's event run, AFTER pricing
        for name in ("single", "land", "first", "second"):
            mm = bk[name]
            avg = mm["avg"]
            for pid, opp, win in ((a, b, True), (b, a, False)):
                sv, wn, osv, own = STAGE_COUNTS[name](m, win)
                if sv <= 0 or osv <= 0:
                    continue
                exp_s = min(max(avg + (mm["serve"].get(pid, avg) - avg)
                                - (mm["ret"].get(opp, 1 - avg) - (1 - avg)),
                                0.02), 0.99)
                exp_o = min(max(avg + (mm["serve"].get(opp, avg) - avg)
                                - (mm["ret"].get(pid, 1 - avg) - (1 - avg)),
                                0.02), 0.99)
                e = run.setdefault((name, pid), [0.0, 0.0, 0.0, 0.0])
                e[0] += sv
                e[1] += wn - exp_s * sv
                e[2] += osv
                e[3] += (osv - own) - (1 - exp_o) * osv

    base = loss[configs[0][0]]
    b0 = sum(base) / n
    print(f"\n  {n:,} matches, identical set, every config paired\n")
    print(f"  {'config':>26} {'log loss':>10} {'vs shipped':>11} {'t':>8}")
    for lbl, _three, _w in configs:
        v = loss[lbl]
        mm = sum(v) / n
        d = [x - y for x, y in zip(base, v)]
        mu = sum(d) / n
        sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1))
        tt = mu / (sd / math.sqrt(n)) if sd else 0.0
        print(f"  {lbl:>26} {mm:>10.5f} {mm - b0:>+11.5f} {tt:>+8.2f}")

    # what does each add ON TOP of the other?
    a_only = sum(loss["three stages, no update"]) / n
    b_only = sum(loss["single, in-event"]) / n
    both = sum(loss["three stages + in-event"]) / n
    print(f"\n  three stages adds, on top of in-event : {both - b_only:+.5f}")
    print(f"  in-event adds, on top of three stages : {both - a_only:+.5f}")
    print(f"  sum of the two alone                  : "
          f"{(a_only - b0) + (b_only - b0):+.5f}")
    print(f"  actual combined                       : {both - b0:+.5f}")


if __name__ == "__main__":
    walk()
