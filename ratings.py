"""
M2 -- decayed, shrunk, opponent-adjusted serve and return ratings.

Built and gated against SYNTHETIC data with known true abilities before being
pointed at real matches.  Real data can tell you a model is broken; only
synthetic data can tell you it is right.

Gates:
  1. RECOVERY   estimator recovers known abilities from generated matches,
                including under assortative pairing where the naive estimator
                is provably biased.
  2. NO LEAKAGE as-of ratings are bit-identical whether or not future matches
                exist in the stream.
  3. CALIBRATION fitted half-life beats a flat career average on held-out
                log loss.  (needs real data -- see backtest.py)

Design notes, all from data_plan.md:
  * decay weights the COUNTS, not match-level percentages
  * decay runs on CALENDAR days, so an injured player's rating goes stale
  * two timescales, because "how good is he" and "how is he playing" are
    different questions and one half-life cannot answer both
  * opponent adjustment uses only ratings as of the match, never after
"""

import math
import os
from collections import defaultdict

TOUR_AVG = 0.6372          # measured in M1; see tour_avg.json for per-surface
HL_FAST = 90               # days -- current form
HL_SLOW = 270              # days -- fitted (was 730 by assumption)
ALPHA = 0.30               # weight on fast; fit this, do not trust the default
PRIOR_WEIGHT = 150         # pseudo-counts, in service points; fitted


class Acc:
    """Decayed count accumulator.  Decays lazily; never mutates on read.

    Holds three running sums so that a rating is one division:
      num  weighted points won
      den  weighted points played
      adj  weighted opponent-strength correction, in the same units as num
    """
    __slots__ = ("num", "den", "adj", "t")

    def __init__(self):
        self.num = self.den = self.adj = 0.0
        self.t = None

    def _factor(self, t, hl):
        if self.t is None:
            return 1.0
        if t < self.t:
            raise ValueError(f"non-monotonic time: {t} < {self.t}")
        return 0.5 ** ((t - self.t) / hl)

    def add(self, t, hl, won, pts, adj):
        f = self._factor(t, hl)
        self.num = self.num * f + won
        self.den = self.den * f + pts
        self.adj = self.adj * f + adj
        self.t = t

    def value(self, t, hl, prior, prior_weight):
        f = self._factor(t, hl)                      # read-only
        return ((self.num + self.adj) * f + prior_weight * prior) / \
               (self.den * f + prior_weight)


class Ratings:
    """Streaming serve/return ratings.  Feed matches in chronological order."""

    def __init__(self, tour_avg=TOUR_AVG, hl_fast=HL_FAST, hl_slow=HL_SLOW,
                 alpha=ALPHA, prior_weight=PRIOR_WEIGHT, adjust=True):
        self.ta = tour_avg
        self.hl = (hl_fast, hl_slow)
        self.alpha = alpha
        self.pw = prior_weight
        self.adjust = adjust                          # off => naive estimator
        self.S = defaultdict(lambda: (Acc(), Acc()))  # serve  (fast, slow)
        self.R = defaultdict(lambda: (Acc(), Acc()))  # return (fast, slow)
        self.n = defaultdict(int)                     # matches seen, per player

    # ---------------------------------------------------------- read

    def serve(self, pid, t):
        a, b = self.S[pid]
        return (self.alpha * a.value(t, self.hl[0], self.ta, self.pw) +
                (1 - self.alpha) * b.value(t, self.hl[1], self.ta, self.pw))

    def ret(self, pid, t):
        a, b = self.R[pid]
        p = 1 - self.ta
        return (self.alpha * a.value(t, self.hl[0], p, self.pw) +
                (1 - self.alpha) * b.value(t, self.hl[1], p, self.pw))

    def matchup(self, a, b, t, tour_avg=None):
        """(p_a_on_serve, p_b_on_serve) -- Barnett-Clarke, opponent adjusted."""
        ta = self.ta if tour_avg is None else tour_avg
        pa = ta + (self.serve(a, t) - ta) - (self.ret(b, t) - (1 - ta))
        pb = ta + (self.serve(b, t) - ta) - (self.ret(a, t) - (1 - ta))
        return pa, pb

    # --------------------------------------------------------- write

    def observe(self, t, a, b, a_svpt, a_won, b_svpt, b_won):
        """Record one match.  Adjustments use ratings AS OF t, so the update
        can never see its own result -- that is what makes this leak-free."""
        if a_svpt <= 0 or b_svpt <= 0:
            return

        if self.adjust:
            # a served into b's return: observed rate understates a if b
            # returns better than average.  Correct back toward true ability.
            adj_as = a_svpt * (self.ret(b, t) - (1 - self.ta))
            adj_bs = b_svpt * (self.ret(a, t) - (1 - self.ta))
            # a returned b's serve: observed understates a if b serves big.
            adj_ar = b_svpt * (self.serve(b, t) - self.ta)
            adj_br = a_svpt * (self.serve(a, t) - self.ta)
        else:
            adj_as = adj_bs = adj_ar = adj_br = 0.0

        for i, hl in enumerate(self.hl):
            self.S[a][i].add(t, hl, a_won, a_svpt, adj_as)
            self.S[b][i].add(t, hl, b_won, b_svpt, adj_bs)
            self.R[a][i].add(t, hl, b_svpt - b_won, b_svpt, adj_ar)
            self.R[b][i].add(t, hl, a_svpt - a_won, a_svpt, adj_br)
        self.n[a] += 1
        self.n[b] += 1



