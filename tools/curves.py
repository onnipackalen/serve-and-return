"""Fit EFFECT CURVES, not effect coefficients.

    python3 tools/curves.py build          compute + cache walk-forward residuals
    python3 tools/curves.py fit            fit every covariate's curve
    python3 tools/curves.py fit event_matches
    python3 tools/curves.py antisym --logit  score them as price.py applies them
    python3 tools/curves.py write            write fitted_curves.json

Why curves.  Every adjustment in this project so far is a single number
multiplied by a feature -- style_w, h2h_w, dens_w.  That shape can only ever
say "more of this is more of that", and several of the things worth modelling
are not like that:

  wins banked at this event   rises to ~2 wins, then REVERSES at 4+
  days of rest                the VARIABLES table already says 0-1 tired,
                              2-4 optimal, 14+ rusty -- an inverted U
  minutes on court            costless early, punishing late

A linear weight fitted to a hump returns something near zero and the effect
is declared absent.  That is not a measurement, it is the wrong basis.

Method:
  * bucket the covariate, take the mean residual in each bucket
  * SHRINK each bucket toward zero by n/(n+k) -- rule 4, per-bucket means on
    a few hundred rows are noise dressed as structure
  * split TRAIN/TEST BY TIME and score the curve out of sample.  A curve
    fitted and judged on the same rows will always look good.

Residuals come from walk-forward prices, so nothing here saw its own match
(rule 5).  Building the cache is the slow part and only has to happen when
the model or the data changes.
"""

import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

CACHE = os.path.join(HERE, "residuals.json")

# covariate -> bucket edges.  Chosen to keep every bucket populated rather
# than to be round numbers; a bucket with 200 rows tells you nothing.
BUCKETS = {
    "event_matches":  [0, 1, 2, 3, 4, 99],
    "event_minutes":  [0, 1, 120, 240, 360, 480, 9999],
    "event_sets_lost": [0, 1, 2, 3, 4, 99],
    "event_5setters": [0, 1, 2, 99],
    "days_rest":      [0, 2, 4, 8, 15, 29, 60, 9999],
    "matches_28d":    [0, 2, 4, 6, 9, 99],
    "event_gwp":      [0.0, .45, .50, .53, .56, .60, 1.01],
    # injury proxies -- no column names them, but a retirement or a
    # withdrawal identifies a hurt player exactly, and a long layoff
    # identifies one who may not be match-sharp on return
    "ret_90d":        [0, 1, 2, 99],
    "wo_90d":         [0, 1, 2, 99],
    "comeback":       [0, 1, 2],
    "layoff_days":    [0, 1, 30, 60, 120, 240, 9999],
    # burdens that fall between events rather than inside them
    "travel_km":      [0, 1, 500, 1500, 4000, 8000, 99999],
    "elev_change_m":  [-9999, -500, -100, 100, 500, 9999],
    "surface_switch": [0, 1, 2],
    # playing in your own country.  The raw win rate at home is 46%, because
    # home players are disproportionately wildcards -- which is exactly why
    # this has to be measured on the model's RESIDUAL and not on results.
    "home":           [0, 1, 2],
    # the graded version: 0 is your own country, then how far away.  A binary
    # flag cannot see that Monte Carlo is nearly home for a Frenchman, or
    # that half the field at a South American event is one border away.
    # Three buckets, each with a mechanism: near home (own country or one
    # border away -- crowd, no travel, no time zones), the ordinary middle,
    # and long-haul.  A six-bucket version of this fitted the wiggles in
    # between and lost out of sample; the edges here come from the TRAIN
    # half's fitted shape, which is what report() prints.
    "home_km":        [0, 800, 10000, 99999],
    # things the model has never seen.  Edges sit near the 5th/95th
    # percentile of each so no bucket is a handful of rows.
    "age":            [0, 21, 24, 27, 30, 33, 99],
    "form_spw":       [-1, -0.03, -0.01, 0.01, 0.03, 0.06, 1],
    "bp_form":        [-1, -0.06, -0.02, 0.02, 0.06, 1],
    "event_opp_rank": [0, 1.5, 1.8, 2.1, 2.4, 9],
    # controls for the age finding, and the trend age might only be proxying
    "career_matches": [0, 10, 30, 80, 180, 350, 99999],
    "career_pts":     [0, 300, 1000, 2500, 4500, 7000, 999999],
    "rank_change":    [-9, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 9],
    "peak_gap":       [-9, 0.02, 0.10, 0.30, 0.60, 1.0, 9],
    # opponent CALIBRE, which the style interaction deliberately strips out:
    # it keeps the opponent's shape and throws away their level, on the
    # grounds that level is what the base model handles.  Whether the base
    # model handles it EQUALLY WELL FOR EVERY PLAYER is a separate claim,
    # and it has never been tested.
    "vs_quality":     [-1, -0.004, -0.0015, 0, 0.0015, 0.004, 1],
    "opp_log_rank":   [0, 1.0, 1.4, 1.7, 2.0, 2.3, 9],
    "opp_faced_mean": [0, 1.5, 1.7, 1.9, 2.1, 9],
    # Round. Both players share it, so it CANNOT move an antisymmetric price
    # -- it is here to be measured as a confidence input and as the base of
    # an interaction.
    "round_order":    [0, 3, 4, 5, 6, 7, 8, 9],
    "wins_to_title":  [1, 2, 3, 4, 5, 8],
    "draw_size":      [0, 33, 65, 129],
    # a run of wins, signed by which side of the price the player is on
    "run_vs_price":   [-9, -0.6, -0.2, 0, 0.2, 0.6, 9],
    "price_only":     [-9, -0.25, -0.1, 0, 0.1, 0.25, 9],
    # --- 2026-09-11: columns the loader never read, and per-player traits
    # how the player got into the draw: 0 main, 1 Q, 2 WC, 3 LL, 4 PR
    # (protected ranking -- back from injury), 5 special exempt, 6 other
    "entry":          [0, 1, 2, 3, 4, 5, 6, 7],
    "seeded":         [0, 1, 2],
    "log_rank":       [0, 1.0, 1.4, 1.7, 2.0, 2.3, 9],
    "rank_gap":       [-9, -1.0, -0.5, -0.2, 0, 0.2, 0.5, 1.0, 9],
    "opp_lefty":      [0, 1, 2],
    # Elo's opinion against the point model's, in log-odds.  Elo reads only
    # who won; if closing out matches is a trait the point rates miss, it
    # lives here.  price_only is the control, as for run_vs_price.
    "elo_vs_model":   [-9, -0.5, -0.2, -0.05, 0.05, 0.2, 0.5, 9],
    # PER-PLAYER TRAITS from the player's own PRIOR walk-forward residuals,
    # shrunk by n/(n+TRAIT_K): does this player beat the point model, and
    # does that differ in best-of-five?  Rule 17 first -- `reliability`.
    "resid_prior":    [-1, -0.04, -0.015, -0.005, 0.005, 0.015, 0.04, 1],
    "bo5_resid_prior": [-1, -0.05, -0.02, 0, 0.02, 0.05, 1],
    "bo_diff_prior":  [-1, -0.05, -0.02, 0, 0.02, 0.05, 1],
    # 2026-09-12: the trend-shaped versions of the trait.  resid_365 is the
    # same mean over the last 365 days only (a player who has STARTED beating
    # the model), resid_surface the mean on this row's surface only.
    "resid_365":      [-1, -0.06, -0.025, -0.005, 0.005, 0.025, 0.06, 1],
    "resid_surface":  [-1, -0.04, -0.015, -0.005, 0.005, 0.015, 0.04, 1],
}
SHRINK_K = 400.0        # rows before a bucket mean stands mostly on its own
TRAIT_K = float(os.environ.get("TENNIS_TRAIT_K") or 40.0)   # matches before a player's own residual mean counts
TRAIT_MIN = int(os.environ.get("TENNIS_TRAIT_MIN") or 15)   # fewer prior matches than this: no read (None)
RECENT_K, RECENT_MIN = 20.0, 8      # the 365-day version: fewer rows, stronger prior


