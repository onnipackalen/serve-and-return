"""
Price a matchup from as many pre-match variables as you can supply.

    python3 price.py "Sinner" "Alcaraz" --surface Clay --best-of 5
    python3 price.py Djokovic Alcaraz --surface Grass --date 2025-07-01
    python3 price.py --list Medvedev

Every variable in data_plan.md is accepted.  Only some of them currently
move the number, and the output says which -- a tool that silently ignored
--temp-c would be worse than one that refused it.  As tiers get fitted,
variables graduate from RECORDED to LIVE and nothing else has to change.

Ratings are opponent-adjusted (ratings.fit_iterative) and computed strictly
from matches BEFORE --date, so a historical date gives the price you would
have had on the day, not one informed by the result.
"""

import argparse
import datetime as dt
import math
import json
import os
import re
import sys
from collections import defaultdict

import players
from fastmatch import win_prob
from load import load, tour_avg, data_asof
from ratings import fit_iterative, TOUR_AVG
from fit import to_day, name_map

CACHE_DIR = os.path.join(os.path.dirname(__file__) or ".", "cache")
SURFACE_SHRINK = 4000.0     # service points before a surface rating stands alone
# Fitted by backtest.py on the training half; see fitted_params.json.
try:
    with open(os.path.join(os.path.dirname(__file__) or ".",
                           "fitted_params.json")) as _fh:
        _FP = json.load(_fh)
except OSError:
    _FP = {}
DEFAULT_FORM_SD = _FP.get("form_sd", 0.020)

# Nonlinear residual curves (tools/curves.py).  Separate from
# fitted_params.json because these are shapes, not scalars: a single weight
# fitted to "wins banked at this event" returns ~zero because the effect is
# a hump, and declaring it absent was the wrong answer.
try:
    with open(os.path.join(os.path.dirname(__file__) or ".",
                           "fitted_curves.json")) as _fh:
        _FC = json.load(_fh)
except OSError:
    _FC = {"curves": {}, "buckets": {}}
# The magnitude the curves are applied at: a log-odds shift of 4*k*adj.
# k=1 is the natural value (A moves by what its curve says, B by the
# negative); tools/curves.py measures k on rolling folds and writes the
# adopted value into fitted_curves.json, so this file and the harness read
# one number.
CURVE_K = float(_FC.get("k", 1.0))
# entry codes, for --entry and the report line
F_ENTRY = {"": 0, "Q": 1, "WC": 2, "LL": 3, "PR": 4, "SE": 5}
ENTRY_CHOICES = ("main", "Q", "WC", "LL", "PR", "SE")


def _bucket(name, v):
    edges = _FC.get("buckets", {}).get(name)
    if not edges or v is None:
        return None
    for i in range(len(edges) - 1):
        if edges[i] <= v < edges[i + 1]:
            return i
    return None


def player_curve_adj(work):
    """Sum of the fitted residual curves for one player's workload."""
    tot = 0.0
    for name, curve in _FC.get("curves", {}).items():
        b = _bucket(name, work.get(name))
        if b is not None and str(b) in curve:
            tot += curve[str(b)]
    return tot


class Unavailable(LookupError):
    """A player the news says is not playing.  Refuse rather than price."""


def news_adjust(book, a_id, b_id, asof_day):
    """(per-player rating deltas, detail) from data/news.json, or (None, None).

    The one input here that is not derived from the archive, so it is the one
    that gets validated on the way in (news.validate) and logged on the way
    out (news.log_applied). Everything else in this model can be re-derived
    from the CSVs; this cannot, which is exactly why it is the channel worth
    having -- and exactly why it is held to a stricter standard.
    """
    if not _FP.get("news_w", 0.0):
        return None, None
    try:
        import news as N
    except Exception:                                          # noqa: BLE001
        return None, None
    import features as F
    out, detail = {}, {}
    for pid in (a_id, b_id):
        rec = N.get(pid)
        if not rec:
            continue
        if not rec.get("available", True):
            raise Unavailable(book.names.get(pid, pid))
        try:
            since = N._day(rec["as_of"])
        except Exception:                                      # noqa: BLE001
            since = asof_day
        played = sum(1 for m in F.match_log()
                     if pid in (m.w_id, m.l_id) and m.completed
                     and F._day(m.tourney_date) >= since)
        ds, dr, det = N.weight(rec, book.form_sd(pid), asof_day,
                               played_since=played,
                               scale=_FP.get("news_w", 1.0))
        if det and (ds or dr or det["retire"] or det["var_x"] > 1.0):
            # three levers: the rating shift (serve_probs), the volatility
            # multiplier and the retirement risk (both applied in price)
            out[pid] = {"d_serve": ds, "d_ret": dr,
                        "var_x": det["var_x"], "retire": det["retire"]}
            detail[pid] = dict(det, name=book.names.get(pid, pid))
    return (out or None), (detail or None)


def event_update(book, a_id, b_id, asof_day, tournament, weight=None,
                 rnd=None):
    """How this event so far should move both players' ratings, before pricing.

    Ratings are refit quarterly, so inside a tournament nobody's rating
    moves.  A player who has already won three matches here has shown
    something the price does not know -- measured at +0.0195, 3.7 SE, for
    underdogs with wins banked (tools/round_effect.py).

    The update is a shrinkage step on the OPPONENT-ADJUSTED residual: a
    player who won 65% of serve points against a weak returner has not shown
    what a player who did it against a good one has, and comparing raw rates
    to a tour average would mostly measure the draw.  The denominator is the
    rating's own effective sample size, so a long record barely moves and a
    thin one moves a lot, with no separate tuning.

    Worth -0.00267 at a paired t of +6.82 with the weight swept
    (tools/inevent.py); the optimum is interior, w = 4 is worse than w = 2.
    """
    w = _FP.get("event_update_w", 0.0) if weight is None else weight
    if not w or not tournament:
        return None
    import features as F
    key = F.norm_event(tournament)
    here = [m for m in F.match_log()
            if F.norm_event(m.tname) == key and m.has_stats
            and 0 <= asof_day - F._day(m.tourney_date) <= 21
            and (m.w_id in (a_id, b_id) or m.l_id in (a_id, b_id))]

    # LEAKAGE GUARD.  The archive dates a match by when its TOURNAMENT
    # started, not when the match was played, so "matches at this event
    # before today" cannot be expressed as a date filter -- every round of
    # Wimbledon carries the same date.  Pricing a quarter-final as of a
    # historical day would otherwise fold in the final.
    #
    # Live, there is nothing to guard: the log holds completed matches and
    # the one being priced has not happened.  Historically there is, so a
    # round must be supplied, and rounds at or after it are dropped.
    today = (dt.date.today() - dt.date(2000, 1, 1)).days
    if asof_day < today - 1:
        if rnd is None:
            return None                     # refuse rather than leak
        cap = F.ROUND_ORDER.get(rnd, 9)
        here = [m for m in here if F.ROUND_ORDER.get(m.rnd, 9) < cap]
    if not here:
        return None
    acc = {}
    for m in here:
        for pid, opp, svpt, won, osv, own in (
                (m.w_id, m.l_id, m.w_svpt, m.w_won, m.l_svpt, m.l_won),
                (m.l_id, m.w_id, m.l_svpt, m.l_won, m.w_svpt, m.w_won)):
            if pid in (a_id, b_id):
                event_bank(book, acc, pid, opp, svpt, won, osv, own)
    return event_shift(book, acc, w)


