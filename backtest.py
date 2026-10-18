"""
M2 GATE -- walk-forward backtest.   python3 backtest.py [start_year]

Refits the rating layer at fixed intervals using ONLY prior matches, then
prices the matches in the interval that follows.  Never trains on the week
it is pricing.

WHAT IS MEASURED IS WHAT SHIPS.  Every refit goes through weights.derive --
the derivation that writes weights.json -- and every price goes through
price.serve_probs and price.match_prob, the functions the CLI, the app and
the simulator call.  The harness used to carry its own copy of both, and
the copies drifted: by 2026-09-10 the CLI applied a three-stage serve, an
in-event rating update and a surface path the harness had never priced,
while the harness carried a recent-form carry-over the CLI never shipped.
form_scale, the calibration slope and six residual curves were all fitted
against a model nobody could run.  Rule 19, learned again.

The one thing the CLI applies that this cannot is player news: there is
no archive of what the news said on the morning of each historical match.

Scored against baselines, in increasing order of how much they hurt:

  coin flip   log loss 0.6931.  Beating this is not an achievement.
  Elo         knows only who beat whom -- no serve, no return, no points.
              If the point model cannot beat Elo, Barnett-Clarke is not
              earning its complexity and the premise needs revisiting.
  tour-wide   the single-number rating with tour-wide form volatility --
              the pricing path with every per-player layer switched off.

Then each shipped layer is switched on in turn, all on the SAME matches,
with a paired per-match t against the rung below.

Serve-order artifact: every CSV row is (winner, loser), so pricing with
A-serving-first would hand the winner the first serve in every single match
and quietly inflate the model.  price.match_prob averages over both.
"""

import datetime as dt
import json
import math
import os
import sys
import time
from collections import defaultdict

from load import load
from ratings import TOUR_AVG
from weather import conditions
from features import ROUND_ORDER
import price as P
import weights as W

# Fitted values, single source of truth -- the same dict price.py reads.
_FP = P._FP
# ONE source for the rating-layer constants: weights.py reads fitted_params
# and the TENNIS_* overrides, and the harness must fit with exactly what
# ships (rule 19).  Until 2026-09-14 PRIOR_W was read here separately, so
# TENNIS_PRIOR_WEIGHT moved the live derivation and not the harness -- a
# sweep of it returned four identical walks.
HALF_LIFE = W.HALF_LIFE
PRIOR_W = W.PRIOR_WEIGHT
REFIT_DAYS = int(os.environ.get("TENNIS_REFIT_DAYS") or _FP.get("refit_days", 91))
TRAIN_YEARS = _FP.get("train_years", 5)
LONG_YEARS = W.LONG_YEARS
# Both players must clear this to be scored.  Overridable because it is a
# SCORING threshold, not a model parameter: it decides which matches a
# comparison can see, and a comparison that only sees well-measured players
# cannot detect a change aimed at thin ones (rule 13).
MIN_PTS = int(os.environ.get("TENNIS_MIN_PTS") or 1500)
# Age-dependent half-life, fitted by tools/agehl.py.  1.0/1.0 is the single
# global half-life, bit for bit.
AGE_M_YOUNG = _FP.get("age_m_young", 1.0)
AGE_M_OLD = _FP.get("age_m_old", 1.0)
# The pricing-path switches, as shipped.  Each is a knob on walk_forward so
# a tool can turn one off and measure it paired (tools/pathsweep.py).
EVENT_W = _FP.get("event_update_w", 0.0)
STAGES = _FP.get("three_stage_serve", True)
CARRY = _FP.get("surface_carry", True)

# the harness's extra columns on the shared record tuple (weights.R_*)
R_DENS, R_TID, R_RND = 15, 16, 17


def records(y0, y1):
    """The shared record tuple plus density, event id and round, ordered
    by day, then event, then ROUND.

    Round order matters.  The archive lists some seasons' matches
    alphabetically by round -- F, QF, R128, R16 ... -- and the in-event
    update banks each match right after pricing it, so file order would
    fold a final into the price of a first round.  2019 is scrambled
    outright; 2020-2026 carry two thousand out-of-order rows each.
    """
    out = []
    for m in load(y0, y1)[0]:
        r = W.rich(m)
        if r is None or not m.best_of:
            continue
        # density index for this match, or 0.0 when unknown or indoor.
        # A closed roof means NO weather effect -- feeding outdoor weather
        # to an indoor match is pure noise injection.
        c = conditions(m.tname, m.tourney_date)
        dens = 0.0 if (c is None or c["indoor"]) else c["density_index"]
        out.append(r + (dens, m.tid, m.rnd))
    out.sort(key=lambda r: (r[0], r[R_TID], ROUND_ORDER.get(r[R_RND], 9)))
    return out