def annotate_traits(rows):
    """Add the per-player residual traits to every cached row, from that
    player's PRIOR rows only.

    Rows are processed a day at a time and a player's running sums are
    updated only after the whole day is done, so a match never sees itself
    or another match from the same event day (rule 5, and rule 14 -- every
    round of an event carries one date).  The mean is shrunk toward zero
    by n/(n+TRAIT_K), a population estimate plus a shrunk deviation, as
    every per-player value here is (rule 4).
    """
    rows = sorted(rows, key=lambda r: r["day"])
    tot = collections.defaultdict(lambda: [0.0, 0])       # all matches
    b5 = collections.defaultdict(lambda: [0.0, 0])        # best-of-five only
    b3 = collections.defaultdict(lambda: [0.0, 0])
    surf = collections.defaultdict(lambda: [0.0, 0])      # (pid, surface)
    recent = collections.defaultdict(list)                # pid -> [(day, res)]
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]["day"] == rows[i]["day"]:
            j += 1
        day = rows[i]["day"]
        for r in rows[i:j]:
            pid = r.get("pid")
            s, n = tot[pid]
            r["f"]["resid_prior"] = (s / n) * (n / (n + TRAIT_K)) if n >= TRAIT_MIN else None
            s5, n5 = b5[pid]
            s3, n3 = b3[pid]
            r["f"]["bo5_resid_prior"] = (s5 / n5) * (n5 / (n5 + TRAIT_K)) if n5 >= TRAIT_MIN else None
            r["f"]["bo_diff_prior"] = (((s5 / n5) - (s3 / n3)) * (n5 / (n5 + TRAIT_K))
                                       if (n5 >= TRAIT_MIN and n3 >= TRAIT_MIN) else None)
            ss, ns = surf[(pid, r.get("surf"))]
            r["f"]["resid_surface"] = (ss / ns) * (ns / (ns + TRAIT_K)) if ns >= TRAIT_MIN else None
            rec = [x for _d, x in recent[pid] if day - _d <= 365]
            nr = len(rec)
            r["f"]["resid_365"] = ((sum(rec) / nr) * (nr / (nr + RECENT_K))
                                   if nr >= RECENT_MIN else None)
        for r in rows[i:j]:
            pid = r.get("pid")
            res = r["y"] - r["p"]
            tot[pid][0] += res; tot[pid][1] += 1
            side = b5 if r.get("bo") == 5 else b3
            side[pid][0] += res; side[pid][1] += 1
            surf[(pid, r.get("surf"))][0] += res
            surf[(pid, r.get("surf"))][1] += 1
            recent[pid].append((day, res))
            if len(recent[pid]) > 200:
                recent[pid] = recent[pid][-200:]
        i = j
    return rows