def event_bank(book, acc, pid, opp, svpt, won, osv, own):
    """Fold one completed match into `acc`, the running evidence at an event.

    acc[pid] = [serve pts, serve residual, return pts, return residual,
    matches], residuals against the OPPONENT-ADJUSTED expectation from the
    overall ratings.  The live path (event_update) banks the event's matches
    from the log; backtest.walk_forward banks each match right after pricing
    it.  Same arithmetic, one function -- rule 19.
    """
    if svpt <= 0 or osv <= 0:
        return
    o = book.overall

    def exp_rate(p, q):
        return min(max(TOUR_AVG + (o["serve"].get(p, TOUR_AVG) - TOUR_AVG)
                       - (o["ret"].get(q, 1 - TOUR_AVG) - (1 - TOUR_AVG)),
                       .05), .95)

    e = acc.setdefault(pid, [0.0, 0.0, 0.0, 0.0, 0])
    e[0] += svpt
    e[1] += won - exp_rate(pid, opp) * svpt
    e[2] += osv
    e[3] += (osv - own) - (1 - exp_rate(opp, pid)) * osv
    e[4] += 1


def event_shift(book, acc, weight):
    """acc (see event_bank) -> {pid: {d_serve, d_ret, pts, matches}}, or None.

    A shrinkage step: the denominator is the rating's own effective sample
    size, so a long record barely moves and a thin one moves a lot, with no
    separate tuning.  `weight` is the one free parameter (event_update_w).
    """
    if not weight or not acc:
        return None
    den_all = book.overall["den"]
    out = {}
    for pid, (spts, sres, rpts, rres, n) in acc.items():
        den = den_all.get(pid, 0.0)
        ds = weight * sres / (den + spts) if spts else 0.0
        dr = weight * rres / (den + rpts) if rpts else 0.0
        if spts or rpts:
            out[pid] = {"d_serve": ds, "d_ret": dr, "pts": spts, "matches": n}
    return out or None


def curve_adjustment(a_id, b_id, asof_day, tournament=None, entry=None,
                     surface=None):
    """(net shift for A, per-player detail).

    ANTISYMMETRIC by construction.  The curves were fitted per player, but a
    match's two probabilities must sum to one, so an adjustment given to A
    has to be taken from B.  Applying each side's raw adjustment
    independently scores better on winner-oriented rows and is nonsense:
    it adds probability mass without removing any.

    The magnitude used to be (adj_a - adj_b)/2.  Any k(adj_a - adj_b) is
    antisymmetric, so the 1/2 was never required -- it was a conservative
    choice that halved every fitted effect on top of the shrinkage
    fit_curve already applies.  Measured out of sample on rolling folds
    (`tools/curves.py antisym --logit`), k=1 beats k=1/2 on 4 folds of 4:
    -0.00335 against -0.00205.  The optimum is flat from k=0.75 to k=1.5,
    so k=1 is both the natural value -- A moves by exactly what the curve
    says, and B by the negative, which is all coherence demands -- and
    inside the measured plateau.  No new tunable.
    """
    if not _FC.get("curves"):
        return 0.0, None
    import features as F
    ea, eb = entry if entry else (None, None)
    wa = F.live_workload(a_id, asof_day, tournament, entry=ea, surface=surface)
    wb = F.live_workload(b_id, asof_day, tournament, entry=eb, surface=surface)
    # the ranking gap needs both players; derived here exactly as build()
    # derives it (log10 own rank minus log10 opponent rank)
    la, lb = wa.get("log_rank"), wb.get("log_rank")
    wa["rank_gap"] = (la - lb) if (la is not None and lb is not None) else None
    wb["rank_gap"] = (lb - la) if (la is not None and lb is not None) else None
    adj_a, adj_b = player_curve_adj(wa), player_curve_adj(wb)
    return adj_a - adj_b, (wa, wb, adj_a, adj_b)

# name -> (status, what it does / what it is waiting on)
VARIABLES = {
    "player_a":    ("LIVE", "required"),
    "player_b":    ("LIVE", "required"),
    "date":        ("LIVE", "ratings decay to this date; nothing after it is used"),
    "surface":     ("LIVE", "surface-specific ratings, shrunk toward overall"),
    "best_of":     ("LIVE", "3 or 5 -- changes variance, favourite gains in Bo5"),
    "form_sd":     ("LIVE", "match-day ability spread; widens the distribution"),
    "entry_a/b":   ("LIVE", "how each player got into the draw -- Q, WC, LL, "
                            "PR, SE or main; qualifiers beat their price, "
                            "protected-ranking entrants miss it. The results "
                            "feed cannot say, so it is asked (--entry-a/-b)"),
    "indoor":      ("LIVE", "closed roof zeroes every weather term"),
    "temp_c":      ("LIVE", "folds into air density with elevation + humidity"),
    "elevation_m": ("LIVE", "air density; the cheapest real edge"),
    "humidity":    ("LIVE", "air density; sign is empirical, ball beats physics"),
    "wind_kph":    ("RECORDED", "M5 -- raises DFs, lowers 1st-serve %"),
    "roof_closed": ("RECORDED", "M5 -- if closed, weather terms must be zeroed"),
    "level":       ("RECORDED", "M2b -- G/M/A/D/F/C"),
    "round":       ("IGNORED",  "cancels to EXACTLY zero -- both players share "
                                "the round, so it cannot move an antisymmetric "
                                "price. Later rounds do score worse, but the "
                                "market loses there too"),
    "rest_days_a": ("RECORDED", "M6 -- 0-1 tired, 2-4 optimal, 14+ rusty"),
    "rest_days_b": ("RECORDED", "M6 -- same"),
    "minutes_a":   ("RECORDED", "M6 -- cumulative load this tournament"),
    "minutes_b":   ("RECORDED", "M6 -- same"),
    "h2h":         ("IGNORED",  "near-zero once ability is controlled; the market "
                                "overweights it, which is the edge"),
}


class Unknown(LookupError):
    """No player matched.  Carries the nearest names for the error message."""

    def __init__(self, query, suggestions=()):
        super().__init__(query)
        self.query = query
        self.suggestions = list(suggestions)

    def __str__(self):
        s = players.suggest_line(self.suggestions)
        return (f"no player matching {self.query!r}"
                + (f"  --  did you mean: {s}?" if s else
                   "  --  try a surname, or `tennis.py find <name>`"))


