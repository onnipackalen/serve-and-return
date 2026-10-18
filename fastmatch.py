"""
Fast match-probability lookup.

check.p_match is the exact recursion and costs ~0.09 ms.  That is fine as a
gate and far too slow for a backtest doing millions of evaluations, or for
an interactive tool that must answer instantly.

p_match is smooth in (pa, pb), so tabulate it once on a fine grid and
bilinearly interpolate.  Accuracy is verified against the exact recursion at
import-test time -- run `python3 fastmatch.py` to see the max error.

The exact version stays the source of truth; this is a cache, never a
replacement.  check.py still gates against p_match itself.
"""

import os
import numpy as np

from check import p_match

LO, HI, STEP = 0.30, 0.92, 0.002
CACHE = os.path.join(os.path.dirname(__file__) or ".", "matchgrid.npz")

_PS = None
_G = {}


def build(verbose=True):
    ps = np.arange(LO, HI + STEP / 2, STEP)
    out = {"ps": ps}
    for bo in (3, 5):
        g = np.empty((len(ps), len(ps)))
        for i, a in enumerate(ps):
            for j, b in enumerate(ps):
                g[i, j] = p_match(float(a), float(b), bo)
        out[f"bo{bo}"] = g
        if verbose:
            print(f"  built Bo{bo} grid {g.shape}")
    np.savez_compressed(CACHE, **out)
    return out


def _load():
    global _PS, _G
    if _PS is not None:
        return
    if not os.path.exists(CACHE):
        build()
    d = np.load(CACHE)
    _PS = d["ps"]
    _G = {3: d["bo3"], 5: d["bo5"]}


def _interp(pa, pb, bo):
    """Bilinear interpolation of P(A wins | A serves first)."""
    _load()
    g = _G[bo]
    n = len(_PS)
    fa = (np.clip(pa, LO, HI) - LO) / STEP
    fb = (np.clip(pb, LO, HI) - LO) / STEP
    i0 = np.clip(np.floor(fa).astype(int), 0, n - 2)
    j0 = np.clip(np.floor(fb).astype(int), 0, n - 2)
    da, db = fa - i0, fb - j0
    return (g[i0, j0] * (1 - da) * (1 - db) + g[i0 + 1, j0] * da * (1 - db) +
            g[i0, j0 + 1] * (1 - da) * db + g[i0 + 1, j0 + 1] * da * db)


# 5-node Gauss-Hermite, for integrating over match-day form
_GH_X = np.array([-2.020182870456086, -0.958572464613819, 0.0,
                  0.958572464613819, 2.020182870456086])
_GH_W = np.array([0.019953242059046, 0.393619323152241, 0.945308720482942,
                  0.393619323152241, 0.019953242059046])
_GH_W = _GH_W / _GH_W.sum()


def win_prob(pa, pb, best_of=3, form_sd=0.0, form_sd_b=None):
    """P(A wins), averaged over who serves first, integrated over form.

    Serve order matters: every CSV row is (winner, loser), so pricing with
    A-always-first would hand the winner the first serve in every match.

    form_sd covers match-day ability variation, which the point model omits
    entirely -- without it the only randomness is binomial, which is far less
    than real matches show, and the model comes out systematically
    overconfident.  Pass form_sd_b to give the two players different
    volatility; weights.py derives those per player.
    """
    sb = form_sd if form_sd_b is None else form_sd_b
    if form_sd <= 0 and sb <= 0:
        return float(0.5 * (_interp(pa, pb, best_of) +
                            1.0 - _interp(pb, pa, best_of)))
    ka, kb = np.sqrt(2.0) * form_sd, np.sqrt(2.0) * sb
    qa = np.clip(pa + ka * _GH_X, LO, HI)[:, None]
    qb = np.clip(pb + kb * _GH_X, LO, HI)[None, :]
    w = _GH_W[:, None] * _GH_W[None, :]
    fwd = _interp(qa, qb, best_of)
    rev = _interp(qb.T, qa.T, best_of).T
    return float((w * 0.5 * (fwd + 1.0 - rev)).sum())


if __name__ == "__main__":
    import random
    import time
    if not os.path.exists(CACHE):
        print("building grid (one-off)...")
        build()
    _load()
    print(f"grid {_G[3].shape}, step {STEP}, cache {os.path.getsize(CACHE)/1e6:.1f} MB\n")

    rng = random.Random(0)
    worst = 0.0
    for _ in range(400):
        pa = rng.uniform(0.45, 0.85); pb = rng.uniform(0.45, 0.85)
        bo = rng.choice((3, 5))
        exact = 0.5 * (p_match(pa, pb, bo) + 1 - p_match(pb, pa, bo))
        worst = max(worst, abs(exact - win_prob(pa, pb, bo)))
    print(f"max interpolation error vs exact recursion: {worst:.2e}")
    print(f"  ({'ok -- far below pricing precision' if worst < 1e-4 else 'TOO COARSE'})")

    t = time.time()
    for _ in range(20000):
        win_prob(0.66, 0.63, 3)
    print(f"\nlookup      {(time.time()-t)/20000*1e6:6.1f} us/call")
    t = time.time()
    for _ in range(2000):
        win_prob(0.66, 0.63, 3, form_sd=0.02)
    print(f"with form   {(time.time()-t)/2000*1e6:6.1f} us/call")