# =============================================== ITERATIVE (BATCH) FIT

# ---------------------------------------------------------------- age decay
#
# An exponentially weighted mean LAGS a trend by roughly
#
#     lag  ~=  slope * half_life / ln 2
#
# so a player whose ability is moving wants a shorter memory than one whose
# is not.  Young players are improving, old ones declining, and the residual
# curve on age is monotone across both -- one mechanism, two signs.  Rather
# than correct that after the fact, shorten the half-life at both ends.
#
# The knots are fixed and the two multipliers are fitted (tools/agehl.py),
# because three free numbers on 25,000 matches is a sweep and five is a
# fishing trip.  Multipliers of 1.0 reproduce the single global half-life
# exactly, which is the default until something measures otherwise.
AGE_KNOTS = (22.0, 28.0, 34.0)          # young plateau, prime, old plateau
if os.environ.get("TENNIS_AGE_KNOTS"):   # for tools/knobsweep.py only
    AGE_KNOTS = tuple(float(x) for x in os.environ["TENNIS_AGE_KNOTS"].split(","))


def age_multiplier(age, m_young, m_old):
    """Piecewise-linear in age, pinned to 1.0 through the prime years."""
    lo, mid, hi = AGE_KNOTS
    if age is None:
        return 1.0
    if age <= lo:
        return m_young
    if age < mid:
        return m_young + (1.0 - m_young) * (age - lo) / (mid - lo)
    if age <= hi:
        return 1.0 + (m_old - 1.0) * (age - mid) / (hi - mid)
    return m_old


def age_half_life(base_hl, asof_day, birthdays, m_young, m_old):
    """pid -> half_life for one as-of day, or None when both multipliers
    are 1.0 (which is the shipped single-half-life model, bit for bit).

    ONE definition, imported by weights.py, backtest.py and tools/agehl.py.
    Two derivations of the same quantity drift; this project has the scars.
    """
    if (m_young == 1.0 and m_old == 1.0) or not birthdays:
        return None

    def hl(pid):
        b = birthdays.get(pid)
        if b is None:
            return base_hl
        return base_hl * age_multiplier((asof_day - b) / 365.25,
                                        m_young, m_old)
    return hl


