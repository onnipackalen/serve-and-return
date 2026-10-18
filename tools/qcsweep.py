"""Does adding 133,000 qualifying and Challenger matches improve the ratings?

    python3 tools/qcsweep.py run 0 1.0      score k=0 and k=1.0
    python3 tools/qcsweep.py compare        paired t-test over everything cached

The archive ships 49 qualifying/Challenger files that load() has never
opened. They are 3.2x the main-tour volume, and for the 568 players the
confidence bands call THIN they carry 28x more service points than the tour
does -- exactly the population that measures a +0.038 deficit against the
closing line.

The catch is that a point at a Challenger is not a point on tour: the
population serves 0.611 there against 0.637 in a main draw. Part of that is
weaker players, which the opponent adjustment already handles, and part is
the level itself. The two are not separable by inspection -- comparing the
same player at both levels comes out with the OPPOSITE sign, because on tour
they face far better returners -- so `k` scales the correction and is swept:

    k = 0    a Challenger point counts exactly as a tour point
    k = 1    each level is shifted fully onto the main-draw baseline

Rule 1 throughout: the supplement joins what the ratings are FITTED on and
never what the model is SCORED on, so every config is scored on identical
main-tour matches and compared with a paired per-match t-test.
"""

import math
import os
import pickle
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from backtest import records, walk_forward, price_player, logloss   # noqa: E402
from load import qc_records                                        # noqa: E402

OUT = os.path.join(HERE, "_qcsweep")
SCALES = (0.4, 0.5, 0.6, 0.75, 0.85, 1.0, 1.2)


def run(recs, k):
    # False, not None: None now means "whatever fitted_params says ships",
    # and the baseline here must be NO supplement
    sup = False if k is None else qc_records(2005, 2026, k=k)
    t0 = time.time()
    preds = dict(walk_forward(recs, player_mode=True, supplement=sup))
    tag = "no supplement" if k is None else f"k={k}"
    print(f"  {tag:<16} {len(preds):,} scorable  "
          f"({len(sup) if sup else 0:,} supplement rows, "
          f"{time.time() - t0:.0f}s)", flush=True)
    return preds


def paired(recs, store, base_key):
    common = sorted(set.intersection(*(set(v) for v in store.values())))
    span = recs[common[-1]][0] - recs[common[0]][0]
    cut = recs[common[0]][0] + span // 2
    tr = [i for i in common if recs[i][0] < cut]
    te = [i for i in common if recs[i][0] >= cut]
    print(f"\ncommon {len(common):,}   train {len(tr):,} / test {len(te):,}\n")

    def scored(preds):
        best, bs = 1e9, None
        for sc in SCALES:
            ll = logloss([price_player(preds[i], sc) for i in tr])
            if ll < best:
                best, bs = ll, sc
        return [price_player(preds[i], bs) for i in te], bs

    base_ps, _ = scored(store[base_key])
    base = [-math.log(max(p, 1e-12)) for p in base_ps]

    print(f"  {'config':>16} {'scale':>6} {'test ll':>9} {'vs base':>9} "
          f"{'paired t':>9}")
    for kk in sorted(store, key=lambda x: (x is not None, x)):
        ps, sc = scored(store[kk])
        loss = [-math.log(max(p, 1e-12)) for p in ps]
        d = [b - x for b, x in zip(base, loss)]
        n = len(d)
        mu = sum(d) / n
        sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else 0
        t = mu / (sd / math.sqrt(n)) if sd else 0.0
        lbl = "no supplement" if kk is None else f"k={kk}"
        tag = "  <- baseline" if kk == base_key else ""
        print(f"  {lbl:>16} {sc:>6.2f} {sum(loss)/n:>9.5f} {-mu:>+9.5f} "
              f"{t:>+9.2f}{tag}")


def main():
    os.makedirs(OUT, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"
    recs = records(2005, 2026)
    if cmd == "run":
        for a in sys.argv[2:]:
            k = None if a == "none" else float(a)
            preds = run(recs, k)
            with open(os.path.join(OUT, f"{a}.pkl"), "wb") as fh:
                pickle.dump(preds, fh)
        return 0
    store = {}
    for fn in sorted(os.listdir(OUT)):
        if fn.endswith(".pkl"):
            a = fn[:-4]
            with open(os.path.join(OUT, fn), "rb") as fh:
                store[None if a == "none" else float(a)] = pickle.load(fh)
    if None not in store:
        sys.exit("baseline 'none' not scored yet")
    print(f"{len(store)} configs cached")
    paired(recs, store, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
