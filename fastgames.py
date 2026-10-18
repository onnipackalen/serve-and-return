"""
Tabulated TOTAL-GAMES distribution, the way fastmatch tabulates P(win).

    python3 fastgames.py build     build the table (~5 min, once)
    python3 fastgames.py 0.67 0.63 5

The exact recursion in check.py gives P(win) and nothing else.  Totals need
the whole distribution, and simulating 20,000 matches per price is fine for
one matchup and hopeless for a 30,000-match backtest.  So the distribution
is tabulated on a grid of the two serve probabilities once, and every later
lookup is an interpolation.

Same discipline as fastmatch: the table is an approximation of the
simulator, the simulator is the source of truth, and the gate below reports
the interpolation error rather than assuming it away.
"""

import json
import os
import random
import sys

import tennis_sim as TS

TABLE = os.path.join(os.path.dirname(__file__) or ".", "gamesgrid.json")
LO, HI, STEP = 0.35, 0.90, 0.02        # price.py clamps serve p to this range
MAX_GAMES = 80
_T = None


def _axis():
    n = int(round((HI - LO) / STEP)) + 1
    return [round(LO + i * STEP, 4) for i in range(n)]


def build(sims=4000, seed=0, verbose=True):
    ax = _axis()
    out = {"axis": ax, "sims": sims, "dist": {}}
    rng = random.Random(seed)
    for bo in (3, 5):
        for i, pa in enumerate(ax):
            for pb in ax:
                hist = [0] * (MAX_GAMES + 1)
                for _ in range(sims):
                    st = TS.sim_match(
                        TS.Ctx(players=(None, None), base_p=(pa, pb)),
                        TS.static_p, bo, rng)
                    g = sum(x + y for x, y in st.set_scores)
                    hist[min(g, MAX_GAMES)] += 1
                out["dist"][f"{bo}|{pa}|{pb}"] = hist
            if verbose:
                print(f"  bo{bo} row {i+1}/{len(ax)}", flush=True)
    with open(TABLE, "w") as fh:
        json.dump(out, fh)
    if verbose:
        print(f"wrote {TABLE}")
    return out


def _load():
    global _T
    if _T is None:
        if not os.path.exists(TABLE):
            sys.exit("no games table -- run: python3 fastgames.py build")
        with open(TABLE) as fh:
            _T = json.load(fh)
    return _T


def _clamp(p):
    return min(max(p, LO), HI)


def distribution(pa, pb, best_of=3):
    """Probability of each total-games value, bilinearly interpolated."""
    t = _load()
    ax = t["axis"]
    pa, pb = _clamp(pa), _clamp(pb)
    ia = min(int((pa - LO) / STEP), len(ax) - 2)
    ib = min(int((pb - LO) / STEP), len(ax) - 2)
    fa = (pa - ax[ia]) / STEP
    fb = (pb - ax[ib]) / STEP
    acc = [0.0] * (MAX_GAMES + 1)
    for da, wa in ((0, 1 - fa), (1, fa)):
        for db, wb in ((0, 1 - fb), (1, fb)):
            w = wa * wb
            if w <= 0:
                continue
            h = t["dist"][f"{best_of}|{ax[ia+da]}|{ax[ib+db]}"]
            s = sum(h) or 1
            for g, c in enumerate(h):
                acc[g] += w * c / s
    return acc


def expected(pa, pb, best_of=3):
    d = distribution(pa, pb, best_of)
    return sum(g * p for g, p in enumerate(d))


# Fitted bias correction, in games.  The table is built from independent
# points, and real matches finish SOONER than that implies: measured +0.52
# games too long in best-of-3 and +1.81 in best-of-5, after form is already
# integrated.  Points are not independent -- breaks cluster, sets run away --
# and rather than invent a dependence model this subtracts what was measured.
# Validated out of sample: fitted on the earlier half of 2015-2026, it
# removed 84% of the bias on the later half (bo3 +0.574 -> +0.091,
# bo5 +1.756 -> +0.339).  These are the full-sample values.
BIAS = {3: 0.53, 5: 1.59}