def fit_iterative(matches, asof=None, max_iter=3000, half_life=HL_SLOW,
                  prior_weight=PRIOR_WEIGHT, tour_avg=TOUR_AVG, tol=1e-6,
                  half_life_fn=None, priors=None):
    """Two-way additive fit: serve and return solved jointly, to convergence.

    The streaming estimator corrects A's serve using B's return, which was
    itself corrected using A's serve.  One pass cannot resolve that
    circularity and lands WORSE than no correction (synthetic: slope 0.60
    adjusted vs 0.68 naive, against an oracle of 1.00).  Alternating until
    both sides stop moving recovers the oracle.

    CONVERGENCE IS NOT OPTIONAL.  Convergence rate is set by how well
    connected the who-played-whom graph is; under tight assortative pairing
    this needs ~150 sweeps, and a fixed low cap silently returns attenuated
    ratings that look plausible (slope 0.80).  `info["converged"]` is
    reported so that can never pass unnoticed -- check it.

    Each half-sweep updates every serve given the current returns, then
    every return given the new serves -- a Jacobi step on each side -- so
    it is two sparse matrix-vector products, done here with numpy bincount
    over the match edges.  fit_iterative_reference below is the plain loop
    it replaced on 2026-09-11, kept because ratings.py's gate asserts the
    two agree to 1e-9: one block of the walk-forward harness needed ~3,000
    sweeps and the loop took 15 minutes on it, which is what had quietly
    made every sweep in tools/ cost six minutes a config.

    tol=1e-6 is in units of serve probability -- about a hundred times finer
    than anything that moves a price -- so it is a genuine convergence test,
    not a loose one.

    Uses only matches at or before `asof`, so it is leak-free inside a
    walk-forward loop.  Returns (serve, ret, served_points, info).

    priors, when given, is pid -> (serve_prior, ret_prior): the level each
    player's estimate is shrunk toward by prior_weight, instead of the tour
    average.  weights.derive passes the player's own long-window rating
    when prior_mode is "own", so a player back from a layoff is pulled
    toward who they were rather than toward the middle of the tour.  The
    opponent adjustment is still measured against the tour average.
    """
    import numpy as np
    rbar = 1 - tour_avg
    if asof is None:
        asof = max(m[0] for m in matches)
    hl_cache = {}

    def _hl(p):
        if half_life_fn is None:
            return half_life
        if p not in hl_cache:
            hl_cache[p] = max(30.0, float(half_life_fn(p) or half_life))
        return hl_cache[p]

    idx, players = {}, []
    ia_, ib_, wa_, wb_, asv_, awn_, bsv_, bwn_ = [], [], [], [], [], [], [], []
    for t, a, b, asv, awn, bsv, bwn in matches:
        if t > asof or asv <= 0 or bsv <= 0:
            continue
        for p in (a, b):
            if p not in idx:
                idx[p] = len(players)
                players.append(p)
        gap = asof - t
        w_a = 0.5 ** (gap / _hl(a))               # calendar decay, on counts
        w_b = w_a if half_life_fn is None else 0.5 ** (gap / _hl(b))
        ia_.append(idx[a]); ib_.append(idx[b])
        wa_.append(w_a); wb_.append(w_b)
        asv_.append(asv); awn_.append(awn); bsv_.append(bsv); bwn_.append(bwn)

    n = len(players)
    if n == 0:
        return {}, {}, {}, {"iters": 0, "converged": True, "shift": 0.0,
                            "players": 0}
    ia, ib = np.array(ia_, dtype=np.int64), np.array(ib_, dtype=np.int64)
    wa, wb = np.array(wa_, dtype=float), np.array(wb_, dtype=float)
    asv, awn = np.array(asv_, dtype=float), np.array(awn_, dtype=float)
    bsv, bwn = np.array(bsv_, dtype=float), np.array(bwn_, dtype=float)

    def acc(where, what):
        return np.bincount(where, weights=what, minlength=n)

    # A's serve row decays at A's rate, B's return row at B's rate, off the
    # same match -- and each player's own equation carries their own
    # weight in the opponent-adjustment term, exactly as the loop did
    sv_num = acc(ia, wa * awn) + acc(ib, wb * bwn)
    sv_den = acc(ia, wa * asv) + acc(ib, wb * bsv)
    rt_num = acc(ib, wb * (asv - awn)) + acc(ia, wa * (bsv - bwn))
    rt_den = acc(ib, wb * asv) + acc(ia, wa * bsv)
    s_p = np.concatenate([ia, ib]); s_o = np.concatenate([ib, ia])
    s_w = np.concatenate([wa * asv, wb * bsv])
    r_p = np.concatenate([ib, ia]); r_o = np.concatenate([ia, ib])
    r_w = np.concatenate([wb * asv, wa * bsv])

    ps = np.full(n, float(tour_avg))          # per-player prior levels
    pr = np.full(n, float(rbar))
    if priors:
        for p, (a_s, a_r) in priors.items():
            j = idx.get(p)
            if j is not None:
                if a_s is not None:
                    ps[j] = float(a_s)
                if a_r is not None:
                    pr[j] = float(a_r)
    serve = ps.copy()
    ret = pr.copy()
    pw = float(prior_weight)
    it, shift = 0, float("inf")
    for it in range(1, max_iter + 1):
        adj = acc(s_p, s_w * (ret[s_o] - rbar))     # serve, given returns
        new = (sv_num + adj + pw * ps) / (sv_den + pw)
        shift = float(np.abs(new - serve).max())
        serve = new
        adj = acc(r_p, r_w * (serve[r_o] - tour_avg))  # returns, given serves
        new = (rt_num + adj + pw * pr) / (rt_den + pw)
        shift = max(shift, float(np.abs(new - ret).max()))
        ret = new
        if shift < tol:
            break

    info = {"iters": it, "converged": shift < tol, "shift": shift,
            "players": n}
    return (dict(zip(players, serve.tolist())),
            dict(zip(players, ret.tolist())),
            dict(zip(players, sv_den.tolist())), info)