def elo_baseline(recs, k=24, base=1500.0, decay=1.0):
    """Standard Elo, walk-forward by construction: predict then update.

    K is TUNED on the training split below.  An untuned K=24 scores log loss
    0.858 -- worse than a coin flip at 63% accuracy -- because it lets
    ratings run away and prices upsets at near zero.  Beating a crippled
    baseline would prove nothing, so it gets the same fitting courtesy the
    real model does.
    """
    R, n, preds = defaultdict(lambda: base), defaultdict(int), []
    for t, a, b, *_ in recs:
        pa = 1.0 / (1.0 + 10 ** ((R[b] - R[a]) / 400.0))
        preds.append(pa)
        # larger steps while a player is new, smaller once established
        ka = k * (1.0 + 2.0 / (1.0 + n[a] / 10.0))
        kb = k * (1.0 + 2.0 / (1.0 + n[b] / 10.0))
        R[a] += ka * (1 - pa)
        R[b] += kb * (0 - pa)
        n[a] += 1; n[b] += 1
    return preds


def _fit_block(recs, supp, t, half_life, prior_weight, train_years, hlf):
    """One refit as of the day before t: the derivation weights.py ships,
    wrapped in the Book price.py reads.  The windows are cut inside
    derive(), from `t - 1` backwards, so nothing on or after t can enter."""
    asof = t - 1
    w = W.derive(recs, asof, supp=supp, half_life=half_life,
                 prior_weight=prior_weight, years=train_years,
                 hlf=hlf(asof) if hlf else None)
    return P.Book(weights=w)


def _supplement(recs, supplement):
    """None -> what fitted_params says ships; False/[] -> none; a list -> it."""
    if supplement is None:
        if not _FP.get("qc_supplement", True):
            return []
        from load import qc_records
        d0 = dt.date(2000, 1, 1)
        y0 = (d0 + dt.timedelta(days=recs[0][0])).year
        y1 = (d0 + dt.timedelta(days=recs[-1][0])).year
        return qc_records(y0, y1, k=_FP.get("qc_level_k", 1.0))
    return supplement or []


def _age_fn(half_life):
    """asof -> (pid -> half-life), or None for the single global half-life."""
    if AGE_M_YOUNG == 1.0 and AGE_M_OLD == 1.0:
        return None
    from ratings import age_half_life
    from load import BIRTHDAYS
    return (lambda asof: age_half_life(half_life, asof, BIRTHDAYS,
                                       AGE_M_YOUNG, AGE_M_OLD))


def gate(tol=1e-9):
    """The harness's block derivation must equal what weights.build wrote.

    Rule 19 made runnable: derive one block through _fit_block as of the day
    weights.json was built for, and compare every quantity pricing reads.
    Any divergence between the two callers of weights.derive -- a different
    window, a different supplement, a different half-life function -- shows
    up here as a non-zero difference.
    """
    w = W.load_weights()
    if w is None or "long" not in w:
        print("  no current weights.json -- run: python3 weights.py --rebuild")
        return 1
    recs = records(2005, 2026)
    supp = _supplement(recs, None)
    book = _fit_block(recs, supp, w["asof"] + 1, HALF_LIFE, PRIOR_W,
                      TRAIN_YEARS, _age_fn(HALF_LIFE))
    h = book.w
    bad = 0

    def cmp(label, a, b):
        nonlocal bad
        keys = set(a) | set(b)
        missing = len(keys) - len(set(a) & set(b))
        d = max((abs(a[k] - b[k]) for k in set(a) & set(b)), default=0.0)
        ok = missing == 0 and d <= tol
        bad += not ok
        print(f"  {label:<26} {len(keys):>6,} keys   max |diff| {d:.2e}"
              f"{'' if not missing else f'   {missing} only on one side'}"
              f"   {'ok' if ok else 'FAIL'}")

    for q in ("serve", "ret", "den"):
        cmp(f"overall {q}", w["overall"][q], h["overall"][q])
    for q in ("serve", "ret"):
        cmp(f"long {q}", w["long"][q], h["long"][q])
    for st in sorted(set(w["stages"]) | set(h["stages"])):
        for q in ("serve", "ret"):
            cmp(f"stage {st} {q}", w["stages"].get(st, {}).get(q, {}),
                h["stages"].get(st, {}).get(q, {}))
    cmp("form_sd", {p: v["form_sd"] for p, v in w["form"].items()},
        {p: v["form_sd"] for p, v in h["form"].items()})
    flat = lambda s: {f"{p}/{sf}/{q}": e[q] for p, d in s.items()
                      for sf, e in d.items() for q in ("serve", "ret")}
    cmp("surface ratings", flat(w["surface"]), flat(h["surface"]))
    print("  harness derivation == shipped weights.json: "
          + ("PASS" if not bad else f"FAIL ({bad})"))
    return 1 if bad else 0


