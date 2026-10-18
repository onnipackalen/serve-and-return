"""
Per-player weights, derived from data rather than chosen by hand.

    python3 weights.py                 derive and cache all of them
    python3 weights.py Alcaraz         inspect one player

Replaces two hand-picked constants:

  form_sd        was a single tour-wide 0.035 for everybody.  Now each
                 player gets their own, measured as OVERDISPERSION -- how
                 much their match-to-match serve % varies beyond what
                 binomial noise alone explains.  A player whose serve
                 collapses on bad days genuinely is a wider distribution.

  SURFACE_SHRINK was a flat 4000 pseudo-points for everybody, which gave a
                 clay specialist and a journeyman the same surface weight.
                 Now each player-surface pair gets an empirical-Bayes
                 weight from how large and how well-measured their own
                 surface deviation is.

THE RULE, and it is not negotiable: nothing here is a raw per-player fit.
Eleven free parameters against a few thousand points per player produces
confident nonsense.  Every value below is a population estimate plus a
deviation shrunk by that player's sample size, so a thin-data player
collapses back to the tour-wide number automatically.
"""

import json
import math
import os
import sys
from collections import defaultdict

from load import load, tour_avg
from ratings import fit_iterative, TOUR_AVG
from load import BIRTHDAYS
from fit import to_day, name_map

CACHE = os.path.join(os.path.dirname(__file__) or ".", "weights.json")

# Fitted values live in fitted_params.json so the sweep, the backtest and
# pricing cannot drift apart.  half_life was 730 by assumption until the
# sweep measured 270 (paired t = +2.80).
try:
    with open(os.path.join(os.path.dirname(__file__) or ".",
                           "fitted_params.json")) as _fh:
        _FP = json.load(_fh)
except OSError:
    _FP = {}
HALF_LIFE = _FP.get("half_life_days", 270)

# Surface ratings need a LONGER window than overall ratings.  data_plan.md
# called this: surface data is thin (a player may get 12 clay matches a
# year), so you trade recency for sample size.  Dropping the overall
# half-life to 270 took clay and grass weights from 669 players to 413 and
# left only Hard with enough well-measured players to estimate tau.  The
# contrast keeps its own, longer, half-life.
SURFACE_HALF_LIFE = float(os.environ.get("TENNIS_SURFACE_HL")
                          or _FP.get("surface_half_life_days", 1095))
PRIOR_WEIGHT = float(os.environ.get("TENNIS_PRIOR_WEIGHT") or _FP.get("prior_weight", 150))
# What the 270-day rating is shrunk toward: "tour" (the tour average) or
# "own" (the player's own long-window rating, so a layoff pulls a player
# toward who they were rather than toward the middle of the tour).
# Measured 2026-09-14 with tools/knobsweep.py run prior_mode own.
PRIOR_MODE = os.environ.get("TENNIS_PRIOR_MODE") or _FP.get("prior_mode", "tour")
# PRIOR_MODE "age": how much of the OWN prior survives at the young and old
# ends of a career, the rest going to the tour average.  The ramp between
# them is ratings.age_multiplier, which is PINNED TO 1.0 THROUGH THE PRIME,
# so this knob only ever damps the ends: (1, 1) is exactly "own" -- verified
# to 0.0, and the baseline the sweep runs first (rule 31) -- while (0, 0)
# is the tour average at both ends and still the own prior at 28.
PRIOR_AGE = tuple(float(x) for x in
                  (os.environ.get("TENNIS_PRIOR_AGE")
                   or _FP.get("prior_age", "1,1")).split(","))