def expected_form(pa, pb, best_of=3, form_sd_a=0.0, form_sd_b=0.0,
                  draws=12, seed=0, correct=True):
    """Expected total games, integrating over the match-day form draw.

    The table itself is static: it assumes both players play at exactly
    their rated level.  price.py does not assume that, and neither should
    this -- form variation makes some matches lopsided, and lopsided matches
    are SHORT.  Ignoring it over-predicted length by 1.5 games.
    """
    if not (form_sd_a or form_sd_b):
        e = expected(pa, pb, best_of)
    else:
        rng = random.Random(seed)
        tot = 0.0
        for _ in range(draws):
            tot += expected(pa + rng.gauss(0, form_sd_a),
                            pb + rng.gauss(0, form_sd_b), best_of)
        e = tot / draws
    return e - (BIAS.get(best_of, 0.0) if correct else 0.0)


def dist_form(pa, pb, best_of=3, form_sd_a=0.0, form_sd_b=0.0,
              draws=12, seed=0):
    """Games distribution integrated over form, shifted by the fitted bias."""
    rng = random.Random(seed)
    acc = [0.0] * (MAX_GAMES + 1)
    n = max(1, draws) if (form_sd_a or form_sd_b) else 1
    for _ in range(n):
        qa = pa + rng.gauss(0, form_sd_a) if form_sd_a else pa
        qb = pb + rng.gauss(0, form_sd_b) if form_sd_b else pb
        d = distribution(qa, qb, best_of)
        for g, p in enumerate(d):
            acc[g] += p / n
    shift = int(round(BIAS.get(best_of, 0.0)))
    if shift:
        out = [0.0] * (MAX_GAMES + 1)
        for g, p in enumerate(acc):
            out[max(0, g - shift)] += p
        return out
    return acc


def p_over_form(pa, pb, line, best_of=3, form_sd_a=0.0, form_sd_b=0.0,
                draws=12, seed=0):
    d = dist_form(pa, pb, best_of, form_sd_a, form_sd_b, draws, seed)
    return sum(p for g, p in enumerate(d) if g > line)


def p_over(pa, pb, line, best_of=3):
    """P(total games strictly above `line`).  Use a .5 line to avoid pushes."""
    d = distribution(pa, pb, best_of)
    return sum(p for g, p in enumerate(d) if g > line)


# ------------------------------------------------------------------- gate

def _gate(trials=6, sims=20000):
    """Table vs a fresh simulation -- the same check fastmatch makes."""
    rng = random.Random(7)
    worst_mean = worst_p = 0.0
    print(f"  {'pa':>6} {'pb':>6} {'bo':>3} {'sim mean':>9} {'tab mean':>9} "
          f"{'d':>7} {'sim P>21.5':>11} {'tab':>7} {'d':>7}")
    for _ in range(trials):
        pa = rng.uniform(0.55, 0.80)
        pb = rng.uniform(0.55, 0.80)
        bo = rng.choice((3, 5))
        tot, over = 0, 0
        for _ in range(sims):
            st = TS.sim_match(TS.Ctx(players=(None, None), base_p=(pa, pb)),
                              TS.static_p, bo, rng)
            g = sum(x + y for x, y in st.set_scores)
            tot += g
            over += g > 21.5
        sm, sp = tot / sims, over / sims
        tm, tp = expected(pa, pb, bo), p_over(pa, pb, 21.5, bo)
        worst_mean = max(worst_mean, abs(sm - tm))
        worst_p = max(worst_p, abs(sp - tp))
        print(f"  {pa:>6.3f} {pb:>6.3f} {bo:>3} {sm:>9.3f} {tm:>9.3f} "
              f"{sm-tm:>+7.3f} {sp:>11.4f} {tp:>7.4f} {sp-tp:>+7.4f}")
    print(f"\n  worst mean-games error {worst_mean:.3f} games   "
          f"worst P(over) error {worst_p:.4f}")
    return 1 if (worst_mean > 0.35 or worst_p > 0.02) else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
        raise SystemExit(0)
    if len(sys.argv) >= 3:
        pa, pb = float(sys.argv[1]), float(sys.argv[2])
        bo = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        d = distribution(pa, pb, bo)
        print(f"serve p {pa} / {pb}, best of {bo}")
        print(f"  expected total games {expected(pa, pb, bo):.2f}")
        for line in (19.5, 21.5, 22.5, 23.5, 25.5, 37.5, 39.5):
            print(f"  P(over {line:>5}) {p_over(pa, pb, line, bo):.4f}")
        raise SystemExit(0)
    print("\ngames table vs simulator")
    raise SystemExit(_gate())