class Book:
    """Everything needed to price, loaded from weights.json.

    weights.py is the single fitting entry point -- overall ratings,
    per-player surface abilities and per-player form volatility all come
    from one derivation, so pricing never refits and never disagrees with
    the weights you can inspect.
    """

    @staticmethod
    def cache_path(asof_day=None):
        """Where the weights for this day live.  A historical date needs its
        own derivation, or the ratings would contain matches played after the
        date being priced."""
        import weights as W
        today = (dt.date.today() - dt.date(2000, 1, 1)).days
        day = today if asof_day is None else asof_day
        return day, (W.CACHE if abs(day - today) <= 7 else
                     os.path.join(CACHE_DIR, f"weights_{day}.json"))

    def __init__(self, asof_day=None, rebuild=False, verbose=False,
                 weights=None):
        import weights as W
        # Fail here rather than deep inside a fit. Without this the price path
        # printed a full, confident matchup built from the prior alone -- a
        # fabricated number, which is far worse than an error.
        if weights is None:
            from load import require_data
            require_data("pricing")
        if weights is not None:
            # a derivation handed over directly -- this is how the
            # walk-forward harness prices every historical block through
            # exactly this class, so it cannot drift from the CLI
            w = weights
        else:
            day, path = self.cache_path(asof_day)
            os.makedirs(CACHE_DIR, exist_ok=True)
            w = None if rebuild else W.load_weights(path)
            # a weights file from before the shared derivation (2026-09-11)
            # has no long-window block; pricing from it would silently drop
            # the surface carry-over, so treat it as stale and re-derive
            if w is not None and "long" not in w:
                w = None
            if w is None:
                if verbose:
                    print(f"deriving weights as of day {day} (one-off) ...",
                          file=sys.stderr)
                w = W.build(day, verbose=verbose, path=path)
        self.w = w
        self.asof = w["asof"]
        self.overall = w["overall"]
        # long-window overall rating, for carrying recent form onto the
        # surface rating; absent from a weights.json older than 2026-09-11
        self.long = w.get("long")
        self.names = w.get("names", {})
        self.form = w["form"]
        self.surface = w["surface"]
        self.tour_form_sd = w.get("tour_form_sd", 0.035)
        # carry the recent form shift onto the surface rating (Book.rating).
        # An attribute rather than a constant so the harness can switch it
        # off and measure what it is worth.
        self.carry = _FP.get("surface_carry", True)

    def prominence(self, pid):
        """How likely this is the player someone meant, for tie-breaking.

        Career matches first, recency-weighted service points as the
        tiebreak.  Points alone decay with the 270-day half-life, which would
        hand "Murray" to whichever Murray played most recently rather than to
        Andy.
        """
        return (self.form.get(pid, {}).get("matches", 0) * 1000.0
                + self.overall["den"].get(pid, 0.0))

    def candidates(self, query, limit=8):
        """Ranked matches for a typed name.  See players.search."""
        out = players.search(self.names, query, self.prominence, limit=limit)
        for c in out:
            c["pts"] = self.overall["den"].get(c["id"], 0.0)
            c["matches"] = self.form.get(c["id"], {}).get("matches", 0)
        return out

    def resolve(self, query):
        """(id, name, [runners-up]) from anything a person would type.

        Surname, full name, initials, reversed order and typos all resolve;
        ties break on activity, so "Zverev" is Alexander.  Raises Unknown
        (with suggestions attached) rather than exiting, so the prompt can
        offer a retry instead of dying.
        """
        c = self.candidates(query)
        if not c:
            raise Unknown(query, players.nearest(
                self.names, query, self.prominence))
        return c[0]["id"], c[0]["name"], [x["name"] for x in c[1:4]]

    def rating(self, pid, surface=None, carry=None):
        """(serve, ret, n, surface_weight, on_surface_n).

        Surface ability is the empirical-Bayes combination derived in
        weights.py -- on-surface record combined with off-surface record,
        weighted by how precisely each is measured.  No hand-picked constant.

        It is measured on a LONG window (1,095-day half-life, thin data), so
        it is not substituted for the current rating -- that discards the
        whole point of the fitted 270-day half-life and measured WORSE than
        tour-wide (t = -3.14).  Each player's recent form shift, the current
        overall rating minus the long-window one, is carried onto their
        surface ability instead (t = +4.54).  The backtest always priced this
        way; the CLI did not until 2026-09-11, which is the drift rule 19
        warns about.
        """
        o = self.overall
        s = o["serve"].get(pid, TOUR_AVG)
        r = o["ret"].get(pid, 1 - TOUR_AVG)
        n = o["den"].get(pid, 0.0)
        e = self.surface.get(pid, {}).get(surface) if surface else None
        if not e:
            return s, r, n, 0.0, 0.0
        carry = self.carry if carry is None else carry
        ds = dr = 0.0
        if carry and self.long:
            import weights as W
            cap = W.CARRY_CAP
            ds = max(-cap, min(cap, s - self.long["serve"].get(pid, s)))
            dr = max(-cap, min(cap, r - self.long["ret"].get(pid, r)))
        return e["serve"] + ds, e["ret"] + dr, n, e["w_serve"], e["n"]

    def stage_serve(self, a, b):
        """Serve rate for A against B from the THREE-STAGE decomposition.

        A serve is two decisions, not one: does the first land, and is the
        point won -- and the second-serve point is a different game again.
        Each stage carries its own opponent adjustment, so a returner who is
        differentially good against second serves can be expressed, which a
        single additive number cannot do at any weight.

        Returns None when the stages are absent (an older weights.json) OR
        when either player has no stage rating, so the caller falls back to
        the single-number path rather than guessing.  Substituting the tour
        average for a missing stage rating -- which this did until
        2026-09-11 -- wipes out the player's level exactly when the single
        number knows it, and cost +0.0068 nats in the shipped path.
        """
        st = self.w.get("stages")
        if not st or len(st) < 3:
            return None
        out = {}
        for name in ("land", "first", "second"):
            m = st.get(name)
            if not m or a not in m["serve"] or b not in m["ret"]:
                return None
            avg = m["avg"]
            sa = m["serve"][a]
            rb = m["ret"][b]
            out[name] = min(max(avg + (sa - avg) - (rb - (1 - avg)),
                                0.02), 0.99)
        f = out["land"]
        return f * out["first"] + (1 - f) * out["second"]

    def form_sd(self, pid, scale=1.0, floor=0.015):
        return scaled_form_sd(self.form.get(pid, {}).get("form_sd"), scale,
                              self.tour_form_sd, floor)


def scaled_form_sd(f, scale, tour_sd, floor=0.015):
    """A player's match-day volatility as the recursion consumes it: their
    own derived form_sd (or the tour's, when they have none) times the
    fitted form_scale, floored."""
    return max((f if f else tour_sd) * scale, floor)


DENS_CAP = 0.03             # clamp on the symmetric air-density shift


def _clamp(p):
    return min(max(p, .35), .90)