YEARS = _FP.get("train_years", 5)
TOUR_FORM_SD = 0.035        # fitted tour-wide in backtest.py
FORM_PRIOR_MATCHES = 25     # matches before a player's own spread outweighs it
MIN_MATCHES = 8
CONTRAST_PW = 20            # near-unshrunk, for the surface contrast only
# Window for the long-memory quantities (surface contrast, form volatility,
# the long-window overall rating).  Was LONG_YEARS in backtest.py while
# build() here loaded ten years and windowed nothing -- two derivations of
# the same weights, and they drifted (rule 19).  One constant, one place.
LONG_YEARS = int(os.environ.get("TENNIS_LONG_YEARS") or _FP.get("long_years", 12))
# How far a player's CURRENT rating may carry onto their long-window
# surface rating.  The surface contrast is measured on a 1,095-day
# half-life; substituting it for the current rating outright discards the
# fitted 270-day recency and measured WORSE than tour-wide (t = -3.14).
# Adding the recent shift back on top flipped that to t = +4.54.  The
# backtest has always done this; live pricing did not until 2026-09-11.
CARRY_CAP = float(os.environ.get("TENNIS_CARRY_CAP") or _FP.get("carry_cap", 0.05))
# The TENNIS_* environment overrides above (and TENNIS_REFIT_DAYS in
# backtest.py, TENNIS_AGE_KNOTS in ratings.py) exist for tools/knobsweep.py,
# which runs one walk-forward per value in a subprocess and pairs them.


# ------------------------------------------------------- RECORD LAYOUT
#
# One tuple shape for every fit, so build() and backtest.walk_forward cannot
# feed the estimator different rows.  The first seven fields are exactly
# what ratings.fit_iterative consumes; the rest let the stage fits, the
# surface split and the harness read the same row.
R_DAY, R_W, R_L, R_WSV, R_WWON, R_LSV, R_LWON = range(7)
R_BO, R_SURF = 7, 8
R_W1IN, R_W1WON, R_W2WON, R_L1IN, R_L1WON, R_L2WON = range(9, 15)


def rich(m):
    """A load.Match -> the shared record tuple, or None if it has no stats."""
    if not m.has_stats:
        return None
    return (to_day(m.tourney_date), m.w_id, m.l_id, m.w_svpt, m.w_won,
            m.l_svpt, m.l_won, m.best_of, m.surface,
            m.w_1in, m.w_1won, m.w_2won, m.l_1in, m.l_1won, m.l_2won)


def window(recs, asof_day, years):
    """The records inside (asof - years, asof], which is the only way a
    training window is ever cut here.  Nothing after asof can pass."""
    lo = asof_day - 365 * years
    return [r for r in recs if lo < r[R_DAY] <= asof_day]


def stage_records(recs):
    """{land, first, second}: 7-tuples for the three serve stages.

    serve in     svpt -> 1stIn
    won on 1st   1stIn -> 1stWon
    won on 2nd   (svpt - 1stIn) -> 2ndWon
    """
    out = {"land": [], "first": [], "second": []}
    for r in recs:
        w2d, l2d = r[R_WSV] - r[R_W1IN], r[R_LSV] - r[R_L1IN]
        if min(r[R_W1IN], r[R_L1IN], w2d, l2d) <= 0:
            continue
        t, a, b = r[R_DAY], r[R_W], r[R_L]
        out["land"].append((t, a, b, r[R_WSV], r[R_W1IN], r[R_LSV], r[R_L1IN]))
        out["first"].append((t, a, b, r[R_W1IN], r[R_W1WON],
                             r[R_L1IN], r[R_L1WON]))
        out["second"].append((t, a, b, w2d, r[R_W2WON], l2d, r[R_L2WON]))
    return out


# ------------------------------------------------------- FORM (overdispersion)

def derive_form_sd(matches, serve, ret, asof, half_life=HALF_LIFE,
                   tour_sd=TOUR_FORM_SD, tour_avg=TOUR_AVG):
    """Per-player match-day volatility, from excess variance.

    Residuals are taken against the OPPONENT-ADJUSTED expectation, not the
    player's own mean.  Measuring dispersion around a raw mean makes form_sd
    absorb schedule variety: a journeyman who faces both qualifiers and
    top-10 players looks volatile when it is their opponents varying, not
    them.  Expected rate for a match is serve[p] - ret[opp] + (1 - tour_avg).

    Residuals are then centred per player, which removes any constant error
    in that player's rating and leaves genuine match-to-match movement.

    If ability were fixed, Var(residual) would be exactly binomial,
    p(1-p)/n.  Anything above that is real.
    """
    rbar = 1 - tour_avg
    obs = defaultdict(list)

    def add(p, opp, won, n, w):
        if n < 20 or p not in serve or opp not in ret:
            return
        exp = min(max(serve[p] - ret[opp] + rbar, 0.05), 0.95)
        obs[p].append((w, won / n - exp, exp, n))

    for t, a_, b_, asv, awn, bsv, bwn in matches:
        w = 0.5 ** ((asof - t) / half_life)
        add(a_, b_, awn, asv, w)
        add(b_, a_, bwn, bsv, w)

    out = {}
    for p, rows in obs.items():
        if len(rows) < MIN_MATCHES:
            continue
        sw = sum(w for w, *_ in rows)
        mu = sum(w * r for w, r, _, _ in rows) / sw          # centre per player
        var_obs = sum(w * (r - mu) ** 2 for w, r, _, _ in rows) / sw
        var_bin = sum(w * e * (1 - e) / n for w, _, e, n in rows) / sw
        excess = max(0.0, var_obs - var_bin)
        m = len(rows)
        var = (m * excess + FORM_PRIOR_MATCHES * tour_sd ** 2) / \
              (m + FORM_PRIOR_MATCHES)
        out[p] = {"form_sd": math.sqrt(var), "raw_sd": math.sqrt(excess),
                  "matches": m, "bias": mu}
    return out