def trait_reliability(rows, min_n=40, seed=0):
    """Split-half reliability of the per-player residual mean (rule 17).

    Each player's rows are split at random into two halves; the two half
    means are correlated across players.  If the halves are uncorrelated
    there is no trait to shrink toward and no curve can be honest.
    """
    import random
    rng = random.Random(seed)
    by = collections.defaultdict(list)
    for r in rows:
        by[r.get("pid")].append(r["y"] - r["p"])
    out = {}
    for label, sel in (("all matches", lambda r: True),
                       ("best-of-five", lambda r: r.get("bo") == 5)):
        by = collections.defaultdict(list)
        for r in rows:
            if sel(r):
                by[r.get("pid")].append(r["y"] - r["p"])
        xs, ys = [], []
        for pid, v in by.items():
            if len(v) < min_n:
                continue
            v = v[:]
            rng.shuffle(v)
            h = len(v) // 2
            xs.append(sum(v[:h]) / h)
            ys.append(sum(v[h:]) / (len(v) - h))
        n = len(xs)
        if n < 10:
            out[label] = (n, None, None)
            continue
        mx, my = sum(xs) / n, sum(ys) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs)
        syy = sum((y - my) ** 2 for y in ys)
        r_ = sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0
        # Spearman-Brown: reliability of the full-sample mean
        full = 2 * r_ / (1 + r_) if r_ > -1 else 0.0
        out[label] = (n, r_, full)
    return out


def build_cache(y0=2015, y1=2026):
    import backtest as B
    import features as F
    # The measured-and-rejected opponent-calibre covariates are off in
    # production and cost ~15 minutes of features.build (every player
    # history is rescanned per match).  TENNIS_EXTRA=1 switches them on for
    # a re-measurement; the default build takes about two minutes.
    F.EXTRA_FEATURES = bool(os.environ.get("TENNIS_EXTRA"))
    from fit import to_day
    from load import load

    matches, _bad = load(y0 - 3, y1)
    matches = [m for m in matches if m.tourney_date >= f"{y0-3}0101"]
    feats = F.build(matches)
    meta = {}
    for m in matches:
        meta.setdefault((to_day(m.tourney_date), m.w_id, m.l_id), []).append(m)

    # The residuals these curves correct must come from THE MODEL THAT
    # SHIPS, or every curve corrects errors the shipped estimator does not
    # make.  walk_forward with no arguments is exactly that: every refit
    # through weights.derive, every price through price.serve_probs, with
    # the supplement, the three-stage serve, the in-event update and the
    # surface carry-over as fitted_params says they ship.  Until 2026-09-11
    # it was the rating layer only, and the curves were fitted against a
    # model worse than the one that applied them.
    print("pricing walk-forward (slow, cached afterwards) ...", flush=True)
    recs = B.records(y0 - 3, y1)
    scale = B._FP.get("form_scale", 0.85)
    dens_w = B._FP.get("dens_w", 0.0)
    # Elo on the same records, walk-forward by construction, so its opinion
    # of every match can be held against the point model's (elo_vs_model)
    elo = B.elo_baseline(recs, k=B._FP.get("elo_k", 4))
    rows = []
    blk = {}                       # the block each match was priced from
    for idx, tup in B.walk_forward(recs, book_out=blk):
        day, w_id, l_id = recs[idx][0], recs[idx][1], recs[idx][2]
        cand = meta.get((day, w_id, l_id))
        if not cand:
            continue
        m = cand[0]
        p_w = B.price_player(tup, scale, style_w=0.0, h2h_w=0.0, dens_w=dens_w)
        # service points behind each rating AS OF THIS MATCH, not as of
        # today: the confidence band's "how well measured is this player"
        # input, which it had been approximating with a recent-match count
        den = blk["book"].overall["den"]
        # and the model's own volatility estimate for each player, which the
        # walk already yields: the band has never been allowed to read the
        # model saying "I am unsure about this one"
        sd = {w_id: tup[3], l_id: tup[4]}
        for pid, p, actual, e in ((w_id, p_w, 1, elo[idx]),
                                  (l_id, 1 - p_w, 0, 1 - elo[idx])):
            f = feats.get((m.tid, m.rnd, pid), {})
            # the player's id, so anything PER-PLAYER can be measured on this
            # cache instead of guessed at from proxies.  confidence.py has a
            # comment apologising for its absence; a per-player slope cannot
            # be estimated without it at all.
            rows.append({"day": day, "p": p, "y": actual, "pid": pid,
                         "bo": m.best_of, "elo_p": e, "surf": m.surface,
                         "den": den.get(pid, 0.0), "form_sd": sd.get(pid),
                         "f": {k: f.get(k) for k in BUCKETS}})
    annotate_traits(rows)
    with open(CACHE, "w") as fh:
        json.dump(rows, fh)
    print(f"  cached {len(rows):,} player-rows -> {CACHE}")
    print("\n  These residuals are priced through price.serve_probs and")
    print("  price.match_prob -- the CLI's own code -- with the pricing path")
    print(f"  as fitted_params ships it: three-stage serve "
          f"{'on' if B.STAGES else 'off'}, in-event update w={B.EVENT_W:g}, "
          f"surface carry-over {'on' if B.CARRY else 'off'},")
    print(f"  qual/Challenger supplement "
          f"{'on' if B._FP.get('qc_supplement', True) else 'off'}, "
          f"form_scale {scale:g}, dens_w {dens_w:g}.")
    print("  NOT modelled: player news (no historical archive exists) and")
    print("  the curves themselves, which are what this cache fits.")
    return rows