def fit_iterative_reference(matches, asof=None, max_iter=3000,
                            half_life=HL_SLOW, prior_weight=PRIOR_WEIGHT,
                            tour_avg=TOUR_AVG, tol=1e-6, half_life_fn=None,
                            priors=None):
    """The original pure-Python fit, kept as the yardstick for the gate."""
    rbar = 1 - tour_avg
    sv_num, sv_den, rt_num, rt_den = {}, {}, {}, {}
    sv_opp, rt_opp = {}, {}                       # {player: {opponent: weight}}

    def touch(p):
        if p not in sv_num:
            sv_num[p] = sv_den[p] = rt_num[p] = rt_den[p] = 0.0
            sv_opp[p], rt_opp[p] = {}, {}

    if asof is None:
        asof = max(m[0] for m in matches)

    # PER-PLAYER decay.  half_life_fn(pid) lets a player's own history decay
    # at their own rate -- the point being that an exponentially weighted
    # mean LAGS a trend by roughly (slope * half_life / ln 2), so a player
    # who is changing fast wants a shorter memory than one who is not.
    #
    # Each player's own equation uses their own weight, including in the
    # opponent-adjustment term: sv_opp[a][b] belongs to A's serve equation
    # and so carries A's decay, while rt_opp[b][a] belongs to B's return
    # equation and carries B's.  Sharing one weight across both, which is
    # what a single global half-life does, is only correct because the two
    # rates happen to be equal.
    hl_cache = {}

    def _hl(p):
        if half_life_fn is None:
            return half_life
        if p not in hl_cache:
            hl_cache[p] = max(30.0, float(half_life_fn(p) or half_life))
        return hl_cache[p]

    for t, a, b, asv, awn, bsv, bwn in matches:
        if t > asof or asv <= 0 or bsv <= 0:
            continue
        touch(a); touch(b)
        gap = asof - t
        w_a = 0.5 ** (gap / _hl(a))               # calendar decay, on counts
        w_b = w_a if half_life_fn is None else 0.5 ** (gap / _hl(b))
        wa, wb = w_a * asv, w_b * bsv
        # a serving / b returning -- A's serve row decays at A's rate, B's
        # return row at B's rate, off the same match
        sv_num[a] += w_a * awn;         sv_den[a] += w_a * asv
        rt_num[b] += w_b * (asv - awn); rt_den[b] += w_b * asv
        sv_opp[a][b] = sv_opp[a].get(b, 0.0) + w_a * asv
        rt_opp[b][a] = rt_opp[b].get(a, 0.0) + w_b * asv
        # b serving / a returning
        sv_num[b] += w_b * bwn;         sv_den[b] += w_b * bsv
        rt_num[a] += w_a * (bsv - bwn); rt_den[a] += w_a * bsv
        sv_opp[b][a] = sv_opp[b].get(a, 0.0) + w_b * bsv
        rt_opp[a][b] = rt_opp[a].get(b, 0.0) + w_a * bsv

    players = list(sv_num)
    sv_items = {p: list(sv_opp[p].items()) for p in players}
    rt_items = {p: list(rt_opp[p].items()) for p in players}
    ps = {p: tour_avg for p in players}          # per-player prior levels
    pr = {p: rbar for p in players}
    for p, (a_s, a_r) in (priors or {}).items():
        if p in ps:
            if a_s is not None:
                ps[p] = float(a_s)
            if a_r is not None:
                pr[p] = float(a_r)
    serve = dict(ps)
    ret = dict(pr)

    it, shift = 0, float("inf")
    for it in range(1, max_iter + 1):
        shift = 0.0
        for p in players:                         # serve, given current returns
            adj = sum(wt * (ret[o] - rbar) for o, wt in sv_items[p])
            v = (sv_num[p] + adj + prior_weight * ps[p]) / (sv_den[p] + prior_weight)
            shift = max(shift, abs(v - serve[p])); serve[p] = v
        for p in players:                         # returns, given current serves
            adj = sum(wt * (serve[o] - tour_avg) for o, wt in rt_items[p])
            v = (rt_num[p] + adj + prior_weight * pr[p]) / (rt_den[p] + prior_weight)
            shift = max(shift, abs(v - ret[p])); ret[p] = v
        if shift < tol:
            break

    info = {"iters": it, "converged": shift < tol, "shift": shift,
            "players": len(players)}
    return serve, ret, sv_den, info


