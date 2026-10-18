"""Sweep TRAIT_K / TRAIT_MIN -- the shrinkage and the floor of resid_prior --
on the residual cache, paired.

    python3 tools/traitsweep.py                    # the grid
    python3 tools/traitsweep.py 40,15 80,15 20,10  # explicit K,MIN pairs

No walk.  Each (K, MIN) re-annotates the cached rows in memory
(tools/curves.py annotate_traits reads the two module constants at call
time), refits the eight curves on each fold's TRAIN half and scores the
shipped antisymmetric log-odds application at k = 1 on the fold's test
half -- exactly what `curves.py antisym --logit` does -- but keeps every
match's loss, so each value is compared with the shipped (40, 15) by a
paired per-match t on identical matches (rule 1).  Under a second a
value: the whole grid takes about twenty seconds.
"""

import itertools
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import backtest as B          # noqa: E402
import curves as C            # noqa: E402

GRID_K = (10, 20, 40, 80, 160, 320)
GRID_MIN = (5, 10, 15, 25, 40)


def per_match(rows, names, k=1.0, folds=4):
    """(key -> loss) for every test match, curves fitted per fold on the
    train half, the antisymmetric log-odds application at magnitude k."""
    pairs = C.match_pairs(rows)
    n = len(pairs)
    edges = [int(n * i / (folds + 1)) for i in range(folds + 2)]
    scale = 2.0 * k                      # antisym's grid: x2 is k = 1
    out = {}
    for i in range(1, folds + 1):
        train, test = pairs[:edges[i]], pairs[edges[i]:edges[i + 1]]
        if not test:
            continue
        curves = {nm: C.fit_curve([r for pr in train for r in pr], nm)[0]
                  for nm in names}
        for w, l in test:
            adj = 0.0
            for nm in names:
                bw = C.bucket_of(nm, C.value_of(nm, w))
                bl = C.bucket_of(nm, C.value_of(nm, l))
                adj += curves[nm].get(bw, 0.0) - curves[nm].get(bl, 0.0)
            q = C.apply_logit(w["p"], scale * adj / 2.0)
            out[(w["day"], w["pid"], l["pid"])] = -math.log(max(q, 1e-12))
    return out


def main():
    rows = C.load_cache()
    names = list(C.ADOPTED)
    shipped = (C.TRAIT_K, C.TRAIT_MIN)
    if len(sys.argv) > 1:
        grid = [tuple(float(x) if i == 0 else int(x)
                      for i, x in enumerate(a.split(","))) for a in sys.argv[1:]]
    else:
        grid = [(float(k), int(m)) for k, m in itertools.product(GRID_K, GRID_MIN)]
    grid = list(dict.fromkeys([shipped] + grid))       # shipped first, once
    print(f"resid_prior shrinkage sweep on {len(rows):,} cached player-rows, "
          f"eight curves at k = 1, 4 folds; shipped K={shipped[0]:g} MIN={shipped[1]}\n")
    res, reads = {}, {}
    for K, M in grid:
        C.TRAIT_K, C.TRAIT_MIN = float(K), int(M)
        C.annotate_traits(rows)
        reads[(K, M)] = sum(1 for r in rows if r["f"].get("resid_prior") is not None)
        res[(K, M)] = per_match(rows, names)
        print(f"  K={K:g} MIN={M} done", file=sys.stderr, flush=True)
    C.TRAIT_K, C.TRAIT_MIN = shipped                    # leave the module as found
    base = res[shipped]
    keys = sorted(base)
    ps_base = [math.exp(-base[key]) for key in keys]
    print(f"  {'K':>6} {'MIN':>4} {'rows w/ read':>13} {'test ll':>9} "
          f"{'vs shipped':>11} {'paired t':>9}")
    for K, M in grid:
        ps = [math.exp(-res[(K, M)][key]) for key in keys]
        mu, t = B.paired_t(ps_base, ps)
        tag = "  <- shipped" if (K, M) == shipped else ""
        print(f"  {K:>6g} {M:>4} {reads[(K, M)]:>13,} {B.logloss(ps):>9.5f} "
              f"{-mu:>+11.5f} {t:>+9.2f}{tag}")
    print(f"\n  {len(keys):,} matches, identical for every value; vs shipped: "
          "change in log loss, negative is better, t > 0 means better")
    return 0


if __name__ == "__main__":
    sys.exit(main())