def serve_probs(book, a_id, b_id, surface=None, stages=None, ev=None,
                nws=None, carry=None):
    """The two serve-point probabilities the recursion consumes, and how.

    THE ONE PLACE the rating layer becomes a matchup.  backtest.walk_forward
    prices every historical match through this function too, so the harness
    cannot drift from what ships (rule 19).  Everything that moves a rating
    happens here, in this order:

      1. surface        the empirical-Bayes surface rating with the recent
                        form shift carried onto it (Book.rating); both
                        players on it or neither, never one of each
      2. news           a shift to both ratings (news.py, a prior)
      3. the event      the run so far, as a shrinkage step (event_shift)
      4. three stages   the level comes from the recombined stage fits;
                        everything above is kept as a delta on top of it.
                        OFF since 2026-09-11: worth -0.00195 alone, it
                        costs +0.00137 in company (fitted_params
                        three_stage_serve); `stages` defaults to that flag

    `stages` / `carry` default to what fitted_params.json ships, so the
    CLI, the app, the simulator and the harness all read the same switch.
    """
    if stages is None:
        stages = _FP.get("three_stage_serve", False)
    sa, ra, na, wa, nsa = book.rating(a_id, surface, carry)
    sb, rb, nb, wb, nsb = book.rating(b_id, surface, carry)
    if surface and not (wa and wb):
        # both on the surface split, or neither.  One player on a
        # long-window surface rating against another on the current overall
        # rating is not a fair matchup, and the harness never priced one;
        # the CLI did, until 2026-09-11.
        sa, ra, na, wa, nsa = book.rating(a_id, None)
        sb, rb, nb, wb, nsb = book.rating(b_id, None)
    ta = tour_avg(surface) if (surface and wa and wb) else TOUR_AVG
    rbar = 1 - ta
    pa = _clamp(ta + (sa - ta) - (rb - rbar))
    pb = _clamp(ta + (sb - ta) - (ra - rbar))

    # player news, folded in exactly as the in-event update is: a shift to
    # the two ratings, before the stage decomposition
    if nws:
        # NOT na/nb: those are the two players' service-point counts,
        # unpacked from book.rating above and returned at the bottom.
        n_a, n_b = nws.get(a_id, {}), nws.get(b_id, {})
        pa = _clamp(pa + n_a.get("d_serve", 0.0) - n_b.get("d_ret", 0.0))
        pb = _clamp(pb + n_b.get("d_serve", 0.0) - n_a.get("d_ret", 0.0))

    # the event so far, folded into both ratings
    if ev:
        da, db = ev.get(a_id, {}), ev.get(b_id, {})
        pa = _clamp(pa + da.get("d_serve", 0.0) - db.get("d_ret", 0.0))
        pb = _clamp(pb + db.get("d_serve", 0.0) - da.get("d_ret", 0.0))

    # The three-stage serve supplies the LEVEL; surface, news and the event
    # stay a delta on top of it.  Done this way the surface machinery --
    # empirical Bayes over a 1,095-day half-life -- is untouched, and the
    # decomposition replaces only the quantity it was measured against.
    stage_pa = stage_pb = None
    if stages:
        t3a, t3b = book.stage_serve(a_id, b_id), book.stage_serve(b_id, a_id)
        if t3a is not None and t3b is not None:
            o = book.overall
            oa = o["serve"].get(a_id, TOUR_AVG)
            ob = o["serve"].get(b_id, TOUR_AVG)
            ora = o["ret"].get(a_id, 1 - TOUR_AVG)
            orb = o["ret"].get(b_id, 1 - TOUR_AVG)
            base_a = TOUR_AVG + (oa - TOUR_AVG) - (orb - (1 - TOUR_AVG))
            base_b = TOUR_AVG + (ob - TOUR_AVG) - (ora - (1 - TOUR_AVG))
            stage_pa, stage_pb = t3a, t3b
            pa = _clamp(t3a + (pa - base_a))
            pb = _clamp(t3b + (pb - base_b))
    return {"pa": pa, "pb": pb, "tour_avg": ta,
            "stage_serve": (stage_pa, stage_pb),
            "a": (sa, ra, na, wa, nsa), "b": (sb, rb, nb, wb, nsb)}


def match_prob(pa, pb, best_of, fa, fb, dens=0.0, dens_w=None):
    """(P(A), pa, pb, density shift, dens_w): the recursion, after air density.

    `dens` is venues.density_index -- negative means thin air.  It shifts
    BOTH serve probabilities by the same amount because the conditions are
    shared: less drag, a faster ball, both players hold more easily.  Being
    symmetric it barely moves the moneyline (worth ~0.00006); it is carried
    because the games-total model needs the same plumbing.  Shared with
    backtest.price_player, where dens_w is the thing being fitted.
    """
    dw = _FP.get("dens_w", 0.0) if dens_w is None else dens_w
    shift = 0.0
    if dw and dens:
        shift = max(-DENS_CAP, min(DENS_CAP, dw * dens))
        pa = _clamp(pa - shift)                  # negative index -> serve up
        pb = _clamp(pb - shift)
    return win_prob(pa, pb, best_of, form_sd=fa, form_sd_b=fb), pa, pb, shift, dw


def price(book, a_id, b_id, surface=None, best_of=3, form_scale=None,
          calibrate=True, dens=0.0, curve_adj=0.0, stages=None, ev=None,
          nws=None, dens_w=None):
    """Fair probability for A: serve_probs -> match_prob -> curves -> calibration.

    Every layer that moves a number lives in one of the two shared functions
    above, which the backtest prices through as well.  What is left here is
    the two layers that are FITTED ON the backtest's output and so cannot be
    inside it: the residual curves and the calibration slope.
    """
    scale = _FP.get("form_scale", 1.0) if form_scale is None else form_scale
    sp = serve_probs(book, a_id, b_id, surface, stages=stages, ev=ev, nws=nws)
    fa, fb = book.form_sd(a_id, scale), book.form_sd(b_id, scale)
    if nws:
        # a fitness doubt is a WIDER range of outcomes, not only a lower
        # mean: the report's variance multiplier widens the form draw
        fa *= nws.get(a_id, {}).get("var_x", 1.0)
        fb *= nws.get(b_id, {}).get("var_x", 1.0)
    p_raw, pa, pb, shift, dw = match_prob(sp["pa"], sp["pb"], best_of, fa, fb,
                                          dens, dens_w)
    ta = sp["tour_avg"]
    stage_pa, stage_pb = sp["stage_serve"]
    sa, ra, na, wa, nsa = sp["a"]
    sb, rb, nb, wb, nsb = sp["b"]
    # The curves were fitted on residuals of exactly this quantity -- after
    # density, before calibration -- so this is where they belong.
    #
    # They are applied as a shift in LOG-ODDS, not added to the probability.
    # Additive cannot be right in the tails: a -0.038 shift on a 3.3%
    # underdog takes the price NEGATIVE, and the old clamp then quoted
    # 1e-6 -- fair odds of a million to one.  That is not a hypothetical;
    # one such match cost 13.8 nats and by itself made a whole test fold
    # prefer a weaker adjustment.  dp/dz = p(1-p) = 1/4 at p = 0.5, so a
    # log-odds shift of 4*adj reproduces the fitted residual where the
    # curves were fitted and tapers toward the tails, which is what a
    # bucket-average residual should do.  Measured: -0.00205 against
    # -0.00170 additive at the same magnitude, 4 folds of 4.
    p_before = p_raw
    if curve_adj:
        z = math.log(min(max(p_raw, 1e-9), 1 - 1e-9) /
                     (1 - min(max(p_raw, 1e-9), 1 - 1e-9)))
        p_raw = 1.0 / (1.0 + math.exp(-(z + 4.0 * CURVE_K * curve_adj)))
    b = _FP.get("calibration_b")
    # b == 1.0 is the identity transform, i.e. calibration deliberately off.
    # Reporting it as "applied" made the output claim a layer moved the
    # number when it provably did nothing.
    if b is not None and abs(b - 1.0) < 1e-9:
        b = None
    p = p_raw
    if calibrate and b:
        z = math.log(min(max(p_raw, 1e-9), 1-1e-9) /
                     (1 - min(max(p_raw, 1e-9), 1-1e-9)))
        p = 1.0 / (1.0 + math.exp(-b * z))
    # retirement risk, folded in LAST: it is an event outside the point
    # model, not a residual of it, so the curves and the calibration slope
    # must not see it.  A retirement is a loss.
    r_a = r_b = 0.0
    p_cal = p
    if nws:
        r_a = nws.get(a_id, {}).get("retire", 0.0) or 0.0
        r_b = nws.get(b_id, {}).get("retire", 0.0) or 0.0
        if r_a or r_b:
            p = (1 - r_a) * (1 - r_b) * p + (1 - r_a) * r_b + 0.5 * r_a * r_b
    return {"p_a": p, "p_raw": p_raw, "p_cal": p_cal, "pa_serve": pa,
            "pb_serve": pb, "retire": (r_a, r_b),
            "tour_avg": ta, "form": (fa, fb), "cal_b": b if calibrate else None,
            "dens": dens, "dens_shift": shift, "dens_w": dw,
            "curve_adj": curve_adj, "curve_dp": p_raw - p_before,
            "stage_serve": (stage_pa, stage_pb), "event_update": ev,
            "news": nws,
            "a": (sa, ra, na, wa, nsa), "b": (sb, rb, nb, wb, nsb)}


