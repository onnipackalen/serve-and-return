"""Does an AGE-DEPENDENT rating half-life beat a single global one?

    python3 tools/agehl.py                 the sweep
    python3 tools/agehl.py 0.6 0.8         score one (m_young, m_old)

The `age` residual curve is the largest correction in the model: players
under 21 beat their own price by 8 points, players over 33 miss it by 4,
monotone across every bucket and every era.  The mechanism is not mysterious.
`ratings.fit_iterative` is an exponentially weighted mean over a 270-day
half-life, and an exponentially weighted mean LAGS a trend by roughly

    lag  ~=  slope * half_life / ln 2

so a player whose ability is rising has a rating that sits below it, and one
whose ability is falling has a rating that sits above it.  The curve corrects
that after the fact.  This asks the better question: can the estimator stop
producing the error in the first place?

Shortening the half-life cuts the lag and raises the variance -- fewer
effective points behind each rating.  The optimum trades one against the
other, and it should not be the same at every age, because the SLOPE is not:
a 20-year-old is improving fast, a 27-year-old is flat, a 34-year-old is
declining.  So the half-life is multiplied by a piecewise-linear function of
age with two free numbers, m_young and m_old, both 1.0 at the prime.

Rule 1: every config is scored on the SAME matches, with a paired per-match
t-test, because a shorter half-life qualifies fewer players and raw log loss
would reward whichever config scores the easiest subset.
"""

import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from backtest import records, walk_forward, price_player, logloss   # noqa: E402
from load import BIRTHDAYS                                          # noqa: E402

# knots, in years.  Fixed rather than fitted: three free numbers on 29,000
# matches is a sweep, five is a fishing trip.
Y_LO, MID, O_HI = 22.0, 28.0, 34.0
SCALES = (0.4, 0.5, 0.6, 0.75, 0.85, 1.0, 1.2)   # form_scale, fitted on train


def multiplier(age, m_young, m_old):
    """Piecewise-linear in age, pinned to 1.0 through the prime."""
    if age is None:
        return 1.0
    if age <= Y_LO:
        return m_young
    if age < MID:
        return m_young + (1.0 - m_young) * (age - Y_LO) / (MID - Y_LO)
    if age <= O_HI:
        return 1.0 + (m_old - 1.0) * (age - MID) / (O_HI - MID)
    return m_old


def make_fn(base_hl, m_young, m_old):
    """backtest's half_life_fn: given a refit day, give pid -> half_life.

    (1.0, 1.0) must return a function that yields None -- the single global
    half-life -- and NOT None itself: to walk_forward, half_life_fn=None
    means "whatever fitted_params ships", which since the age half-life was
    adopted is (0.70, 0.85).  Returning None here made the "baseline" run
    identical to the shipped config, bit for bit, on 2026-09-11.
    """
    if m_young == 1.0 and m_old == 1.0:
        return lambda t: None                      # one global half-life
    def at(t):
        def hl(pid):
            b = BIRTHDAYS.get(pid)
            if b is None:
                return base_hl
            return base_hl * multiplier((t - b) / 365.25, m_young, m_old)
        return hl
    return at


def run(recs, base_hl, m_young, m_old):
    t0 = time.time()
    preds = dict(walk_forward(recs, half_life=base_hl, player_mode=True,
                              half_life_fn=make_fn(base_hl, m_young, m_old)))
    print(f"  young {m_young:.2f} old {m_old:.2f}  "
          f"{len(preds):,} scorable  ({time.time() - t0:.0f}s)", flush=True)
    return preds


def paired(recs, store, base_key):
    """Score every config on the intersection, paired against the baseline."""
    common = sorted(set.intersection(*(set(v) for v in store.values())))
    span = recs[common[-1]][0] - recs[common[0]][0]
    cut = recs[common[0]][0] + span // 2
    tr = [i for i in common if recs[i][0] < cut]
    te = [i for i in common if recs[i][0] >= cut]
    print(f"\ncommon {len(common):,}   train {len(tr):,} / test {len(te):,}\n")

    def scored(preds):
        best, bs = 1e9, None
        for sc in SCALES:                          # form_scale on TRAIN only
            ll = logloss([price_player(preds[i], sc) for i in tr])
            if ll < best:
                best, bs = ll, sc
        return [price_player(preds[i], bs) for i in te], bs

    base_ps, _bs = scored(store[base_key])
    base_loss = [-math.log(max(p, 1e-12)) for p in base_ps]

    print(f"  {'m_young':>8} {'m_old':>6} {'scale':>6} {'test ll':>9} "
          f"{'vs base':>9} {'paired t':>9}")
    out = {}
    for k in sorted(store):
        ps, sc = scored(store[k])
        loss = [-math.log(max(p, 1e-12)) for p in ps]
        d = [b - x for b, x in zip(base_loss, loss)]     # >0 means better
        n = len(d)
        mu = sum(d) / n
        sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else 0
        t = mu / (sd / math.sqrt(n)) if sd else 0.0
        ll = sum(loss) / n
        tag = "  <- baseline" if k == base_key else ""
        print(f"  {k[0]:>8.2f} {k[1]:>6.2f} {sc:>6.2f} {ll:>9.5f} "
              f"{-mu:>+9.5f} {t:>+9.2f}{tag}")
        out[k] = (ll, -mu, t)
    return out


OUT = os.environ.get("AGEHL_OUT", os.path.join(HERE, "_agehl"))


def main():
    """`agehl.py run 0.7 1.0 ...` scores configs and caches each to disk;
    `agehl.py compare` loads every cached config and does the paired test.

    Split so the grid can run several processes wide -- each config is a
    full walk-forward and costs about six minutes, and the machine has ten
    cores doing nothing.
    """
    import pickle
    os.makedirs(OUT, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"

    if cmd == "run":
        recs = records(2005, 2026)
        print(f"{len(recs):,} rated matches; birthdays for "
              f"{len(BIRTHDAYS):,} players", flush=True)
        if not BIRTHDAYS:
            sys.exit("no birthdays -- every config would be the baseline")
        vals = [float(a) for a in sys.argv[2:]]
        for i in range(0, len(vals), 2):
            my, mo = vals[i], vals[i + 1]
            preds = run(recs, 270, my, mo)
            with open(os.path.join(OUT, f"{my}_{mo}.pkl"), "wb") as fh:
                pickle.dump(preds, fh)
        return 0

    recs = records(2005, 2026)
    store = {}
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith(".pkl"):
            continue
        my, mo = (float(x) for x in fn[:-4].split("_"))
        with open(os.path.join(OUT, fn), "rb") as fh:
            store[(my, mo)] = pickle.load(fh)
    if (1.0, 1.0) not in store:
        sys.exit("baseline (1.0, 1.0) not scored yet")
    print(f"{len(store)} configs cached")
    paired(recs, store, (1.0, 1.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