def load_cache():
    if not os.path.exists(CACHE):
        sys.exit("no cache -- run: python3 tools/curves.py build")
    with open(CACHE) as fh:
        return json.load(fh)


# Covariates computed FROM a cached row rather than stored on it, because
# they combine a feature with the model's own price -- which features.py
# never sees.  round_effect.py found that a run of wins at an event moves
# underdogs and favourites in OPPOSITE directions, which is exactly why the
# raw count fitted to zero: pooled, the two halves cancel.
def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


DERIVED = {
    # the control: the price ALONE, with no run attached.  If run_vs_price is
    # really re-learning the global calibration slope, this absorbs it.
    "price_only": lambda r: 0.5 - r["p"],
    "run_vs_price": lambda r: (
        None if r["f"].get("event_matches") is None
        else r["f"]["event_matches"] * (0.5 - r["p"])),
    # Elo minus the point model, in log-odds; antisymmetric row to row
    "elo_vs_model": lambda r: (
        None if r.get("elo_p") is None else _logit(r["elo_p"]) - _logit(r["p"])),
}


def value_of(name, r):
    """The covariate for this row, stored or derived."""
    if name in DERIVED:
        return DERIVED[name](r)
    return r["f"].get(name)


def bucket_of(name, v):
    if v is None:
        return None
    edges = BUCKETS[name]
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i
    return None


def fit_curve(rows, name, shrink_k=SHRINK_K):
    """{bucket: shrunk mean residual} from these rows."""
    acc = collections.defaultdict(lambda: [0.0, 0])
    for r in rows:
        b = bucket_of(name, value_of(name, r))
        if b is None:
            continue
        acc[b][0] += r["y"] - r["p"]
        acc[b][1] += 1
    return {b: (s / n) * (n / (n + shrink_k)) for b, (s, n) in acc.items()}, \
           {b: n for b, (_s, n) in acc.items()}


def apply_curve(p, adj):
    """Nudge a probability by an additive residual, staying in (0,1)."""
    return min(max(p + adj, 1e-6), 1 - 1e-6)


def apply_logit(p, adj):
    """The same nudge as a shift in LOG-ODDS, normalised to match at p=0.5.

    Additive-in-probability cannot be right in the tails: a -0.038 shift on
    a 3.3% underdog takes the price NEGATIVE, and the clamp then prices it
    at 1e-6 -- fair odds of a million to one.  One such row costs 13.8 nats
    and on its own made an entire test fold prefer a smaller adjustment.
    price.py has the same clamp and can emit the same absurd price.

    A constant log-odds shift cannot leave (0,1) and shrinks toward the
    tails, which is the behaviour a bucket-average residual should have:
    "this group wins 1 point more often than priced" is a statement about
    matches near the middle, where the bucket's mass is, not about 3%
    underdogs.

    dp/dz = p(1-p), which is 1/4 at p = 0.5, so a log-odds shift of 4*adj
    reproduces the fitted residual exactly where the curves were fitted and
    tapers away from there.  The factor is a change of units, not a free
    parameter -- the scale sweep is what measures magnitude.
    """
    p = min(max(p, 1e-9), 1 - 1e-9)
    z = math.log(p / (1 - p)) + 4.0 * adj
    return 1.0 / (1.0 + math.exp(-z)) if z > -700 else 1e-300


def logloss(rows, curve=None, name=None):
    tot = 0.0
    for r in rows:
        p = r["p"]
        if curve is not None:
            b = bucket_of(name, value_of(name, r))
            if b in curve:
                p = apply_curve(p, curve[b])
        tot -= math.log(max(min(p, 1 - 1e-12), 1e-12)) if r["y"] else \
            math.log(max(min(1 - p, 1 - 1e-12), 1e-12))
    return tot / len(rows)


def report(rows, name):
    rows = [r for r in rows if value_of(name, r) is not None]
    if len(rows) < 2000:
        print(f"  {name}: too few rows ({len(rows)})")
        return
    rows.sort(key=lambda r: r["day"])
    cut = len(rows) // 2
    train, test = rows[:cut], rows[cut:]

    curve, counts = fit_curve(train, name)
    base = logloss(test)
    with_c = logloss(test, curve, name)
    edges = BUCKETS[name]

    print(f"\n  {name}   (train {len(train):,} / test {len(test):,})")
    print(f"    {'bucket':>14} {'n':>7} {'raw resid':>10} {'shrunk':>9}")
    raw, rawn = fit_curve(train, name, shrink_k=0.0)
    for b in sorted(curve):
        lo, hi = edges[b], edges[b + 1]
        lbl = f"{lo:g}-{hi:g}" if hi < 999 else f"{lo:g}+"
        bar = "#" * int(abs(curve[b]) * 700)
        print(f"    {lbl:>14} {counts[b]:>7,} {raw.get(b,0):>+10.4f} "
              f"{curve[b]:>+9.4f}  {bar}")
    d = with_c - base
    verdict = "IMPROVES" if d < -1e-5 else "no help" if d < 1e-5 else "HURTS"
    print(f"    out-of-sample log loss {base:.5f} -> {with_c:.5f}  "
          f"({d:+.5f}, {verdict})")
    return d