# ----------------------------------------------------------- presentation

def market_view(p_a, odds_a, odds_b):
    """The model's price beside a bookmaker's two decimal odds.

    The margin is removed proportionally -- the same devig tools/odds/m4.py
    scores against -- so `edge_a` is the model minus the market's OPINION,
    in probability, and `overround` is the markup that was removed.  It is
    a comparison, not a stake: against Pinnacle closing the model has been
    measured ~0.02 nats BEHIND, and all of that gap lives in confident
    disagreement, so a large edge here is a question to look into, not
    money.  None when the odds are missing or not odds.
    """
    try:
        oa, ob = float(odds_a), float(odds_b)
    except (TypeError, ValueError):
        return None
    if not (oa > 1.0 and ob > 1.0):
        return None
    qa, qb = 1.0 / oa, 1.0 / ob
    ia = qa / (qa + qb)
    return {"odds_a": oa, "odds_b": ob, "implied_a": ia, "implied_b": 1.0 - ia,
            "overround": qa + qb - 1.0,
            "edge_a": p_a - ia, "edge_b": (1.0 - p_a) - (1.0 - ia)}


SURFACES = {"hard": "Hard", "clay": "Clay", "grass": "Grass",
            "carpet": "Carpet"}
RECORDED_KEYS = ("wind_kph", "level", "round", "rest_days_a", "rest_days_b",
                 "minutes_a", "minutes_b")


def _truthy(v):
    """--indoor yes / true / 1 all mean the roof is shut."""
    return str(v).strip().lower() in ("1", "true", "yes", "y", "closed") \
        if v is not None else False


def asof_date(book):
    return dt.date(2000, 1, 1) + dt.timedelta(days=book.asof)


def resolve_conditions(tournament, day, temp_c=None, elevation_m=None,
                       humidity=None, indoor=None):
    """(density index, one-line explanation) for a match.

    Two ways in.  Name a tournament and the venue table plus the cached
    weather supply everything.  Or give the numbers directly, which is what
    you want for a venue the table has never seen, or to ask what a hotter
    afternoon would do to the same match.

    Indoor is not a small correction -- a closed roof means there is no
    weather effect at all, so feeding outdoor conditions to an indoor match
    is pure noise.  Those return 0.0 and say so.
    """
    import venues
    if temp_c is not None and elevation_m is not None:
        rh = 0.5 if humidity is None else (
            humidity / 100.0 if humidity > 1 else humidity)
        if indoor:
            return 0.0, f"indoor -- weather ignored ({elevation_m:.0f} m)"
        d = venues.density_index(temp_c, elevation_m, rh)
        return d, (f"{temp_c:.0f}C, {rh:.0%} rh, {elevation_m:.0f} m "
                   f"-> density {d:+.4f}")
    if not tournament:
        return 0.0, None
    v = venues.lookup(tournament)
    if not v:
        return 0.0, f"no venue on file for {tournament!r}"
    from weather import conditions
    date = (dt.date(2000, 1, 1) + dt.timedelta(days=day)).strftime("%Y%m%d")
    c = conditions(tournament, date)
    if c is None:
        return 0.0, (f"{tournament}: {v[2]:.0f} m, but no weather cached for "
                     f"{date} -- run `python3 weather.py fetch`")
    if c["indoor"]:
        return 0.0, f"{tournament}: indoor -- weather ignored"
    # wind is shown but does NOT move the number: it acts through a different
    # mechanism than density (it disrupts the ball toss rather than changing
    # drag) and has no fitted weight yet.  Reporting it without using it is
    # the point -- see VARIABLES.
    w = c.get("wind_kph")
    return c["density_index"], (
        f"{tournament}: {c['temp_c']:.0f}C, {c['humidity']:.0%} rh, "
        f"{c['elevation_m']:.0f} m -> density {c['density_index']:+.4f}"
        + (f"   [wind {w:.0f} km/h, recorded only]" if w else ""))


_DATA_END = []          # cached; the CSV scan is cheap but not free


def staleness(book):
    """How far the price runs past the last match in the data, or None.

    A historical date is never stale -- the data is ahead of it.  A price for
    today is only as fresh as the mirror, and the mirror stopped in May 2026,
    so this is the difference between a number you can use and a number that
    has not seen a Grand Slam.
    """
    if not _DATA_END:
        _DATA_END.append(data_asof())
    end = _DATA_END[0]
    if not end:
        return None
    gap = (asof_date(book) - dt.date.fromisoformat(end)).days
    return (end, gap) if gap > 21 else None