# ================================================= SYNTHETIC GENERATOR

def make_players(n, rng, serve_sd=0.030, ret_sd=0.025):
    """True abilities.  Spread chosen to match the real tour: M1 measured
    serve ability from 0.548 to 0.726 across 477 rated players."""
    out = []
    for i in range(n):
        out.append({
            "id": f"p{i}",
            "serve": TOUR_AVG + rng.gauss(0, serve_sd),
            "ret": (1 - TOUR_AVG) + rng.gauss(0, ret_sd),
        })
    return out


def generate(players, n_matches, rng, days=1460, assortative=True, k=8,
             best_of=3):
    """Simulate matches from true abilities, in chronological order.

    assortative=True pairs players of similar strength, which is what real
    draws do (seeds meet seeds late).  It is also the condition under which
    the naive unadjusted estimator is biased -- with random pairing the bias
    largely averages out and the test proves nothing.
    """
    import tennis_sim as ts

    # Overall ability is serve + return.  Sorting on serve - return would
    # instead pair big servers against weak returners, which inflates their
    # observed serve % and biases the test in the opposite direction.
    order = sorted(range(len(players)),
                   key=lambda i: players[i]["serve"] + players[i]["ret"])
    pos = {players[i]["id"]: r for r, i in enumerate(order)}

    out = []
    for _ in range(n_matches):
        i = rng.randrange(len(players))
        if assortative:
            r = pos[players[i]["id"]]
            lo, hi = max(0, r - k), min(len(players) - 1, r + k)
            j = order[rng.randint(lo, hi)]
            if j == i:
                j = order[(r + 1) % len(players)]
        else:
            j = rng.randrange(len(players))
            while j == i:
                j = rng.randrange(len(players))

        A, B = players[i], players[j]
        pa = TOUR_AVG + (A["serve"] - TOUR_AVG) - (B["ret"] - (1 - TOUR_AVG))
        pb = TOUR_AVG + (B["serve"] - TOUR_AVG) - (A["ret"] - (1 - TOUR_AVG))

        pA = ts.Player(A["id"], 0.0, 0.0, form_sd=0.0)
        pB = ts.Player(B["id"], 0.0, 0.0, form_sd=0.0)
        ctx = ts.Ctx(players=(pA, pB), base_p=(pa, pb))
        st = ts.sim_match(ctx, ts.static_p, best_of=best_of, rng=rng)

        # recover per-side service points from the simulated match
        a_svpt, a_won, b_svpt, b_won = _split(st, pa, pb, rng)
        out.append((rng.randrange(days), A["id"], B["id"],
                    a_svpt, a_won, b_svpt, b_won))
    out.sort(key=lambda r: r[0])
    return out


def _split(st, pa, pb, rng):
    """Service points per side.  sim_match tracks totals, not per-server
    counts, so split the match's points by the alternating-service structure
    and redraw outcomes at the true rates -- the counts are what ratings need."""
    total = st.points_played
    a_svpt = total // 2 + (total % 2)
    b_svpt = total - a_svpt
    a_won = sum(rng.random() < pa for _ in range(a_svpt))
    b_won = sum(rng.random() < pb for _ in range(b_svpt))
    return a_svpt, a_won, b_svpt, b_won


# ============================================================== GATES

