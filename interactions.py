"""
Matchup-specific effects: does a player over- or under-perform against
particular OPPONENTS, or against particular STYLES of opponent?

Two distinct claims, and they deserve different priors:

  STYLE   "this player handles big servers better than his rating implies"
          Plausible mechanism (return position, block returns, court
          coverage), and every player faces many opponents of each style,
          so it is estimable.

  H2H     "this player just owns that guy"
          data_plan.md predicts near-zero once ability is controlled.  It
          is the first thing every commentator reaches for, which is
          exactly why the market overweights it.  Built here so it can be
          MEASURED rather than argued about -- see backtest.py.

Both are residual models on top of the Barnett-Clarke expectation, so they
can only capture what serve and return ratings do NOT already explain:

    residual = observed_serve_rate - (serve[p] - ret[opp] + rbar)

Both are empirical-Bayes shrunk.  A raw per-pair or per-player slope is a
coin flip dressed as an insight.
"""

import math
from collections import defaultdict

from ratings import TOUR_AVG

MIN_STYLE_MATCHES = 15
MIN_H2H_POINTS = 200


def residuals(matches, serve, ret, asof, half_life=730, tour_avg=TOUR_AVG):
    """(player, opponent, weight, points, residual, opponent_style).

    style > 0 means the opponent is serve-biased (big serve, weak return);
    style < 0 means return-biased.  It is the opponent's shape, with their
    overall LEVEL already removed -- level is what the base model handles.
    """
    rbar = 1 - tour_avg
    out = []

    def add(p, opp, won, n, w):
        if n < 20 or p not in serve or opp not in ret or opp not in serve:
            return
        exp = min(max(serve[p] - ret[opp] + rbar, 0.05), 0.95)
        style = (serve[opp] - tour_avg) - (ret[opp] - rbar)
        out.append((p, opp, w, n, won / n - exp, style))

    for t, a, b, asv, awn, bsv, bwn in matches:
        w = 0.5 ** ((asof - t) / half_life)
        add(a, b, awn, asv, w)
        add(b, a, bwn, bsv, w)
    return out


def _split_halves(rows_by_key, rng_seed=0):
    """Split each key's rows into two random halves."""
    import random
    rng = random.Random(rng_seed)
    h1, h2 = {}, {}
    for k, rows in rows_by_key.items():
        idx = list(range(len(rows)))
        rng.shuffle(idx)
        m = len(idx) // 2
        if m < 4:
            continue
        h1[k] = [rows[i] for i in idx[:m]]
        h2[k] = [rows[i] for i in idx[m:2 * m]]
    return h1, h2


def _reliability(a, b):
    """Correlation between two independent halves of the same estimate."""
    ks = [k for k in a if k in b]
    if len(ks) < 25:
        return 0.0, len(ks)
    xs, ys = [a[k] for k in ks], [b[k] for k in ks]
    n = len(ks)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0, n
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n * sx * sy)
    return r, n


def _shrink_by_reliability(full, h1, h2):
    """Shrink raw estimates by how much they actually replicate.

    The earlier attempt derived shrinkage from an analytic variance formula
    for a weighted-least-squares slope.  That formula overstated the noise,
    tau^2 came out <= 0, and a real effect (split-half r = 0.23 across 137
    players) was flattened to exactly zero.

    Measuring reliability directly avoids having to get that algebra right.
    Split each player's matches into random halves, estimate independently,
    correlate.  Spearman-Brown gives the reliability of the full-data
    estimate, r_full = 2r/(1+r), and classical test theory says the optimal
    shrinkage toward the mean IS that reliability.

    r <= 0 means the estimate does not replicate, and everything collapses
    to zero -- which is a finding, not a bug.
    """
    r, n = _reliability(h1, h2)
    if r <= 0:
        return {k: 0.0 for k in full}, 0.0, n
    r_full = 2 * r / (1 + r)
    mu = sum(full.values()) / len(full) if full else 0.0
    return ({k: mu + r_full * (v - mu) for k, v in full.items()},
            r_full, n)


def _slope(rows):
    """Weighted least-squares slope of residual on opponent style."""
    sw = sum(x[0] for x in rows)
    if sw <= 0:
        return None
    mr = sum(x[0] * x[1] for x in rows) / sw
    ms = sum(x[0] * x[2] for x in rows) / sw
    sxx = sum(x[0] * (x[2] - ms) ** 2 for x in rows)
    if sxx <= 1e-12:
        return None
    return sum(x[0] * (x[2] - ms) * (x[1] - mr) for x in rows) / sxx


def derive_style_slopes(res, min_matches=MIN_STYLE_MATCHES, shrink=True):
    """Per-player slope of serve residual on opponent style.

    Positive slope: this player beats expectation against serve-biased
    opponents (big serve, weak return).  Negative: he prefers grinders.
    Shrunk by measured split-half reliability.
    """
    grp = defaultdict(list)
    for p, opp, w, n, r, st in res:
        grp[p].append((w * n, r, st))
    grp = {k: v for k, v in grp.items() if len(v) >= min_matches}

    full = {k: b for k, v in grp.items() if (b := _slope(v)) is not None}
    if not shrink:
        return full, 1.0, len(full)
    a, b_ = _split_halves(grp)
    h1 = {k: s for k, v in a.items() if (s := _slope(v)) is not None}
    h2 = {k: s for k, v in b_.items() if (s := _slope(v)) is not None}
    return _shrink_by_reliability(full, h1, h2)


def _mean_resid(rows):
    sw = sum(x[0] for x in rows)
    return sum(x[0] * x[1] for x in rows) / sw if sw > 0 else None


def derive_h2h(res, min_points=MIN_H2H_POINTS, shrink=True):
    """Per (player, opponent) residual -- the classic head-to-head claim.

    Measured, not assumed.  Split-half reliability across eras came back at
    +1.6 SE on 97 pairs: suggestive, and not distinguishable from zero.
    Shrinkage is calibrated the same way as style, so if it does not
    replicate it contributes nothing.
    """
    grp = defaultdict(list)
    pts = defaultdict(float)
    for p, opp, w, n, r, st in res:
        grp[(p, opp)].append((w * n, r, st))
        pts[(p, opp)] += n
    grp = {k: v for k, v in grp.items() if pts[k] >= min_points}

    full = {k: m for k, v in grp.items() if (m := _mean_resid(v)) is not None}
    if not shrink:
        return full, 1.0, len(full)
    a, b_ = _split_halves(grp)
    h1 = {k: m for k, v in a.items() if (m := _mean_resid(v)) is not None}
    h2 = {k: m for k, v in b_.items() if (m := _mean_resid(v)) is not None}
    return _shrink_by_reliability(full, h1, h2)


def apply_style(serve_p, style_opp, slope, cap=0.03):
    """Adjust a serve rating for this specific opponent's style."""
    if not slope:
        return serve_p
    return serve_p + max(-cap, min(cap, slope * style_opp))