def report(book, a, b, surface=None, best_of=3, form_scale=None,
           calibrate=True, recorded=None, out=sys.stdout, dens=0.0,
           dens_why=None, tournament=None, use_curves=True, entry=None):
    """Print one priced matchup.  `a`/`b` are candidate dicts from Book.

    Shared by the one-shot CLI and the prompt so the two can never drift.
    `entry` is (A's entry code, B's) -- Q, WC, LL, PR, SE or "main" -- the
    one curve input the live log cannot supply for a first-round match.
    """
    p_ = lambda s="": print(s, file=out)
    cadj, detail = (curve_adjustment(a["id"], b["id"], book.asof, tournament,
                                     entry=entry, surface=surface)
                    if use_curves else (0.0, None))
    ev = event_update(book, a["id"], b["id"], book.asof, tournament)
    try:
        nws, ndet = news_adjust(book, a["id"], b["id"], book.asof)
    except Unavailable as e:
        p_(f"\n{a['name']}  vs  {b['name']}")
        p_("-" * 64)
        p_(f"  NOT PRICED: the news on file says {e} is not playing.")
        p_("  Clear it with  tennis.py news --clear "
           f"{str(e).split()[-1]!r}  if that is stale.")
        return None
    r = price(book, a["id"], b["id"], surface, best_of, form_scale,
              calibrate=calibrate, dens=dens, curve_adj=cadj, ev=ev, nws=nws)
    an, bn = a["name"], b["name"]

    p_(f"\n{an}  vs  {bn}")
    p_("-" * 64)
    p_(f"  as of {asof_date(book)}   {surface or 'all surfaces'}   "
       f"best of {best_of}")
    st = staleness(book)
    if st:
        p_(f"  ! newest match in the data is {st[0]} -- {st[1]} days of "
           f"results are missing")
    for side, c in (("A", a), ("B", b)):
        if c.get("why") in ("close to full name", "close to surname",
                            "close to name"):
            p_(f"  ({side}: read {c['typed']!r} as {c['name']})")
        elif c.get("alts"):
            p_(f"  ({side}: also matched {', '.join(c['alts'])}"
               f" -- type a full name to pick)")

    for nm, (sv, rt, n, w, ns), f in ((an, r["a"], r["form"][0]),
                                      (bn, r["b"], r["form"][1])):
        tag = (f"surface w={w:.0%} on {ns:,.0f} pts" if w
               else "no surface split" if surface else "")
        p_(f"  {nm:<24} serve {sv:.4f}  return {rt:.4f}  "
           f"form_sd {f:.4f}  {tag}")

    p = r["p_a"]
    p_(f"\n  tour average serve here   {r['tour_avg']:.4f}")
    if dens_why:
        p_(f"  conditions                {dens_why}")
    if r["dens_shift"]:
        p_(f"  air density               both serves {-r['dens_shift']:+.4f} "
           f"(w={r['dens_w']:.2f}, symmetric)")
    p_(f"  point win prob on serve   {r['pa_serve']:.4f} / {r['pb_serve']:.4f}")
    if r.get("stage_serve") and r["stage_serve"][0] is not None:
        p_(f"  three-stage serve         {r['stage_serve'][0]:.4f} / "
           f"{r['stage_serve'][1]:.4f}  (serve in, won on 1st, won on 2nd, "
           f"each opponent-adjusted)")
    if ndet:
        for nm, pid in ((an, a["id"]), (bn, b["id"])):
            d = ndet.get(pid)
            if not d:
                continue
            bits = [f"severity {d['severity']}"]
            if d.get("issue"):
                bits.append(d["issue"][:28])
            bits.append(d["area"])
            bits.append(d["sourcing"])
            bits.append(f"{d['age_days']}d old, decay {d['decay']:.2f}")
            if d["played_since"]:
                bits.append(f"{d['played_since']} matches since")
            p_(f"  NEWS      {nm[:20]:<20} {', '.join(bits)}")
            nn = nws.get(pid, {})
            extra = ""
            if nn.get("var_x", 1.0) > 1.0:
                extra += f", form_sd x{nn['var_x']:.2f}"
            if nn.get("retire"):
                extra += f", retire {nn['retire']:.0%}"
            p_(f"            -> serve {nn.get('d_serve', 0):+.4f}, "
               f"return {nn.get('d_ret', 0):+.4f}{extra}   "
               f"({d['sources']} source(s), from the report's "
               f"{'impact block' if d.get('how') == 'impact' else 'severity'})")
            if d.get("reasoning"):
                p_(f"            {d['reasoning'][:110]}")
    if r.get("event_update"):
        for nm, pid in ((an, a["id"]), (bn, b["id"])):
            e = r["event_update"].get(pid)
            if e:
                p_(f"  in-event  {nm[:20]:<20} {e['matches']} here, "
                   f"{e['pts']:.0f} svc pts  -> serve {e['d_serve']:+.4f}, "
                   f"return {e['d_ret']:+.4f}")
    elif detail and tournament and _FP.get("event_update_w") and any(
            w.get("event_matches") for w in detail[:2]):
        # a run exists but none of it carries serve stats (the 2026 US Open
        # and Roland Garros publish results only), so there is nothing to
        # bank.  Say so rather than leave the line out.
        p_("  in-event                  matches here carry no serve stats "
           "-- the rating update has nothing to bank")
    if detail:
        wa, wb, adj_a, adj_b = detail
        for nm, w, ad in ((an, wa, adj_a), (bn, wb, adj_b)):
            gwp = ("-" if w["event_gwp"] is None
                   else f"{w['event_gwp']:.1%} games")
            ent = ""
            if "entry" in _FC.get("curves", {}):
                codes = {v: k for k, v in F_ENTRY.items()}
                ent = (", entry unknown" if w.get("entry") is None else
                       f", entry {codes.get(w['entry'], '?') or 'main'}")
            p_(f"  form/run  {nm[:20]:<20} {w['matches_28d']:>2} in 28d, "
               f"{w['event_matches']} here ({gwp}, {w['event_sets_lost'] or 0}"
               f" sets lost{ent})  -> {ad:+.4f}")
    if r["curve_adj"]:
        p_(f"  net curve adjustment      {r['curve_dp']:+.4f} "
           f"(log-odds {4 * CURVE_K * r['curve_adj']:+.4f}"
           f"{f', k={CURVE_K:g}' if CURVE_K != 1.0 else ''}; antisymmetric, "
           f"fitted shapes not weights)")
    # how much to trust THIS price, from what predicted error in the
    # odds-joined study: data thinness, match fitness, layoff
    try:
        import confidence as C
        min_pts = min(r["a"][2], r["b"][2])
        m28 = 99
        cb = 0
        if detail:
            wa, wb, _aa, _ab = detail
            m28 = min(wa["matches_28d"], wb["matches_28d"])
            cb = (wa.get("comeback") or 0) + (wb.get("comeback") or 0)
        f = C.features(min_pts, m28, cb)
        bnd = C.band(f)
        p_(f"\n  confidence  {bnd}  (measured deficit vs closing line "
           f"~{C.MEASURED_DEFICIT[bnd]:+.3f} nats; {C.tightness(p)} matchup)")
        p_(f"              {min_pts:,.0f} service pts on the thinner side, "
           f"{m28 if m28 < 99 else '?'} recent matches"
           + (", a player returning from layoff" if cb else ""))
        if ndet:
            worst = max(d["severity"] for d in ndet.values())
            # reported BESIDE the band, not folded into it.  The band's
            # measured deficits were fitted before this input existed, and
            # folding an unmeasured term into a measured scale is how the
            # tightness mistake happened.
            p_(f"              a fitness report is on file (severity "
               f"{worst}) -- NOT in the band above, which was measured "
               f"before this input existed")
    except Exception:                                          # noqa: BLE001
        pass
    if r["cal_b"]:
        p_(f"  calibration               raw {r['p_raw']:.4f} -> "
           f"{r['p_cal']:.4f}  (slope {r['cal_b']:.3f})")
    ra, rb = r.get("retire", (0.0, 0.0))
    if ra or rb:
        p_(f"  retirement risk           {an[:14]} {ra:.0%} / {bn[:14]} {rb:.0%}"
           f"  -> {r['p_cal']:.4f} becomes {p:.4f}  (a retirement is a loss)")
    p_(f"\n  P({an})  {p:.4f}    fair {1/p:.3f}")
    p_(f"  P({bn})  {1-p:.4f}    fair {1/(1-p):.3f}")

    live = ["surface=" + (surface or "all"), f"best_of={best_of}",
            f"as_of={asof_date(book)}", "per-player form_sd",
            "per-player surface weights",
            "calibration" if r["cal_b"] else "calibration OFF"]
    if r["dens_shift"]:
        live.append("air density")
    if r.get("stage_serve") and r["stage_serve"][0] is not None:
        live.append("three-stage serve")
    if r.get("event_update"):
        live.append("in-event rating update")
    if r.get("news"):
        live.append("player news (a PRIOR, not a fit -- see news.py)")
        try:
            import news as N
            N.log_applied({"asof": str(asof_date(book)), "a": a["id"],
                           "b": b["id"], "surface": surface,
                           "best_of": best_of, "p": r["p_a"],
                           "news": ndet, "shift": nws})
        except Exception:                                      # noqa: BLE001
            pass
    if r["curve_adj"]:
        live.append("form/run curves")
    p_(f"\n  moved the number : {', '.join(live)}")
    if recorded:
        p_(f"  RECORDED ONLY    : {', '.join(recorded)}")
        p_("     ^ accepted and ignored; those tiers are not fitted yet.")
    if _FP.get("calibration_b") is None:
        p_("\n  WARNING: no fitted calibration -- run backtest.py")
    elif not r["cal_b"]:
        m = _FP.get("calibration_b_measured")
        p_(f"\n  calibration is OFF by measurement"
           + (f" (slope {m:.3f} measured; applying it made test loss worse)"
              if m else ""))
    return r