def combined(rows, names, folds=4):
    """Fit several curves together and score them on rolling time folds.

    Two separate wins can be the same win counted twice -- matches_28d and
    days_rest are near-substitutes, and event_gwp only exists for players
    who already played here.  Applying them jointly, on folds the curves
    never saw, is the only way to know what is actually left.
    """
    rows = sorted(rows, key=lambda r: r["day"])
    n = len(rows)
    edges = [int(n * i / (folds + 1)) for i in range(folds + 2)]
    base_tot = new_tot = 0.0
    seen = 0
    for i in range(1, folds + 1):
        train = rows[:edges[i]]
        test = rows[edges[i]:edges[i + 1]]
        if not test:
            continue
        curves = {nm: fit_curve(train, nm)[0] for nm in names}
        b = nw = 0.0
        for r in test:
            p = r["p"]
            adj = 0.0
            for nm in names:
                bkt = bucket_of(nm, value_of(nm, r))
                if bkt in curves[nm]:
                    adj += curves[nm][bkt]
            q = apply_curve(p, adj)
            if r["y"]:
                b -= math.log(max(p, 1e-12)); nw -= math.log(max(q, 1e-12))
            else:
                b -= math.log(max(1 - p, 1e-12))
                nw -= math.log(max(1 - q, 1e-12))
        base_tot += b
        new_tot += nw
        seen += len(test)
        print(f"    fold {i}  n={len(test):>6,}  base {b/len(test):.5f}  "
              f"with curves {nw/len(test):.5f}  {(nw-b)/len(test):+.5f}")
    print(f"    ALL      n={seen:>6,}  base {base_tot/seen:.5f}  "
          f"with curves {new_tot/seen:.5f}  {(new_tot-base_tot)/seen:+.5f}")
    return (new_tot - base_tot) / seen


def match_pairs(rows):
    """Rebuild matches from the cache.

    build_cache appends the winner's row and then the loser's row from the
    SAME walk-forward price, so they are adjacent and p_l == 1 - p_w.  A
    stable sort by day keeps them adjacent because both carry the same day.
    Verified here rather than assumed -- a silent off-by-one would pair each
    winner with the next match's loser and every number below would be noise.
    """
    rows = sorted(rows, key=lambda r: r["day"])
    out, bad = [], 0
    for i in range(0, len(rows) - 1, 2):
        w, l = rows[i], rows[i + 1]
        if w["y"] != 1 or l["y"] != 0 or abs(w["p"] + l["p"] - 1) > 1e-9:
            bad += 1
            continue
        out.append((w, l))
    if bad:
        print(f"    ! {bad:,} rows did not pair -- cache may be stale")
    return out