# ------------------------------------------- SURFACE (empirical Bayes weight)

def effective_n(per_surf_records, asof, half_life=HALF_LIFE):
    """Decay-adjusted sample size, per player per surface.

    A weighted mean's variance is NOT p(1-p)/sum(w*n) -- exponential decay
    concentrates weight on recent matches, so the effective sample is
    smaller than the weighted total.  Using the wrong one understates the
    noise floor and makes real signal look like noise (or the reverse).

        n_eff = (sum w*n)^2 / sum w^2*n
    """
    out = {}
    for surf, rows in per_surf_records.items():
        s1, s2 = defaultdict(float), defaultdict(float)
        for t, a_, b_, asv, awn, bsv, bwn in rows:
            w = 0.5 ** ((asof - t) / half_life)
            s1[a_] += w * asv; s2[a_] += w * w * asv
            s1[b_] += w * bsv; s2[b_] += w * w * bsv
        out[surf] = {p: (s1[p] ** 2 / s2[p]) if s2[p] > 0 else 0.0 for p in s1}
    return out


def _combine(x1, v1, x2, v2, tau2):
    """Posterior mean of the true surface ability.

    Two independent estimates: on-surface (x1, var v1) and off-surface
    (x2, var v2), whose true values differ by delta ~ N(mu, tau^2).  The
    off-surface estimate therefore acts as a prior with variance v2 + tau^2:

        ability = [x1/v1 + x2/(v2+tau^2)] / [1/v1 + 1/(v2+tau^2)]

    tau^2 -> 0 means surfaces are interchangeable and everything collapses
    to the pooled estimate.  tau^2 -> inf means the off-surface record tells
    you nothing and only on-surface matches count.  Both limits are correct,
    which is what a hand-picked constant could never guarantee.
    """
    p1, p2 = 1.0 / v1, 1.0 / (v2 + tau2)
    return (x1 * p1 + x2 * p2) / (p1 + p2), p1 / (p1 + p2)


def derive_surface_weights(per_surface, per_other, neff_surf, neff_other,
                           tau_min_n=3000):
    """Per-player, per-surface ability, empirical Bayes.

    Deviations are (this surface) minus (ALL OTHER surfaces) -- never minus
    the overall rating, which CONTAINS the surface matches.  Correlated
    estimates overstate the sampling variance and drive the estimated
    population spread to exactly zero, which is what happened on the first
    attempt.  Two disjoint samples give Var(d) = v1 + v2 honestly.

    tau^2 is estimated only from players with enough data on BOTH sides for
    the signal to clear the noise floor, then applied to everyone.  It is a
    population constant, so it should be measured where it is measurable.
    """
    out, stats = {}, {}
    for surf, book in per_surface.items():
        other = per_other.get(surf)
        if not other:
            continue
        n1a, n2a = neff_surf.get(surf, {}), neff_other.get(surf, {})

        def var(x, n):
            return max(x * (1 - x) / n, 1e-9) if n > 0 else 1e9

        strong = [p for p in book["serve"]
                  if n1a.get(p, 0) > tau_min_n and n2a.get(p, 0) > tau_min_n
                  and p in other["serve"]]
        if len(strong) < 12:
            continue
        stats[surf] = {"n_strong": len(strong)}
        tau2 = {}
        for q in ("serve", "ret"):
            ds = [book[q][p] - other[q][p] for p in strong]
            vs = [var(book[q][p], n1a[p]) + var(other[q][p], n2a[p])
                  for p in strong]
            mu = sum(ds) / len(ds)
            var_obs = sum((d - mu) ** 2 for d in ds) / len(ds)
            tau2[q] = max(var_obs - sum(vs) / len(vs), 1e-8)
            stats[surf][q] = {"tau": math.sqrt(tau2[q]), "mu": mu}

        for p in book["serve"]:
            if p not in other["serve"]:
                continue
            n1, n2 = n1a.get(p, 0.0), n2a.get(p, 0.0)
            if n1 <= 0 or n2 <= 0:
                continue
            e = {"n": n1, "n_off": n2}
            for q in ("serve", "ret"):
                x1, x2 = book[q][p], other[q][p]
                mu = stats[surf][q]["mu"]
                val, w = _combine(x1, var(x1, n1), x2 + mu,
                                  var(x2, n2), tau2[q])
                e[q] = val
                e[f"w_{q}"] = w
                e[f"d_{q}"] = val - x2
            out.setdefault(p, {})[surf] = e
    return out, stats


