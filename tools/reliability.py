"""Is this a stable player trait, or is it noise?

    python3 tools/reliability.py

Rule 13, made runnable. Before shrinking a per-player quantity by anything,
split that player's matches into two random halves, compute the quantity on
each half, and correlate the halves across players. Spearman-Brown corrects
the half-sample correlation up to the reliability of the full sample.

  reliability ~ 1.0   a real trait; a per-player value is nearly all signal
  reliability ~ 0.3   a third of the measured spread is real
  reliability ~ 0.0   the two halves disagree; there is nothing to shrink
                      TOWARD, and any per-player value is noise with a
                      mechanism attached

This exists because the opponent-calibre feature was built, shrunk by a
chosen constant, and measured to nothing -- and only afterwards did this
check reveal that below 40 matches the halves are uncorrelated. Ten lines,
run in the wrong order.

Every quantity below is scored against two anchors: serve level, which is
indisputably a trait, and opponent style, which the backtest independently
fits to zero.
"""

import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import weights as W                                            # noqa: E402
from ratings import TOUR_AVG                                   # noqa: E402
from interactions import residuals                             # noqa: E402
from load import load                                          # noqa: E402
from fit import to_day                                         # noqa: E402

THRESHOLDS = (40, 100, 250)


def spearman_brown(A, B):
    """(n, half-sample r, full-sample reliability)."""
    n = len(A)
    if n < 15:
        return n, 0.0, 0.0
    ma, mb = sum(A) / n, sum(B) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(A, B))
    den = math.sqrt(sum((x - ma) ** 2 for x in A)
                    * sum((y - mb) ** 2 for y in B))
    r = num / den if den else 0.0
    return n, r, (2 * r / (1 + r) if r > -1 else 0.0)


def split_half(groups, stat, minn, seed=0):
    rng = random.Random(seed)
    A, B = [], []
    for _p, v in groups.items():
        if len(v) < minn:
            continue
        idx = list(range(len(v)))
        rng.shuffle(idx)
        h = len(idx) // 2
        s1, s2 = stat([v[i] for i in idx[:h]]), stat([v[i] for i in idx[h:]])
        if s1 is None or s2 is None:
            continue
        A.append(s1)
        B.append(s2)
    return spearman_brown(A, B)


def wmean(v):
    tw = sum(z for _x, _y, z in v)
    return (sum(y * z for _x, y, z in v) / tw) if tw > 0 else None


def wslope(v):
    tw = sum(z for _x, _y, z in v)
    if tw <= 0:
        return None
    mx = sum(x * z for x, _y, z in v) / tw
    my = sum(y * z for _x, y, z in v) / tw
    den = sum(z * (x - mx) ** 2 for x, _y, z in v)
    return (sum(z * (x - mx) * (y - my) for x, y, z in v) / den
            if den > 1e-12 else None)


def main():
    w = W.load_weights()
    if not w:
        sys.exit("no weights.json -- run: python3 tennis.py fit")
    serve, ret, rbar = w["overall"]["serve"], w["overall"]["ret"], 1 - TOUR_AVG

    raw, _ = load(2015, 2026)
    recs = [(to_day(m.tourney_date), m.w_id, m.l_id, m.w_svpt, m.w_won,
             m.l_svpt, m.l_won) for m in raw if m.has_stats]
    recs.sort(key=lambda r: r[0])
    rank = {}
    for m in raw:
        if m.w_rank:
            rank.setdefault(m.w_id, []).append((m.tourney_date, m.w_rank))
        if m.l_rank:
            rank.setdefault(m.l_id, []).append((m.tourney_date, m.l_rank))

    res = residuals(recs, serve, ret, w["asof"], half_life=1095)
    lvl_of = {p: (serve[p] - TOUR_AVG) + (ret.get(p, rbar) - rbar)
              for p in serve}

    groups = {"level": defaultdict(list), "style": defaultdict(list),
              "abs": defaultdict(list)}
    for p, opp, wt, n, r, st in res:
        groups["level"][p].append((lvl_of.get(opp, 0.0), r, wt * n))
        groups["style"][p].append((st, r, wt * n))
        groups["abs"][p].append((0.0, r + (serve[p] - TOUR_AVG), wt * n))

    print(f"  {len(res):,} player-match residuals\n")
    print(f"  {'quantity':<46} {'min m':>6} {'players':>8} "
          f"{'half r':>8} {'full':>7}")
    rows = (("serve level  (anchor: a real trait)", "abs", wmean),
            ("slope on opponent LEVEL", "level", wslope),
            ("slope on opponent STYLE  (anchor: fits to 0)", "style", wslope))
    for lbl, key, stat in rows:
        for mn in THRESHOLDS:
            n, r, f = split_half(groups[key], stat, mn)
            print(f"  {lbl:<46} {mn:>6} {n:>8} {r:>8.3f} {f:>7.3f}")
    print("\n  A quantity that does not clearly beat the STYLE line is not a")
    print("  trait this data can measure, whatever mechanism it has.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