def antisym(rows, names, folds=4, mode="add", quiet=False,
            scales=(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)):
    """Score the curves the way price.py actually APPLIES them, and ask
    whether the way it applies them is right.

    combined() nudges each player's row on its own.  price.py cannot do that
    -- two probabilities must sum to one -- so it applies k*(adj_a - adj_b)
    to A and the negative to B.  Antisymmetry is required (rule 9); the
    magnitude k is a separate claim, and this is where it is measured.  The
    grid below is in units where x1 is k = 1/2 (the original conservative
    choice) and x2 is k = 1, which is what price.py ships.

    Because the adjustment is antisymmetric it maps 0.5 -> 0.5 and one row
    per match is enough: the loser's row is 1 minus the winner's by
    construction, so scoring both would be scoring the same number twice.
    That is exactly the condition rule 9 demands before a winner-oriented
    evaluation is legitimate.

    Curves are fitted on each fold's TRAIN half only; the scale is read off
    the training rows too, and the honest column is the last one.
    """
    pairs = match_pairs(rows)
    say = (lambda *_a, **_k: None) if quiet else print
    say(f"    application: {mode}")
    n = len(pairs)
    say(f"    {n:,} matches paired from {len(rows):,} player-rows")
    edges = [int(n * i / (folds + 1)) for i in range(folds + 2)]

    put = apply_logit if mode == "logit" else apply_curve

    def loss_at(chunk, curves, scale):
        tot = 0.0
        for w, l in chunk:
            adj = 0.0
            for nm in names:
                bw = bucket_of(nm, value_of(nm, w))
                bl = bucket_of(nm, value_of(nm, l))
                adj += (curves[nm].get(bw, 0.0) - curves[nm].get(bl, 0.0))
            q = put(w["p"], scale * adj / 2.0)
            tot -= math.log(max(q, 1e-12))
        return tot / max(len(chunk), 1)

    hdr = "  ".join(f"x{s:g}".rjust(8) for s in scales)
    say(f"    {'fold':>6} {'n':>7}  {hdr}   {'best on train':>14}  {'that scale on test':>18}")
    tot_base = tot_half = tot_fitted = 0.0
    seen = 0
    per_fold = [[] for _ in scales]
    sizes = []
    for i in range(1, folds + 1):
        train, test = pairs[:edges[i]], pairs[edges[i]:edges[i + 1]]
        if not test:
            continue
        curves = {nm: fit_curve([r for pr in train for r in pr], nm)[0]
                  for nm in names}
        cells = [loss_at(test, curves, s) for s in scales]
        best = min(scales, key=lambda s: loss_at(train, curves, s))
        on_test = loss_at(test, curves, best)
        for si, c in enumerate(cells):
            per_fold[si].append(c)
        sizes.append(len(test))
        row = "  ".join(f"{c:8.5f}" for c in cells)
        say(f"    {i:>6} {len(test):>7,}  {row}   {best:>14g}  {on_test:>18.5f}")
        tot_base += cells[scales.index(0.0)] * len(test)
        tot_half += loss_at(test, curves, 2.0) * len(test)      # k = 1
        tot_fitted += on_test * len(test)
        seen += len(test)
    # A per-fold scale chosen on train can sit at the edge of the grid while
    # one fold quietly disagrees, so also report every FIXED scale summed
    # over all folds, with how many folds it actually helps.  A constant
    # that helps 4/4 is a result; one that helps 3/4 by more is a coin toss.
    say()
    say(f"    {'fixed scale':>12} {'all folds':>10} {'vs x0':>9} {'folds helped':>13}")
    for si, sc in enumerate(scales):
        tot = sum(per_fold[si][j] * sizes[j] for j in range(len(sizes))) / seen
        helped = sum(1 for j in range(len(sizes))
                     if per_fold[si][j] < per_fold[scales.index(0.0)][j])
        say(f"    {sc:>12g} {tot:>10.5f} {tot - tot_base / seen:>+9.5f} "
              f"{helped:>10}/{len(sizes)}")
    say()
    say(f"    no curves                             {tot_base / seen:.5f}")
    say(f"    curves as price.py applies them (x2)  {tot_half / seen:.5f}"
          f"   ({(tot_half - tot_base) / seen:+.5f})")
    say(f"    scale chosen on train                 {tot_fitted / seen:.5f}"
          f"   ({(tot_fitted - tot_base) / seen:+.5f})")
    if quiet:
        # the last scale in the grid, which loo sets to the shipping one
        return sum(per_fold[-1][j] * sizes[j] for j in range(len(sizes))) / seen
    return (tot_half - tot_base) / seen, (tot_fitted - tot_base) / seen


# The curves price.py actually applies.  Each one earned its place on the
# rolling-fold antisymmetric harness (`antisym --logit`), not on its own
# single-split number, because near-substitutes cancel: `home` and `home_km`
# are individually positive and together worth exactly nothing.
ADOPTED = ["matches_28d", "event_gwp", "event_sets_lost", "home",
           "age", "form_spw", "resid_prior", "entry"]

OUT = os.path.join(ROOT, "fitted_curves.json")
TRAITS = os.path.join(ROOT, "data", "player_traits.json")


def _shipped_k():
    """The magnitude price.py applies, from fitted_curves.json (1.0 if unset)."""
    try:
        with open(OUT) as fh:
            return float(json.load(fh).get("k", 1.0))
    except (OSError, ValueError):
        return 1.0


def player_traits(rows):
    """pid -> the per-player residual traits a LIVE price reads.

    Live pricing has no walk-forward residual for a match that has not
    happened, so the trait it consumes is the player's mean residual over
    every cached row, shrunk by n/(n+TRAIT_K).  Every cached row is
    out-of-sample with respect to the fit that priced it, and a live match
    is after all of them, so this is the same quantity annotate_traits
    gives a historical row, evaluated at the end of the log.
    """
    tot = collections.defaultdict(lambda: [0.0, 0])
    b5 = collections.defaultdict(lambda: [0.0, 0])
    surf = collections.defaultdict(lambda: [0.0, 0])
    recent = collections.defaultdict(lambda: [0.0, 0])
    last = max(r["day"] for r in rows) if rows else 0
    for r in rows:
        res = r["y"] - r["p"]
        tot[r["pid"]][0] += res; tot[r["pid"]][1] += 1
        if r.get("bo") == 5:
            b5[r["pid"]][0] += res; b5[r["pid"]][1] += 1
        surf[(r["pid"], r.get("surf"))][0] += res
        surf[(r["pid"], r.get("surf"))][1] += 1
        if last - r["day"] <= 365:
            recent[r["pid"]][0] += res; recent[r["pid"]][1] += 1
    out = {}
    for pid, (s, n) in tot.items():
        if n < TRAIT_MIN:
            continue
        e = {"resid_prior": round((s / n) * (n / (n + TRAIT_K)), 6), "n": n}
        s5, n5 = b5[pid]
        if n5 >= TRAIT_MIN:
            e["bo5_resid_prior"] = round((s5 / n5) * (n5 / (n5 + TRAIT_K)), 6)
            e["n5"] = n5
        sr, nr = recent[pid]
        if nr >= RECENT_MIN:
            e["resid_365"] = round((sr / nr) * (nr / (nr + RECENT_K)), 6)
            e["n365"] = nr
        sf = {}
        for (p2, sfc), (ss, ns) in surf.items():
            if p2 == pid and sfc and ns >= TRAIT_MIN:
                sf[sfc] = round((ss / ns) * (ns / (ns + TRAIT_K)), 6)
        if sf:
            e["surf"] = sf
        out[pid] = e
    return out