def _priors(lo_s, lo_r, asof_day):
    """pid -> (serve, return) level the 270-day rating is shrunk toward.

    "tour" (until 2026-09-14): None, so every player is shrunk toward the
    tour average -- the assumption that a player we have little recent
    evidence about is average, which is false about everyone on tour.

    "own" (2026-09-14): the player's own LONG-window rating, the 12-year fit
    that already exists for the surface carry-over.  A player back from a
    layoff is pulled toward who they were instead of toward the middle of
    the tour; worth -0.00091 at a paired t of +2.92.

    "age": the same, blended back toward the tour average at the ends of a
    career.  The own prior made the age curve LARGER (youngest minus oldest
    +0.075 -> +0.085), and the mechanism is plain: the 12-year window holds
    a declining player's peak, so the prior over-states them, and it holds a
    rising player's junior years, so it under-states them.  The prior only
    bites where the 270-day window is thin -- arriving, winding down, or
    back from an injury -- which is exactly where a stale level does most
    damage.  The blend is the SAME piecewise-linear age ramp the half-life
    uses (ratings.age_multiplier, AGE_KNOTS), because "when is a player
    young, prime or old" must have one answer in this project (rule 19).

    A player with no birthday keeps the own prior, the same fallback the
    age-dependent half-life makes.  PRIOR_AGE (1, 1) reproduces "own" to
    0.0; the ramp is pinned at the prime, so no setting turns this into
    "tour" for everyone.
    """
    if PRIOR_MODE == "tour":
        return None
    own = {p: (lo_s[p], lo_r[p]) for p in lo_s}
    if PRIOR_MODE != "age":
        return own
    from ratings import age_multiplier
    from load import birthdays as _birthdays
    bdays = _birthdays()
    w_young, w_old = PRIOR_AGE
    rbar = 1.0 - TOUR_AVG
    out = {}
    for p, (a_s, a_r) in own.items():
        b = bdays.get(p)
        age = None if b is None else (asof_day - b) / 365.25
        w = age_multiplier(age, w_young, w_old)
        out[p] = (w * a_s + (1.0 - w) * TOUR_AVG,
                  w * a_r + (1.0 - w) * rbar)
    return out


# ----------------------------------------------------------------- BUILD