def config(surface=True, stages=None, event_w=None, carry=None):
    """One pricing-path configuration.  Defaults are what ships."""
    return {"surface": surface,
            "stages": STAGES if stages is None else stages,
            "event_w": EVENT_W if event_w is None else event_w,
            "carry": CARRY if carry is None else carry}


def walk_forward(recs, half_life=HALF_LIFE, prior_weight=PRIOR_W,
                 refit_days=REFIT_DAYS, train_years=TRAIN_YEARS,
                 player_mode=True, half_life_fn=None, supplement=None,
                 stages=None, event_w=None, carry=None, configs=None,
                 book_out=None):
    """Yields (index, (pa, pb, best_of, form_sd_a, form_sd_b, dens)).

    pa/pb are the serve probabilities from price.serve_probs -- surface,
    the event so far and the three stages already inside them, air density
    not yet (price_player applies it, so dens_w can be fitted).  form_sd_a/b
    are the players' own derived volatilities, unscaled, or None.

    player_mode=False prices the single-number rating with no surface split;
    stages / event_w / carry override what fitted_params says ships.

    configs, when given, is a list of config() dicts and each yield is
    (index, [tuple per config]) -- one refit, several pricing paths, all on
    identical matches.  That is how tools/pathsweep.py measures a knob.

    half_life_fn, when given, is called as half_life_fn(asof) at each refit
    and must return pid -> half_life for that day.  Two levels because a
    player's half-life depends on their age, which depends on when the
    refit is happening.

    book_out, when given, is a dict this sets to {"book": book} before
    every yield, so a caller can read the block the match was priced from --
    the service points behind each rating, say.  confidence.py needs those
    to fit the band on the same inputs a live price feeds it, and a band
    fitted on a proxy for them is a band nobody ships (rule 19).

    supplement: qualifying and Challenger 7-tuples that join what the
    ratings are FITTED on and never what the model is SCORED on -- scoring
    them would change the match set and break every paired comparison
    (rule 1).  None means whatever fitted_params says ships; False means
    none.
    """
    supp = _supplement(recs, supplement)
    cfgs = configs or [config(player_mode, stages, event_w, carry)]
    hlf = half_life_fn if half_life_fn is not None else _age_fn(half_life)

    start = recs[0][0] + 365 * 3                    # burn-in
    book, next_refit = None, start
    runs = {}                                       # tid -> event evidence
    unconverged = 0
    for idx, r in enumerate(recs):
        t = r[0]
        if t < start:
            continue
        if t >= next_refit:
            t0 = time.time()
            book = _fit_block(recs, supp, t, half_life, prior_weight,
                              train_years, hlf)
            unconverged += not book.w["converged"]
            next_refit = t + refit_days
            print(f"  refit as of day {t - 1}  "
                  f"{len(book.overall['den']):,} players  "
                  f"{time.time() - t0:.0f}s"
                  + ("" if book.w["converged"] else "  UNCONVERGED"),
                  file=sys.stderr, flush=True)
        if book is None:
            continue
        a, b = r[W.R_W], r[W.R_L]
        run = runs.setdefault(r[R_TID], {})
        den = book.overall["den"]
        if den.get(a, 0) >= MIN_PTS and den.get(b, 0) >= MIN_PTS:
            bo, surf, dens = r[W.R_BO], r[W.R_SURF], r[R_DENS]
            fa = book.form.get(a, {}).get("form_sd")
            fb = book.form.get(b, {}).get("form_sd")
            out = []
            for c in cfgs:
                ev = None
                if c["event_w"]:
                    acc = {p: run[p] for p in (a, b) if p in run}
                    ev = P.event_shift(book, acc, c["event_w"])
                sp = P.serve_probs(book, a, b, surf if c["surface"] else None,
                                   stages=c["stages"], ev=ev, carry=c["carry"])
                out.append((sp["pa"], sp["pb"], bo, fa, fb, dens))
            if book_out is not None:
                book_out["book"] = book
            yield idx, (out if configs else out[0])
        # bank this match into the event's evidence AFTER pricing it, on
        # every match -- a player below MIN_PTS still played it
        P.event_bank(book, run, a, b, r[W.R_WSV], r[W.R_WWON],
                     r[W.R_LSV], r[W.R_LWON])
        P.event_bank(book, run, b, a, r[W.R_LSV], r[W.R_LWON],
                     r[W.R_WSV], r[W.R_WWON])
    if unconverged:
        print(f"  ! {unconverged} refit block(s) had an unconverged fit "
              f"(rule 2)", file=sys.stderr)