def pick(book, typed):
    """Resolve a typed name into the candidate dict report() wants."""
    cands = book.candidates(typed)
    if not cands:
        raise Unknown(typed, players.nearest(book.names, typed,
                                             book.prominence))
    top = dict(cands[0], typed=typed)
    # only call out runners-up that genuinely tie -- a shared surname.  Fuzzy
    # near-misses are noise and get the "read X as Y" line instead.
    top["alts"] = ([c["name"] for c in cands[1:4]]
                   if players.ambiguous(cands) else [])
    return top


# --------------------------------------------------------------- the prompt

_VS = re.compile(r"\s+(?:vs\.?|versus|v\.?|-{1,2}|/)\s+", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_line(text, surface=None, best_of=3, date=None):
    """'Sinner vs Alcaraz clay bo5' -> (a, b, how, surface, best_of, date).

    Conditions can appear anywhere and are stripped before the names are
    split, so "clay Sinner vs Alcaraz" and "Sinner vs Alcaraz bo5 clay" both
    work.  `how` is "sep" when an explicit vs / - / separated the names,
    "bare" when two lone words were split on the guess that they are two
    surnames, and "one" when only one name was found.  The caller checks a
    "bare" split really resolves before trusting it, because "del potro" and
    "Auger Aliassime" are also two lone words.
    """
    words, keep = text.split(), []
    for w in words:
        lw = w.lower().strip(".,")
        if lw in SURFACES:
            surface = SURFACES[lw]
        elif lw in ("bo3", "bo5", "best-of-3", "best-of-5"):
            best_of = int(lw[-1])
        elif lw in ("indoor", "indoors"):
            surface = surface or "Hard"
        elif _DATE.match(lw):
            date = lw
        else:
            keep.append(w)
    line = " ".join(keep).strip()
    if not line:
        return None, None, "one", surface, best_of, date

    m = _VS.split(line, maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return m[0].strip(), m[1].strip(), "sep", surface, best_of, date
    # no separator: two bare surnames is the other thing people type
    toks = line.split()
    if len(toks) == 2:
        return toks[0], toks[1], "bare", surface, best_of, date
    return line, None, "one", surface, best_of, date


PROMPT_HELP = """
  Two players, any spelling -- surname, full name, initials, typos:
      Sinner vs Alcaraz              Djokovic Nadal          alcarez v sinner
  Add conditions anywhere on the line:
      Sinner vs Alcaraz clay bo5     Federer vs Nadal grass 2008-07-06
  Conditions:  hard | clay | grass | carpet    bo3 | bo5    YYYY-MM-DD
  Commands:
      surface clay      set the default surface (`surface off` to clear)
      bo5               set the default best-of
      date 2025-07-01   price as of a past date (`date today` to clear)
      at Cincinnati     price under that venue's conditions (`at off`)
      entry a Q         A came through qualifying (Q, WC, LL, PR, SE, main;
                        `entry off` clears both) -- the feed cannot tell
      find murray       list players matching a name
      who Ruud          why the model rates a player as it does
      ?                 this help          q        quit
"""


def prompt(book, surface=None, best_of=3, date=None, at=None):
    """Interactive loop.  `date` swaps the whole Book, since ratings as of a
    past date must be derived from matches before it."""
    print(f"\n{'=' * 64}")
    print(f"  Tennis pricing      {len(book.names):,} players, "
          f"rated as of {asof_date(book)}")
    print(f"{'=' * 64}")
    st = staleness(book)
    if st:
        print(f"  ! data stops {st[0]}; a price for today is {st[1]} days "
              f"stale")
    print("  Type two players, e.g.  Sinner vs Alcaraz clay bo5")
    print("  ?  help    q  quit")

    entry = [None, None]
    while True:
        bits = [s for s in (surface, f"bo{best_of}", date,
                            f"@{at}" if at else None,
                            (f"entry {entry[0] or '-'}/{entry[1] or '-'}"
                             if any(entry) else None)) if s]
        try:
            line = input(f"\n[{' '.join(bits)}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        low = line.lower()
        if low in ("q", "quit", "exit", ":q"):
            return 0
        if low in ("?", "h", "help"):
            print(PROMPT_HELP)
            continue

        cmd, _, rest = line.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd in ("at", "venue"):
            if rest.lower() in ("off", "none", ""):
                at = None
                print("  conditions off")
            else:
                d, why = resolve_conditions(rest, book.asof)
                print(f"  {why}")
                at = rest if d or "indoor" in (why or "") else at
            continue
        if cmd == "entry":
            toks = rest.split()
            if not toks or toks[0].lower() in ("off", "none"):
                entry = [None, None]
                print("  entry cleared")
            elif len(toks) == 2 and toks[0].lower() in ("a", "b") and \
                    toks[1].upper() in ENTRY_CHOICES + ("MAIN",):
                code = toks[1].upper()
                entry["ab".index(toks[0].lower())] = ("main" if code == "MAIN"
                                                      else code)
            else:
                print("  entry a Q   |   entry b WC   |   entry off   "
                      "(codes: main Q WC LL PR SE)")
            continue
        if cmd == "surface":
            if rest.lower() in ("off", "none", "all"):
                surface = None
            elif rest.lower() in SURFACES:
                surface = SURFACES[rest.lower()]
            else:
                print("  surfaces: hard, clay, grass, carpet, off")
            continue
        if cmd in ("bo", "best-of") or low in ("bo3", "bo5"):
            n = rest or low[-1]
            best_of = 5 if str(n).endswith("5") else 3
            continue
        if cmd == "date":
            want = None if rest.lower() in ("today", "now", "off") else rest
            if want and not _DATE.match(want):
                print("  date YYYY-MM-DD, or `date today`")
                continue
            try:
                book, date = rebook(want), want
            except Exception as e:                          # noqa: BLE001
                print(f"  {e}")
                continue
            print(f"  ratings now as of {asof_date(book)}")
            continue
        if cmd in ("find", "list", "search") and rest:
            show_list(book, rest)
            continue
        if cmd in ("who", "weights", "p") and rest:
            try:
                c = pick(book, rest)
            except Unknown as e:
                print(f"  {e}")
                continue
            subprocess_weights(c["name"])
            continue

        qa, qb, how, surf, bo, dt_ = parse_line(line, surface, best_of, date)
        if dt_ != date:
            try:
                book, date = rebook(dt_), dt_
            except Exception as e:                          # noqa: BLE001
                print(f"  {e}")
                continue
        try:
            a, b = resolve_pair(book, qa, qb, how, " ".join(
                w for w in line.split() if w.lower() not in ("vs", "v")))
        except (Unknown, NeedTwo) as e:
            print(f"  {e}")
            continue
        if a["id"] == b["id"]:
            print(f"  both names resolved to {a['name']} -- "
                  "name the opponent differently")
            continue
        dens, dens_why = resolve_conditions(at, book.asof)
        report(book, a, b, surf, bo, dens=dens, dens_why=dens_why,
               tournament=at, entry=tuple(entry))


class NeedTwo(LookupError):
    """The line named one player, not two."""

    def __init__(self, name=None):
        super().__init__(name)
        self.name = name

    def __str__(self):
        who = f"that is one player, {self.name}" if self.name else \
            "need two players"
        return f"{who} -- add an opponent, e.g. `{self.name or 'Sinner'} vs Alcaraz`"


def resolve_pair(book, qa, qb, how, whole):
    """(a, b) candidate dicts, or raise Unknown / NeedTwo.

    A "bare" two-word split is a guess, and the competing reading is that the
    two words are one player.  Whichever matches more strongly wins, so
    "Sinner Alcaraz" is a matchup and "del potro" is a request for an
    opponent -- not a spelling lecture about a player who does exist.
    """
    if not qb:
        one = book.candidates(whole, limit=1)
        raise NeedTwo(one[0]["name"] if one else None)
    if how == "bare":
        one = book.candidates(whole, limit=1)
        halves = [book.candidates(q, limit=1) for q in (qa, qb)]
        # "del potro" is an exact surname; "del" and "potro" are weak guesses.
        # Whichever reading matches more strongly is the one that was meant.
        if one and one[0]["score"] >= players.SUBSTRING and (
                not all(halves) or
                one[0]["score"] >= min(h[0]["score"] for h in halves)):
            raise NeedTwo(one[0]["name"])
    return pick(book, qa), pick(book, qb)


def rebook(date):
    """Book as of a date, quietly, with a one-line note if it has to derive.

    build() is chatty by design when you run the fit deliberately; inside the
    prompt that scrolls the price you asked for off the screen.  But a silent
    four-second pause looks like a hang, so say what is happening.
    """
    day = to_day(date.replace("-", "")) if date else None
    if not os.path.exists(Book.cache_path(day)[1]):
        print(f"  deriving ratings as of {date or 'today'} "
              f"(one-off, a few seconds) ...", flush=True)
    return Book(day, verbose=False)


def subprocess_weights(name):
    import subprocess
    subprocess.call([sys.executable,
                     os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "weights.py"), name])


def show_list(book, query):
    hits = book.candidates(query, limit=20)
    if not hits:
        hits = players.nearest(book.names, query, book.prominence, limit=10)
        for h in hits:
            h["matches"] = book.form.get(h["id"], {}).get("matches", 0)
            h["pts"] = book.overall["den"].get(h["id"], 0.0)
        if hits:
            print(f"  nothing matched {query!r}; nearest:")
    if not hits:
        print(f"  nothing matched {query!r}")
        return
    print(f"  {'player':<28} {'matches':>8} {'recent pts':>11}   matched on")
    for h in hits:
        print(f"  {h['name']:<28} {h['matches']:>8,} {h['pts']:>11,.0f}   "
              f"{h['why']}")


# ------------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(
        description="Price a tennis matchup from pre-match variables.",
        epilog="With no players it opens an interactive prompt. "
               "Bare words like `clay` or `bo5` work as positional shorthand.")
    ap.add_argument("player_a", nargs="?")
    ap.add_argument("player_b", nargs="?")
    ap.add_argument("extra", nargs="*",
                    help="shorthand: clay/hard/grass/carpet, bo3/bo5, a date")
    ap.add_argument("--list", "--find", dest="list", metavar="NAME",
                    help="search players and exit")
    ap.add_argument("--variables", action="store_true",
                    help="show every accepted variable and its status")
    ap.add_argument("-i", "--interactive", action="store_true",
                    help="force the interactive prompt")
    ap.add_argument("--rebuild", action="store_true", help="re-derive weights")
    ap.add_argument("--raw", action="store_true",
                    help="skip the calibration layer")
    ap.add_argument("--no-curves", action="store_true",
                    help="skip the fitted form/run curves")
    ap.add_argument("--surface", choices=["Hard", "Clay", "Grass", "Carpet"])
    ap.add_argument("--best-of", type=int, default=3, choices=[3, 5])
    ap.add_argument("--date", help="YYYY-MM-DD; uses only earlier matches")
    ap.add_argument("--at", metavar="TOURNAMENT",
                    help="venue + cached weather -> air density "
                         "(e.g. --at Cincinnati)")
    ap.add_argument("--form-scale", type=float)
    ap.add_argument("--entry-a", choices=ENTRY_CHOICES,
                    help="how A got into the draw: main, Q, WC, LL, PR, SE "
                         "(the results feed does not say)")
    ap.add_argument("--entry-b", choices=ENTRY_CHOICES)
    for f, t in (("indoor", str), ("temp-c", float), ("elevation-m", float),
                 ("humidity", float), ("wind-kph", float), ("roof-closed", str),
                 ("level", str), ("round", str), ("rest-days-a", float),
                 ("rest-days-b", float), ("minutes-a", float),
                 ("minutes-b", float)):
        ap.add_argument(f"--{f}", type=t)
    a = ap.parse_args()

    if a.variables:
        print(f"{'variable':<14} {'status':<9} effect")
        for k, (st, why) in VARIABLES.items():
            print(f"  {k:<12} {st:<9} {why}")
        return 0

    # Everything positional goes through the same forgiving parse the prompt
    # uses, so `price Sinner Alcaraz clay bo5`, `price "Sinner" "Alcaraz"`,
    # `price Djokovic vs Nadal` and `price Juan Martin del Potro vs Sinner`
    # all mean what they look like.  --surface / --best-of / --date still
    # work and are the defaults the shorthand overrides.
    surface, best_of, date = a.surface, a.best_of, a.date
    words, names = [w for w in [a.player_a, a.player_b] + list(a.extra) if w], []
    for w in words:
        lw = w.lower().strip(".,")
        if lw in SURFACES:
            surface = SURFACES[lw]
        elif lw in ("bo3", "bo5"):
            best_of = int(lw[-1])
        elif _DATE.match(lw):
            date = lw
        else:
            names.append(w)

    # Shell quoting already says where one name ends and the next begins, so
    # two arguments are two players even when either is multi-word.  Only when
    # that is not what was typed does the line get the prompt's guesswork.
    qa = qb = how = None
    whole = " ".join(names)
    sep = [i for i, w in enumerate(names)
           if w.lower() in ("vs", "vs.", "v", "v.", "versus", "-", "/")]
    if sep:
        i = sep[0]
        qa, qb, how = " ".join(names[:i]), " ".join(names[i + 1:]), "sep"
        whole = " ".join(names[:i] + names[i + 1:])
    elif len(names) == 2:
        qa, qb, how = names[0], names[1], "sep"
    elif len(names) == 1:
        qa, qb, how, surface, best_of, date = parse_line(
            names[0], surface, best_of, date)
    elif len(names) > 2:
        ap.error(f"could not tell which words are the two players in "
                 f"{whole!r} -- quote each name, or put `vs` between them "
                 "(and check any condition words: hard/clay/grass/carpet, "
                 "bo3/bo5, YYYY-MM-DD)")

    try:
        day = to_day(date.replace("-", "")) if date else None
    except Exception:                                       # noqa: BLE001
        ap.error(f"bad --date {date!r}; want YYYY-MM-DD")
    book = Book(day, rebuild=a.rebuild, verbose=True)

    if a.list:
        show_list(book, a.list)
        return 0

    if a.interactive or not names:
        return prompt(book, surface, best_of, date, a.at)

    try:
        pa, pb = resolve_pair(book, qa, qb, how, whole)
    except (Unknown, NeedTwo) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if pa["id"] == pb["id"]:
        print(f"error: both names resolved to {pa['name']}", file=sys.stderr)
        return 2

    recorded = [f"{k}={v}" for k, v in vars(a).items()
                if v is not None and k in RECORDED_KEYS]
    dens, dens_why = resolve_conditions(
        a.at, book.asof, a.temp_c, a.elevation_m, a.humidity,
        _truthy(a.indoor) or _truthy(a.roof_closed))
    report(book, pa, pb, surface, best_of, a.form_scale, dens=dens,
           dens_why=dens_why, tournament=a.at, use_curves=not a.no_curves,
           calibrate=not a.raw, recorded=recorded,
           entry=(a.entry_a, a.entry_b))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