def derive(recs, asof_day, supp=(), half_life=None, prior_weight=None,
           hlf=None, years=None, long_years=None, verbose=False):
    """Every per-player quantity pricing reads, from record tuples alone.

    THE ONE DERIVATION.  weights.build() calls this for the weights.json the
    CLI reads; backtest._fit_block calls it at every refit of the walk-forward
    harness.  Until 2026-09-11 the harness had its own copy, and the two had
    drifted in four places -- the form half-life, the surface window, the
    three-stage serve and the carry-over of recent form onto the surface
    rating -- so the harness was fitting form_scale and calibration against
    numbers production never produced.  Rule 19: two derivations of one
    quantity WILL drift.  Now there is one.

    recs   rich tuples (see rich()) of MAIN-TOUR matches, any span -- the
           windows are cut HERE so callers cannot cut them differently
    supp   7-tuples of qualifying / Challenger matches; they join the main
           rating fit only
    hlf    pid -> half-life for this as-of day (ratings.age_half_life), or
           None for the single global half-life
    """
    years = YEARS if years is None else years
    long_years = LONG_YEARS if long_years is None else long_years
    half_life = HALF_LIFE if half_life is None else half_life
    prior_weight = PRIOR_WEIGHT if prior_weight is None else prior_weight

    main = window(recs, asof_day, years)
    long_ = window(recs, asof_day, long_years)
    main7 = [r[:7] for r in main]
    long7 = [r[:7] for r in long_]
    supp_w = window(supp, asof_day, years) if supp else []
    supp7 = [r[:7] for r in supp_w]
    if verbose:
        print(f"fitting {len(main7):,} matches in the last {years} years "
              f"+ {len(supp7):,} qual/challenger, as of day {asof_day} ...")

    # MAIN RATING: the 270-day half-life, age-decayed per player, with the
    # QUALIFYING AND CHALLENGER SUPPLEMENT.  49 files the loader never
    # opened: 3.2x the main-tour volume, and for the 568 players the
    # confidence bands call thin they carry 28x more service points than
    # the tour does.  Measured -0.00388 at a paired t of +4.13
    # (tools/qcthin.py) -- but only once MIN_PTS was lowered so the thin
    # players it is FOR entered the common set (rule 13).
    #
    # It joins the MAIN rating only.  Surface contrast and form volatility
    # keep their main-draw history: those are stable traits on long
    # windows, and mixing levels into them is the substitution mistake of
    # rule 8.
    fit_recs = sorted(main7 + supp7, key=lambda r: r[0]) if supp7 else main7

    # LONG-WINDOW OVERALL RATING, fitted first: the surface ability is
    # carried forward from it (Book.rating, CARRY_CAP), and with
    # PRIOR_MODE "own" it is also the level the 270-day rating is shrunk
    # toward -- the player's own history instead of the tour average.
    lo_s, lo_r, _lo_d, i3 = fit_iterative(long7, asof=asof_day,
                                          half_life=SURFACE_HALF_LIFE,
                                          prior_weight=CONTRAST_PW)
    priors = _priors(lo_s, lo_r, asof_day)
    s, r_, d, info = fit_iterative(fit_recs, asof=asof_day,
                                   half_life=half_life,
                                   prior_weight=prior_weight,
                                   half_life_fn=hlf, priors=priors)
    conv = [info["converged"], i3["converged"]]

    # THREE-STAGE SERVE.  The archive records how a service point got where
    # it did -- serve in, won on the first, won on the second -- and the
    # model always collapsed that to one number.  Recombining three
    # separately opponent-adjusted stages is worth -0.00195 nats at a
    # paired t of +12.32 (tools/twostage.py --walk), because a returner can
    # be differentially good against second serves and a single additive
    # adjustment cannot express that.  SAME RECORDS as the main fit -- the
    # supplement included -- same half-life, same prior; only the numerator
    # and denominator of each stage differ.  price.serve_probs composes
    # `stages + (single-number matchup - single-number base)`, and that
    # isolates the decomposition only if both fits saw the same matches:
    # fitted on the main tour alone, every player rated from Challenger
    # points was priced at the tour average, +0.0068 nats of damage.
    stages = {}
    stage_src = main + [r for r in supp_w if len(r) > R_L2WON]
    for name, rs in stage_records(stage_src).items():
        if len(rs) < 400:
            continue
        avg = sum(r[4] + r[6] for r in rs) / sum(r[3] + r[5] for r in rs)
        ss, rr, dd, inf = fit_iterative(rs, asof=asof_day,
                                        half_life=half_life,
                                        prior_weight=prior_weight,
                                        tour_avg=avg, half_life_fn=hlf)
        stages[name] = {"serve": ss, "ret": rr, "den": dd, "avg": avg,
                        "converged": inf["converged"]}
        conv.append(inf["converged"])
    if verbose and stages:
        print("  three-stage serve: " + ", ".join(
            f"{k} {v['avg']:.4f}" for k, v in sorted(stages.items())))

    # SURFACE CONTRAST, on the LONG window and its own 1,095-day half-life.
    # Surface data is thin -- a player may get 12 clay matches a year -- so
    # it trades recency for sample size; dropping the overall half-life to
    # 270 took clay and grass weights from 669 players to 413.  NOT
    # age-decayed: it measures a stable trait, and shortening a long-window
    # quantity to chase current form is the mistake this project already
    # made once (rule 8).
    per_surf = defaultdict(list)
    for r in long_:
        per_surf[r[R_SURF]].append(r[:7])
    per_book, per_other = {}, {}
    for surf, rs in per_surf.items():
        if len(rs) < 400:
            continue
        rest = [r for sf, xs in per_surf.items() if sf != surf for r in xs]
        if len(rest) < 400:
            continue
        # NEAR-UNSHRUNK on purpose: prior_weight=300 compresses the
        # deviations while the noise floor stays unshrunk, which drives the
        # estimated population spread to zero.  Shrinkage is applied
        # afterwards, by _combine, where it is accounted for.
        ss, rr, dd, i1 = fit_iterative(rs, asof=asof_day,
                                       half_life=SURFACE_HALF_LIFE,
                                       prior_weight=CONTRAST_PW,
                                       tour_avg=tour_avg(surf))
        os_, orr, od, i2 = fit_iterative(rest, asof=asof_day,
                                         half_life=SURFACE_HALF_LIFE,
                                         prior_weight=CONTRAST_PW)
        per_book[surf] = {"serve": ss, "ret": rr, "den": dd}
        per_other[surf] = {"serve": os_, "ret": orr, "den": od}
        conv += [i1["converged"], i2["converged"]]
    other_recs = {sf: [r for g, rs in per_surf.items() if g != sf for r in rs]
                  for sf in per_book}
    neff_s = effective_n(per_surf, asof_day, SURFACE_HALF_LIFE)
    neff_o = effective_n(other_recs, asof_day, SURFACE_HALF_LIFE)
    surfw, tau = derive_surface_weights(per_book, per_other, neff_s, neff_o)

    # (the long-window overall rating was fitted above, before the main
    # fit; the surface rating is long-window ability + surface contrast, and
    # the current 270-day rating minus the long-window one is the recent
    # form shift added back on top -- see Book.rating and CARRY_CAP)

    # FORM VOLATILITY, also on the long window and long half-life.  It is a
    # stable trait; measured on the short window the per-player model
    # scored WORSE than tour-wide (0.62565 vs 0.62273) -- an artefact of
    # starving a variance estimate, not a real regression.  form_scale was
    # fitted against THIS derivation, so this is the one that must ship.
    form = derive_form_sd(long7, s, r_, asof_day, SURFACE_HALF_LIFE)

    if verbose:
        print(f"derived form_sd for {len(form):,} players, "
              f"surface weights for {len(surfw):,}"
              + ("" if all(conv) else
                 f"   ! {conv.count(False)} of {len(conv)} fits did NOT "
                 "converge"))
    return {"asof": asof_day, "form": form, "surface": surfw,
            "tau": tau, "tour_form_sd": TOUR_FORM_SD,
            "half_life": half_life, "prior_weight": prior_weight,
            "prior_mode": PRIOR_MODE, "prior_age": list(PRIOR_AGE),
            "years": years, "long_years": long_years,
            # the overall (all-surface) ratings, so price.py needs no second fit
            "overall": {"serve": s, "ret": r_, "den": d,
                        "converged": info["converged"]},
            "long": {"serve": lo_s, "ret": lo_r},
            # three-stage serve; price.Book.stage_serve recombines them
            "stages": stages,
            "converged": all(conv)}