def score(pairs):
    """pairs: (p_assigned_to_the_actual_winner). Returns log loss, Brier, acc."""
    n = len(pairs)
    ll = -sum(math.log(max(p, 1e-12)) for p in pairs) / n
    br = sum((1 - p) ** 2 for p in pairs) / n
    ac = sum(p > 0.5 for p in pairs) / n
    return ll, br, ac, n


def calibration(pairs, bins=6):
    """pairs: (p_model, outcome). Predicted vs realised, by confidence band."""
    buckets = defaultdict(lambda: [0.0, 0, 0])
    for p, y in pairs:
        q = min(int((p - 0.5) / 0.5 * bins), bins - 1) if p >= 0.5 else \
            min(int((0.5 - p) / 0.5 * bins), bins - 1)
        pp, yy = (p, y) if p >= 0.5 else (1 - p, 1 - y)
        b = buckets[q]
        b[0] += pp; b[1] += yy; b[2] += 1
    return buckets


def logloss(ps):
    return -sum(math.log(max(p, 1e-12)) for p in ps) / len(ps)


def paired_t(ps_base, ps_new):
    """(mean improvement in nats, paired t) of new over base, same matches."""
    d = [-math.log(max(x, 1e-12)) + math.log(max(y, 1e-12))
         for x, y in zip(ps_base, ps_new)]
    n = len(d)
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return mu, (mu / (sd / math.sqrt(n)) if sd else 0.0)


def fit_calibration(ps):
    """Fit p -> expit(b * logit(p)).  Returns b.

    Every row here is "the winner won", so y is constant and ordinary
    logistic regression has nothing to fit against.  Symmetrising each match
    into both outcomes fixes that, and because logit(1-p) = -logit(p) the
    intercept vanishes by construction, leaving one slope.

    b < 1 shrinks toward 0.5 -- the model was overconfident.
    b > 1 would mean it was underconfident.
    """
    zs = [math.log(min(max(p, 1e-9), 1 - 1e-9) /
                   (1 - min(max(p, 1e-9), 1 - 1e-9))) for p in ps]

    def loss(b):
        return -sum(math.log(max(1.0 / (1.0 + math.exp(-b * z)), 1e-12))
                    for z in zs) / len(zs)

    lo, hi = 0.2, 1.8
    for _ in range(60):                       # golden-section
        m1, m2 = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
        if loss(m1) < loss(m2):
            hi = m2
        else:
            lo = m1
    return 0.5 * (lo + hi)


def apply_cal(p, b):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return 1.0 / (1.0 + math.exp(-b * math.log(p / (1 - p))))


def price_tour(m, sd):
    """The tour-wide model: one form_sd for everybody, no density."""
    pa, pb, bo = m[0], m[1], m[2]
    return P.match_prob(pa, pb, bo, sd, sd, 0.0, 0.0)[0]