def fit_line(xs, ys):
    """Least-squares slope/intercept of y on x, plus RMSE about y=x."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx else 0.0
    rmse = (sum((y - x) ** 2 for x, y in zip(xs, ys)) / n) ** 0.5
    return slope, my - slope * mx, rmse


def gate_recovery(rng, n_players=120, n_matches=9000):
    """Do we get the true abilities back?  Naive vs opponent-adjusted."""
    players = make_players(n_players, rng)
    matches = generate(players, n_matches, rng, assortative=True)
    truth = {p["id"]: p for p in players}

    # Shrinkage biases slope toward 0 by design, so comparing a shrunk
    # estimator against 1.0 conflates two effects.  The third row runs
    # near-unshrunk: if the opponent adjustment is truly unbiased, its
    # slope must come back at ~1.0.
    end = max(m[0] for m in matches)
    rows = {}

    def score(getter):
        est = [(truth[p]["serve"], getter(p)) for p in truth if den_ok(p)]
        return fit_line([x for x, _ in est], [y for _, y in est]) + (len(est),)

    for label, adjust in (("stream naive  ", False), ("stream adjust ", True)):
        R = Ratings(adjust=adjust, prior_weight=20)
        for m in matches:
            R.observe(*m)
        den_ok = lambda p: R.S[p][1].den > 2000
        rows[label] = score(lambda p: R.serve(p, end))

    # huge half-life => decay off, so this isolates the iteration itself
    serve, ret, den, info = fit_iterative(matches, asof=end, half_life=10 ** 9,
                                          prior_weight=20)
    den_ok = lambda p: den.get(p, 0) > 2000
    rows["iterative     "] = score(lambda p: serve[p])
    return rows, matches, info


def gate_leakage(rng, n_players=40, n_matches=1200):
    """A rating used to price match k must not move when match k+1 exists."""
    players = make_players(n_players, rng)
    matches = generate(players, n_matches, rng)
    cut = len(matches) // 2
    t_cut, a_cut, b_cut = matches[cut][0], matches[cut][1], matches[cut][2]

    # Reading at t_cut after streaming past it would be a backwards read,
    # which the monotonicity guard rejects.  Capture at the moment match
    # `cut` is about to be priced, in both runs.
    def asof(stream, stop):
        R = Ratings()
        for i, m in enumerate(stream):
            if i == stop:
                break
            R.observe(*m)
        return R.serve(a_cut, t_cut), R.ret(b_cut, t_cut)

    return asof(matches[:cut], cut), asof(matches, cut)


if __name__ == "__main__":
    import random
    import sys
    rng = random.Random(7)
    ok = True

    print("1. RECOVERY -- estimated vs true serve ability")
    print("   (slope 1.000 = unbiased; <1 = shrunk toward the mean)")
    rows, matches, info = gate_recovery(rng)
    for label, (slope, icept, rmse, n) in rows.items():
        print(f"   {label} slope {slope:.3f}   rmse {rmse:.5f}   ({n} players)")
    it_slope, _, it_rmse, _ = rows["iterative     "]
    unbiased = abs(1 - it_slope) < 0.08
    better = it_rmse < rows["stream naive  "][2]
    ok &= unbiased and better and info["converged"]
    print(f"   converged in {info['iters']} sweeps, max shift {info['shift']:.2e}"
          f"   {'ok' if info['converged'] else 'FAIL -- hit the cap'}")
    print(f"   iterative slope within 0.08 of 1.0        "
          f"{'ok' if unbiased else 'FAIL'}")
    print(f"   iterative beats naive on rmse             "
          f"{'ok' if better else 'FAIL'}")

    print("\n2. NO LEAKAGE -- as-of rating with and without future matches")
    (s1, r1), (s2, r2) = gate_leakage(rng)
    d = max(abs(s1 - s2), abs(r1 - r2))
    ok &= d == 0.0
    print(f"   truncated  serve {s1:.10f}  return {r1:.10f}")
    print(f"   full       serve {s2:.10f}  return {r2:.10f}")
    print(f"   max drift  {d:.2e}   {'ok' if d == 0.0 else 'FAIL'}")

    print("\n3. VECTORISED == REFERENCE -- the numpy fit against the plain loop")
    end = max(m[0] for m in matches)
    ages = {m[1]: end - 365 * (18 + (hash(m[1]) % 20)) for m in matches}
    hlf = age_half_life(270, end, ages, 0.7, 0.85)
    worst = 0.0
    own = {m[1]: (0.60 + (hash(m[1]) % 7) / 100, 0.36 + (hash(m[1]) % 5) / 100)
           for m in matches[::7]}                  # a player-specific prior
    for kw in ({"half_life": 10 ** 9, "prior_weight": 20},
               {"half_life": 270, "prior_weight": 150, "half_life_fn": hlf},
               {"half_life": 270, "prior_weight": 150, "priors": own}):
        s_a, r_a, d_a, i_a = fit_iterative(matches, asof=end, **kw)
        s_b, r_b, d_b, i_b = fit_iterative_reference(matches, asof=end, **kw)
        worst = max(worst, max(abs(s_a[p] - s_b[p]) for p in s_a),
                    max(abs(r_a[p] - r_b[p]) for p in r_a),
                    max(abs(d_a[p] - d_b[p]) for p in d_a))
        ok &= i_a["converged"] == i_b["converged"]
    ok &= worst < 1e-9
    print(f"   max |diff| over serve, return, points {worst:.2e}   "
          f"{'ok' if worst < 1e-9 else 'FAIL'}")

    print("\n" + ("M2 GATE PASS" if ok else "M2 GATE FAIL"))
    sys.exit(0 if ok else 1)