def build(asof_day, years=None, half_life=None, prior_weight=None,
          verbose=True, path=None):
    """Load the archive, derive every weight as of one day, write the file.

    Loads enough history for the long window and hands derive() everything;
    the windows are cut there, exactly as the backtest cuts them.
    """
    import datetime as dt
    years = YEARS if years is None else years
    half_life = HALF_LIFE if half_life is None else half_life
    prior_weight = PRIOR_WEIGHT if prior_weight is None else prior_weight
    y1 = (dt.date(2000, 1, 1) + dt.timedelta(days=asof_day)).year
    y0 = max(1990, y1 - max(years, LONG_YEARS) - 1)
    from load import require_data
    require_data("tennis.py fit")
    raw, _ = load(y0, y1)
    recs = [r for r in (rich(m) for m in raw) if r is not None]
    supp = []
    if _FP.get("qc_supplement", True):
        from load import qc_records
        supp = qc_records(y0, y1, k=_FP.get("qc_level_k", 1.0))
    from ratings import age_half_life
    hlf = age_half_life(half_life, asof_day, BIRTHDAYS,
                        _FP.get("age_m_young", 1.0), _FP.get("age_m_old", 1.0))
    data = derive(recs, asof_day, supp=supp, half_life=half_life,
                  prior_weight=prior_weight, hlf=hlf, years=years,
                  verbose=verbose)
    data["names"] = name_map(y0, y1)
    # Never cache an empty fit. Writing one is worse than crashing: the file
    # is structurally valid and marked converged, so every later command reads
    # it happily and the absent archive stays invisible forever.
    if not data.get("overall", {}).get("serve"):
        from load import NoData, DATA_DIR
        raise NoData(
            "fit produced zero rated players, so nothing was written.\n\n"
            f"  looked in : {DATA_DIR}\n"
            "  This usually means the match archive is missing -- see NOTICE\n"
            "  and the Setup section of README.md.")
    with open(path or CACHE, "w") as fh:
        json.dump(data, fh)
    if verbose:
        print("\npopulation spread of REAL surface effects (tau)")
        for k, e in sorted(data["tau"].items()):
            print(f"  {k:<8} serve tau {e['serve']['tau']:.4f} "
                  f"(mean {e['serve']['mu']:+.4f})   "
                  f"return tau {e['ret']['tau']:.4f} "
                  f"(mean {e['ret']['mu']:+.4f})   "
                  f"[{e['n_strong']} well-measured players]")
    return data