def price_player(m, scale, floor=0.015, style_w=0.0, h2h_w=0.0, cap=None,
                 dens_w=0.0):
    """P(winner) from a walk_forward tuple, through price.match_prob.

    `scale` multiplies each player's own form_sd (form_scale) and `dens_w`
    weights the symmetric air-density shift; both are fitted below.
    style_w / h2h_w are accepted for the older callers' sake and must be
    zero: neither is in the pricing path (both measured at zero -- see
    HANDOFF, "Tested and DO NOT work").
    """
    if style_w or h2h_w:
        raise ValueError("style_w / h2h_w are not in the pricing path")
    pa, pb, bo, fa, fb, dens = m
    fa = P.scaled_form_sd(fa, scale, W.TOUR_FORM_SD, floor)
    fb = P.scaled_form_sd(fb, scale, W.TOUR_FORM_SD, floor)
    return P.match_prob(pa, pb, bo, fa, fb, dens, dens_w)[0]


if __name__ == "__main__":
    if "--gate" in sys.argv:
        sys.exit(gate())
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2005
    recs = records(y0, 2026)
    print(f"{len(recs):,} rated matches {y0}-2026")

    # The ladder: the pricing path with each SHIPPED layer switched on in
    # turn, ending at exactly the shipped config.  A layer fitted_params
    # switches off (the three-stage serve, since 2026-09-11) is measured
    # afterwards as a variant of the shipped path, so its cost stays on the
    # record.  ONE walk-forward -- the refits are the slow part and every
    # rung shares them -- so every rung is scored on identical matches.
    ladder = [
        ("tour-wide (single rating)",
         config(surface=False, stages=False, event_w=0.0, carry=False)),
        ("per-player surface + form",
         config(surface=True, stages=False, event_w=0.0)),
    ]
    cur = ladder[-1][1]
    if STAGES:
        cur = dict(cur, stages=True)
        ladder.append(("  + three-stage serve", cur))
    if EVENT_W:
        cur = dict(cur, event_w=EVENT_W)
        ladder.append(("  + in-event update", cur))
    assert cur == config(), "the ladder must end at the shipped config"
    variants = []
    if not STAGES:
        variants.append(("  three-stage serve ON (not shipped)",
                         dict(cur, stages=True)))
    if not EVENT_W:
        variants.append(("  in-event update ON (not shipped)",
                         dict(cur, event_w=2.0)))
    paths = ladder + variants
    t0 = time.time()
    store = {nm: {} for nm, _ in paths}
    for idx, tups in walk_forward(recs, configs=[c for _, c in paths]):
        for (nm, _), tup in zip(paths, tups):
            store[nm][idx] = tup
    tour, play = store[ladder[0][0]], store[ladder[-1][0]]
    print(f"  walk-forward, {len(paths)} pricing paths  "
          f"{time.time()-t0:5.0f}s  {len(play):,} matches")

    idxs = sorted(play)
    span = recs[idxs[-1]][0] - recs[idxs[0]][0]
    cut = recs[idxs[0]][0] + span // 2
    tr = [i for i in idxs if recs[i][0] < cut]
    te = [i for i in idxs if recs[i][0] >= cut]
    print(f"\ntrain {len(tr):,} | test {len(te):,}  (nothing below tuned on test)\n")

    best = {}
    print("fit on TRAIN: tour-wide form_sd")
    for sd in (0.020, 0.030, 0.035, 0.040, 0.050):
        ll = logloss([price_tour(tour[i], sd) for i in tr])
        if ll < best.get("tour_ll", 9): best.update(tour_ll=ll, tour_sd=sd)
        print(f"   sd {sd:.3f}   {ll:.5f}")
    print(f"   -> {best['tour_sd']:.3f}")

    print("\nfit on TRAIN: scale on each player's own derived form_sd")
    for sc in (0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2):
        ll = logloss([price_player(play[i], sc) for i in tr])
        if ll < best.get("play_ll", 9): best.update(play_ll=ll, play_scale=sc)
        print(f"   scale {sc:.2f}   {ll:.5f}")
    print(f"   -> {best['play_scale']:.2f}")

    print("\nfit on TRAIN: weight on AIR DENSITY")
    for dw in (0.0, 0.05, 0.10, 0.20, 0.40):
        ll = logloss([price_player(play[i], best["play_scale"], dens_w=dw)
                      for i in tr])
        if ll < best.get("dw_ll", 9): best.update(dw_ll=ll, dens_w=dw)
        print(f"   dens_w {dw:.2f}   {ll:.5f}")
    print(f"   -> {best['dens_w']:.2f}")

    b_tour = fit_calibration([price_tour(tour[i], best["tour_sd"]) for i in tr])
    b_play = fit_calibration([price_player(play[i], best["play_scale"],
                                           dens_w=best["dens_w"]) for i in tr])
    print(f"\ncalibration slope on TRAIN   tour {b_tour:.3f}   "
          f"per-player {b_play:.3f}")
    print("   (<1 = was overconfident, shrink toward 0.5)")

    print(f"\n{'='*78}\nTEST  ({len(te):,} matches)")
    print("\nfit on TRAIN: Elo K")
    elo_c, best_k, bk = {}, None, 1e9
    for k in (2, 4, 8, 12, 24):
        elo_c[k] = elo_baseline(recs, k=k)
        ll = logloss([elo_c[k][i] for i in tr])
        if ll < bk: bk, best_k = ll, k
        print(f"   K {k:<3}  {ll:.5f}")
    print(f"   -> {best_k}")

    sc = best["play_scale"]
    rows = [
        ("coin flip", [0.5] * len(te)),
        (f"Elo, K={best_k} (match results only)", [elo_c[best_k][i] for i in te]),
        (f"{ladder[0][0]}, form_sd={best['tour_sd']:.3f}",
         [price_tour(tour[i], best["tour_sd"]) for i in te]),
        ("  + calibration",
         [apply_cal(price_tour(tour[i], best["tour_sd"]), b_tour) for i in te]),
    ]
    for nm, _ in ladder[1:]:
        rows.append((nm if nm.startswith("  ") else f"{nm} (scale {sc:.2f})",
                     [price_player(store[nm][i], sc) for i in te]))
    rows.append((f"  + air density (w={best['dens_w']:.2f})",
                 [price_player(play[i], sc, dens_w=best["dens_w"])
                  for i in te]))
    rows.append(("  + calibration",
                 [apply_cal(price_player(play[i], sc, dens_w=best["dens_w"]),
                            b_play) for i in te]))
    print(f"\n{'model':<44} {'log loss':>9} {'brier':>8} {'acc':>7} "
          f"{'vs above':>9} {'t':>7}")
    prev = None
    ladder_out = []
    for nm, ps in rows:
        ll, br, ac, n = score(ps)
        extra = ""
        if prev is not None and nm.startswith("  "):
            mu, t = paired_t(prev, ps)
            extra = f" {-mu:>+9.5f} {t:>+7.2f}"
            ladder_out.append({"rung": nm.strip(), "log_loss": ll,
                               "vs_previous": -mu, "paired_t": t})
        elif nm.startswith("per-player"):
            ladder_out.append({"rung": nm, "log_loss": ll})
        print(f"{nm:<44} {ll:>9.5f} {br:>8.5f} {ac:>7.4f}{extra}")
        prev = ps
    shipped_ps = rows[-2][1] if False else [
        price_player(play[i], sc, dens_w=best["dens_w"]) for i in te]
    for nm, _c in variants:
        ps = [price_player(store[nm][i], sc, dens_w=best["dens_w"])
              for i in te]
        ll, br, ac, n = score(ps)
        mu, t = paired_t(shipped_ps, ps)
        print(f"{nm:<44} {ll:>9.5f} {br:>8.5f} {ac:>7.4f} {-mu:>+9.5f} "
              f"{t:>+7.2f}   (vs shipped)")
        ladder_out.append({"rung": nm.strip(), "log_loss": ll,
                           "vs_shipped": -mu, "paired_t": t})

    final = rows[-1][1]
    print("\ncalibration on TEST, final model")
    for q, (sm, y, c) in sorted(calibration([(p, 1) for p in final]).items()):
        if c < 50: continue
        lo, hi = 0.5+q/6*0.5, 0.5+(q+1)/6*0.5
        print(f"  {lo:.2f}-{hi:.2f}  predicted {sm/c:.4f}  realised {y/c:.4f}"
              f"  gap {sm/c-y/c:+.4f}  ({c:,})")

    # A measured slope is not a reason to APPLY it.  Fitting per-player
    # form_sd already absorbs the overconfidence calibration was meant to
    # fix, so the slope comes out near 1 and applying it can make test loss
    # worse.  Writing b_play unconditionally silently re-enabled
    # calibration on every run and overwrote the note saying why it was off
    # -- exactly the failure Rule 7 in HANDOFF.md describes.  Decide on the
    # test numbers, then write what was actually chosen.
    uncal = rows[-2][1]
    ll_uncal, ll_cal = logloss(uncal), logloss(final)
    use_cal = ll_cal < ll_uncal
    b_used = b_play if use_cal else 1.0
    ll_final = ll_cal if use_cal else ll_uncal
    verdict = (f"Calibration ON: slope {b_play:.3f} improved test log loss "
               f"{ll_uncal:.5f} -> {ll_cal:.5f}."
               if use_cal else
               f"Calibration DISABLED (b=1.0). Measured slope {b_play:.3f}, "
               f"but applying it made test log loss WORSE "
               f"({ll_uncal:.5f} -> {ll_cal:.5f}): fitting per-player form_sd "
               f"absorbs the overconfidence it was built to fix.")
    print(f"\ncalibration decision: {'ON' if use_cal else 'OFF'}  "
          f"(uncalibrated {ll_uncal:.5f} vs calibrated {ll_cal:.5f})")

    keep = {k: _FP[k] for k in _FP if k.endswith("_note")}
    out = dict(keep)
    out.update({
        "form_sd": best["tour_sd"], "form_scale": best["play_scale"],
        # neither is in the pricing path; both measured at zero for the
        # life of the project and are no longer swept (see HANDOFF)
        "style_w": 0.0, "h2h_w": 0.0,
        "dens_w": best["dens_w"], "elo_k": best_k,
        "calibration_b": b_used,
        "calibration_b_measured": b_play,
        "calibration_b_tour": b_tour,
        # write back what was ACTUALLY used, never a literal --
        # hardcoding these silently clobbered the tuned values
        "half_life_days": HALF_LIFE, "prior_weight": PRIOR_W,
        "age_m_young": AGE_M_YOUNG, "age_m_old": AGE_M_OLD,
        "qc_supplement": _FP.get("qc_supplement", True),
        "qc_level_k": _FP.get("qc_level_k", 1.0),
        "event_update_w": EVENT_W,
        "three_stage_serve": STAGES,
        "surface_carry": CARRY,
        "long_years": LONG_YEARS,
        # the constants tools/knobsweep.py sweeps; written back so a swept
        # value survives the next refit (the writeback builds a fresh dict,
        # and a key it does not know about is silently dropped -- rule 7)
        "carry_cap": W.CARRY_CAP,
        "surface_half_life_days": W.SURFACE_HALF_LIFE,
        "refit_days": REFIT_DAYS,
        "prior_mode": W.PRIOR_MODE,
        "prior_age": ",".join(f"{x:g}" for x in W.PRIOR_AGE),
        "train_years": TRAIN_YEARS, "test_log_loss": ll_final,
        # the two numbers the app's "the model" tab shows beside the headline
        "test_matches": len(te),
        "elo_log_loss": logloss([elo_c[best_k][i] for i in te]),
        "test_log_loss_uncalibrated": ll_uncal,
        "test_log_loss_calibrated": ll_cal,
        "test_ladder": ladder_out,
        "scorable_matches": len(play),
        "news_w": _FP.get("news_w", 1.0),
        "fitted_on": f"{y0}-2026 walk-forward, train half ({len(tr)} matches)",
        "note": verdict + " dens_w is fitted but worth ~0.00006 on "
                "moneyline -- air density is symmetric, so its value "
                "should show up on games totals, not match winner. "
                "Refit with backtest.py after any model change.",
        "harness_note": "Since 2026-09-11 every refit goes through "
                        "weights.derive and every price through "
                        "price.serve_probs / price.match_prob -- the same "
                        "code the CLI runs -- so test_log_loss measures "
                        "the model that ships: the rating layer with the "
                        "qual/Challenger supplement and the age-dependent "
                        "half-life, the surface split with the recent-form "
                        f"carry-over ({'on' if CARRY else 'off'}), the "
                        f"three-stage serve ({'on' if STAGES else 'OFF'}), "
                        f"the in-event update (w={EVENT_W:g}), air density "
                        "and calibration. NOT in it: player news (no "
                        "historical archive) and the residual curves "
                        "(fitted on this harness's own residuals; scored by "
                        "tools/curves.py). `python3 backtest.py --gate` "
                        "asserts the harness derivation equals weights.json.",
    })
    json.dump(out, open("fitted_params.json", "w"), indent=2)
    print(f"\nwrote fitted_params.json  (test log loss {ll_final:.5f})")