def write(rows, names=None, k=None):
    """Fit the adopted curves on the whole cache and write fitted_curves.json.

    Rule 7: write back what was actually used.  Until now this file was
    maintained by hand, which meant the note inside it described a state the
    code had moved on from -- it still claimed the curves were worth
    -0.0008 and closed 3% of the market gap, both superseded.

    `k` is the magnitude price.py applies (its log-odds shift is 4*k*adj);
    it is written into the file so price.py and this harness cannot differ.
    Also writes data/player_traits.json, the per-player residual traits a
    live price reads (player_traits), whenever a trait curve is adopted.
    """
    names = names or ADOPTED
    k = _shipped_k() if k is None else k
    curves, counts = {}, {}
    for nm in names:
        c, n = fit_curve(rows, nm)
        curves[nm] = {str(b): round(v, 6) for b, v in sorted(c.items())}
        counts[nm] = {str(b): v for b, v in sorted(n.items())}
    if any(nm in ("resid_prior", "bo5_resid_prior", "resid_365",
                  "resid_surface") for nm in names):
        tr = player_traits(rows)
        with open(TRAITS, "w") as fh:
            json.dump(tr, fh)
        print(f"  wrote {TRAITS}  ({len(tr):,} players)")
    doc = {
        "k": k,
        "_note": (
            "Residual adjustments to a player's win probability, indexed by "
            "bucket. Fitted on walk-forward residuals (never on the data "
            "that fitted the ratings), shrunk toward zero by n/(n+%g), and "
            "validated on rolling time folds with the adjustment applied "
            "ANTISYMMETRICALLY and in LOG-ODDS, which is how price.py "
            "applies them. Worth -0.00541 nats out of sample (2026-09-15, 7-day cadence, "
            "age-dependent prior, refreshed archive; -0.00738 with the flat own prior, "
            "-0.00807 at 21 days, -0.00999 at 91 -- each improvement to the rating layer "
            "leaves the curves less to correct) at the shipped magnitude (k=1), 4 folds "
            "of 4; k=1.25 is within 0.0003 of it and the scale chosen on each fold's "
            "train half scores worse, so the natural value stays. Cost of dropping: entry "
            "+0.00100, age +0.00091, event_gwp +0.00090, resid_prior +0.00088, matches_28d "
            "+0.00083, form_spw +0.00026, event_sets_lost +0.00022, home +0.00015 -- entry "
            "is now the largest and age has more than halved, which is the age-dependent "
            "prior doing what it was built to do. EIGHT curves since 2026-09-12: entry "
            "(how the player got into the draw: qualifiers beat their price, "
            "protected-ranking entrants miss it) adds -0.00058 on top of the "
            "seven and costs +0.00058 to drop; live prices take it from the "
            "--entry flag / the app control, or from the player's earlier "
            "rows at the event when the archive carries a code, else unknown "
            "and no adjustment (the reconstructed feed carries the code since 2026-09-14). "
            "Measured 2026-09-12 and REJECTED in company: resid_365 (the "
            "player's residual over the last 365 days only, -0.00131 alone, "
            "+0.00092 when added: a substitute for resid_prior) and "
            "resid_surface (the residual on this surface only, -0.00038 alone, "
            "+0.00119 when added). Refitted 2026-09-11 against "
            "residuals priced through the CLI's own path (price.serve_probs: "
            "surface with the recent-form carry-over, in-event update, air "
            "density, the qual/Challenger supplement, age multipliers "
            "(0.50, 0.85); three-stage serve OFF). SEVEN curves: the seventh, "
            "resid_prior, is the player's own mean walk-forward residual over "
            "their prior matches, shrunk by n/(n+40) -- does this player beat "
            "the point model -- split-half reliability 0.39 for players with "
            "40+ rows; it adds -0.00166 on top of the other six and costs "
            "+0.00166 to drop; live prices read it from data/player_traits.json. "
            "Cost of dropping each from the set: age +0.00255, resid_prior "
            "+0.00166, matches_28d +0.00146, event_gwp +0.00092, form_spw "
            "+0.00074, home +0.00018, event_sets_lost +0.00016. "
            "Measured 2026-09-11 and REJECTED in company: rank_gap (+0.00077 "
            "when added), seeded (+0.00035), bo5_resid_prior (+0.00007), "
            "log_rank (-0.00012, not worth a stale live input), elo_vs_model "
            "and opp_lefty (hurt alone), bo_diff_prior (hurts alone); entry "
            "type ADDS -0.00047 but cannot be known live before a player's "
            "first match at an event, so it waits for a draw source. "
            "REJECTED, each because it makes the SET worse or adds nothing: "
            "event_matches (raw wins banked -- the signal is margin, not "
            "count), bp_form (break points saved: clutch is noise), "
            "event_opp_rank, career_matches, career_pts, home_km, "
            "rank_change, peak_gap. The last three are all the same trend "
            "signal `age` already carries."
            % SHRINK_K),
        "shrink_k": SHRINK_K,
        "buckets": {nm: BUCKETS[nm] for nm in names},
        "curves": curves,
        "n": counts,
    }
    with open(OUT, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"  wrote {OUT}")
    for nm in names:
        tot = sum(counts[nm].values())
        print(f"    {nm:<18} {len(curves[nm])} buckets, {tot:,} rows")
    return doc