def load_weights(path=None):
    path = path or CACHE
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


if __name__ == "__main__":
    import datetime as dt
    today = (dt.date.today() - dt.date(2000, 1, 1)).days
    q = [a for a in sys.argv[1:] if not a.startswith("-")]
    w = load_weights()
    if w is None or "--rebuild" in sys.argv:
        w = build(today)

    if q:
        import players
        query = " ".join(q)
        prom = (lambda pid: w["form"].get(pid, {}).get("matches", 0) * 1000.0
                + w["overall"]["den"].get(pid, 0.0))
        hits = players.search(w["names"], query, prom)
        if not hits:
            near = players.suggest_line(
                players.nearest(w["names"], query, prom))
            sys.exit(f"no player matching {query!r}"
                     + (f"  --  did you mean: {near}?" if near else ""))
        p, n = hits[0]["id"], hits[0]["name"]
        if len(hits) > 1 and players.ambiguous(hits):
            print(f"(also matched: "
                  f"{', '.join(h['name'] for h in hits[1:4])})")
        f = w["form"].get(p)
        print(f"\n{n}")
        if f:
            print(f"  form_sd      {f['form_sd']:.4f}   "
                  f"(own estimate {f['raw_sd']:.4f} from {f['matches']} matches, "
                  f"tour-wide {w['tour_form_sd']:.3f})")
            v = "more volatile" if f["form_sd"] > w["tour_form_sd"] else "steadier"
            print(f"               -> {v} than the tour")
        for surf, e in sorted(w["surface"].get(p, {}).items(),
                              key=lambda kv: -kv[1]["n"]):
            print(f"  {surf:<8} n_eff {e['n']:>6,.0f}   "
                  f"serve {e['serve']:.4f} ({e['d_serve']:+.4f}, "
                  f"w={e['w_serve']:.0%})   "
                  f"return {e['ret']:.4f} ({e['d_ret']:+.4f}, "
                  f"w={e['w_ret']:.0%})")
    else:
        fs = sorted((v["form_sd"], k) for k, v in w["form"].items()
                    if v["matches"] >= 40)
        print(f"\nsteadiest servers (lowest form_sd, >=40 matches)")
        for sd, p in fs[:6]:
            print(f"  {w['names'].get(p,p):<26} {sd:.4f}")
        print(f"\nmost volatile")
        for sd, p in fs[-6:][::-1]:
            print(f"  {w['names'].get(p,p):<26} {sd:.4f}")