def forward(rows, base, cands, k=None, folds=4):
    """What does each candidate add ON TOP of the adopted set, alone?

    The complement of leave_one_out.  Dropping a candidate from a pool that
    contains its near-substitutes always looks good -- the 2026-09-11 pool
    of six candidates was 0.005 WORSE than the six adopted curves alone, and
    every ranking-shaped candidate "hurt" it -- so the question that can
    adopt one is what it adds to the shipped set by itself.
    """
    k = _shipped_k() if k is None else k
    full = antisym(rows, base, folds=folds, mode="logit", scales=(0.0, 2 * k),
                   quiet=True)
    print(f"\n  {'added':<20} {'set with it':>15} {'gain from adding':>18}")
    print(f"  {'(nothing)':<20} {full:>15.5f} {'':>18}")
    out = {}
    for nm in cands:
        v = antisym(rows, base + [nm], folds=folds, mode="logit",
                    scales=(0.0, 2 * k), quiet=True)
        out[nm] = v - full
        verdict = ("ADDS" if v - full < -1e-5 else
                   "nothing" if v - full < 1e-5 else "HURTS")
        print(f"  {nm:<20} {v:>15.5f} {v - full:>+18.5f}  {verdict}")
    return out


def leave_one_out(rows, names, k=None, folds=4):
    """What does each curve add ON TOP OF the others, and what does it cost
    to drop it?

    A curve that scores well alone can be worth nothing in company -- `home`
    and `home_km` are individually positive and jointly worth zero.  The
    only question that decides whether a curve ships is what the set loses
    without it.
    """
    k = _shipped_k() if k is None else k
    full = antisym(rows, names, folds=folds, mode="logit", scales=(0.0, 2 * k),
                   quiet=True)
    print(f"\n  {'dropped':<20} {'set without it':>15} {'cost of dropping':>18}")
    print(f"  {'(nothing)':<20} {full:>15.5f} {'':>18}")
    out = {}
    for nm in names:
        rest = [x for x in names if x != nm]
        v = (antisym(rows, rest, folds=folds, mode="logit",
                     scales=(0.0, 2 * k), quiet=True) if rest else 0.0)
        out[nm] = v - full
        verdict = ("earns it" if v - full > 1e-5 else
                   "DEAD WEIGHT" if v - full > -1e-5 else "HURTS THE SET")
        print(f"  {nm:<20} {v:>15.5f} {v - full:>+18.5f}  {verdict}")
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fit"
    if cmd == "loo":
        args = sys.argv[2:]
        k = None
        for a in args:
            if a.startswith("--k="):
                k = float(a[4:])
        names = [a for a in args if not a.startswith("-")] or ADOPTED
        kk = _shipped_k() if k is None else k
        print(f"leave-one-out over {names}, at k={kk:g} (price.py's magnitude):")
        leave_one_out(load_cache(), names, k=k)
        return 0
    if cmd == "add":
        args = sys.argv[2:]
        k = None
        for a in args:
            if a.startswith("--k="):
                k = float(a[4:])
        cands = [a for a in args if not a.startswith("-")]
        kk = _shipped_k() if k is None else k
        print(f"forward selection onto {ADOPTED}, at k={kk:g}:")
        forward(load_cache(), ADOPTED, cands, k=k)
        return 0
    if cmd == "write":
        args = sys.argv[2:]
        k = None
        for a in args:
            if a.startswith("--k="):
                k = float(a[4:])
        names = [a for a in args if not a.startswith("-")] or None
        write(load_cache(), names, k=k)
        return 0
    if cmd == "antisym":
        rows = load_cache()
        args = sys.argv[2:]
        mode = "logit" if "--logit" in args else "add"
        names = [a for a in args if not a.startswith("-")] or \
            ["matches_28d", "event_gwp", "event_sets_lost"]
        print(f"antisymmetric application of {names}, rolling folds:")
        antisym(rows, names, mode=mode)
        return 0
    if cmd == "combined":
        rows = load_cache()
        names = sys.argv[2:] or ["matches_28d", "event_gwp"]
        print(f"combined curves {names}, rolling folds:")
        combined(rows, names)
        return 0
    if cmd == "build":
        build_cache()
        return 0
    if cmd == "reliability":
        rows = load_cache()
        print("split-half reliability of a player's own residual mean "
              "(rule 17):")
        for lbl, (n, r_, full) in trait_reliability(rows).items():
            if r_ is None:
                print(f"  {lbl:<14} too few players ({n})")
            else:
                print(f"  {lbl:<14} {n:>5} players with 40+ rows   "
                      f"split-half r {r_:+.3f}   full-sample reliability "
                      f"{full:.3f}")
        return 0
    rows = load_cache()
    print(f"{len(rows):,} cached player-rows")
    names = sys.argv[2:] or list(BUCKETS)
    results = {}
    for n in names:
        if n not in BUCKETS:
            print(f"  unknown covariate {n!r}")
            continue
        results[n] = report(rows, n)
    print("\n  summary (out-of-sample change in log loss; negative is better)")
    for n, d in sorted((k, v) for k, v in results.items() if v is not None):
        print(f"    {n:<18} {d:+.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
