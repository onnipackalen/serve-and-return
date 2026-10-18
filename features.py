"""
Tier 2 -- workload, derived from the match log rather than fetched.

    python3 features.py             coverage + distributions
    python3 features.py Alcaraz     one player's recent workload

Nothing here needs a new source.  Every value is computed from matches
already loaded, which is the whole appeal: no scrape to break, no join to
get wrong.

WHAT tourney_date COSTS US, stated up front.  The archive dates a match by
when its TOURNAMENT started, not when it was played, so two players meeting
in a final and a first round carry the same date.  That makes some things
exact and others merely approximate, and they must not be mixed up:

  exact        matches and minutes played EARLIER IN THIS EVENT.  Round
               order gives the sequence with certainty -- a quarter-final
               is always after a round of 16.
  approximate  days since the previous event.  Measured start-to-start, so
               it is right to within the length of a tournament.  Useful for
               "came straight off a Masters" vs "took three weeks off";
               useless for "played a 4-hour match yesterday".

So the within-event quantities are the ones to trust, and they are also the
ones fatigue arguments actually turn on.

Every value defaults to a neutral 0 for a player with no history, and
nothing here changes a price on its own -- backtest.py fits a weight for it
first, exactly as it did for style and h2h (both of which fitted to zero).
"""

import math
import re
import sys

from venues import distance_km
from collections import defaultdict

# Round order within an event.  RR/BR are round-robin and bronze matches,
# which do not sit in the knockout sequence; they are treated as first.
ROUND_ORDER = {"RR": 0, "BR": 0, "R128": 1, "R64": 2, "R32": 3, "R16": 4,
               "QF": 5, "SF": 6, "F": 7}
# entry codes, as integers so the curve harness can bucket them
ENTRY = {"": 0, "Q": 1, "WC": 2, "LL": 3, "PR": 4, "SE": 5}


_DAYS = {}


def _day(yyyymmdd):
    """Days since 2000-01-01 from a YYYYMMDD string.

    Memoised: build() calls this inside every per-player history loop --
    four million times for a single season -- and there are only a couple
    of thousand distinct dates.  Parsing each call made the full-archive
    build with EXTRA_FEATURES take 48 minutes; cached it takes under two.
    """
    s = str(yyyymmdd)
    d = _DAYS.get(s)
    if d is None:
        import datetime as dt
        d = _DAYS[s] = (dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
                        - dt.date(2000, 1, 1)).days
    return d


def score_parts(score, winner_side):
    """(sets_won, sets_lost, games_won, games_lost) for one side of a match.

    A run is not just a count of wins: reaching a quarter-final in straight
    sets says something different about a player than scraping there in five,
    and it costs a different amount.  Retirements and walkovers return zeros
    rather than a guess.
    """
    if not score or any(t in score.upper()
                        for t in ("W/O", "WALKOVER", "DEF", "RET")):
        return 0, 0, 0, 0
    sw = sl = gw = gl = 0
    for tok in score.split():
        m = re.match(r"^(\d+)-(\d+)", tok)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if not winner_side:
            a, b = b, a
        gw += a
        gl += b
        sw += a > b
        sl += b > a
    return sw, sl, gw, gl


def build(matches):
    """{(tourney_id, round, player_id): workload} for every match.

    workload keys:
      event_matches   matches this player already played at this event  (exact)
      event_minutes   minutes already played at this event              (exact)
      event_sets_lost sets dropped so far at this event                 (exact)
      event_gwp       share of games won so far at this event           (exact)
      event_5setters  matches here that went the distance               (exact)
      days_rest       days since the previous event started        (approximate)
      matches_28d     matches in the 28 days before this event      (approximate)
      home            playing in their own country, or None         (exact)
      round_order     0 (RR) to 8 (final)                          (exact)
      wins_to_title   matches still to win for the title           (exact)
      draw_size       32, 64, 128 ...                              (exact)
      age             years, back-filled by arithmetic when blank   (exact)
      form_spw        28d serve level minus their own 365d level    (exact)
      bp_form         180d break points saved minus their own 730d  (exact)
      event_opp_rank  mean log10 rank of opponents beaten here      (exact)
      vs_quality      their own slope on opponent calibre, applied  (derived)
      opp_log_rank    this opponent's log10 rank                    (exact)
      opp_faced_mean  mean calibre their own rating was built on    (derived)
      home_km         km from their country to this venue, own = 0  (approximate)

    The dominance terms exist to separate two things that both rise with
    wins: INFORMATION (this player is better than rated) and FATIGUE (this
    player is tired).  Counting wins alone confounds them.
    """
    # order every match, then walk each player's career forward
    seq = sorted(matches, key=lambda m: (m.tourney_date,
                                         ROUND_ORDER.get(m.rnd, 9)))
    xbar, tour_b = _quality_gradient(seq) if EXTRA_FEATURES else (1.651, 0.0)
    per = defaultdict(list)     # player -> [(date, tid, rnd, mins, parts)]
    out = {}
    for m in seq:
        for pid in (m.w_id, m.l_id):
            hist = per[pid]
            d = _day(m.tourney_date)
            my_rank = m.w_rank if pid == m.w_id else m.l_rank
            my_opp_rank = m.l_rank if pid == m.w_id else m.w_rank
            here = [h for h in hist if h[1] == m.tid]
            ev_matches = len(here)
            ev_minutes = sum(h[3] or 0 for h in here)
            sets_lost = sum(h[4][1] for h in here)
            gw = sum(h[4][2] for h in here)
            gl = sum(h[4][3] for h in here)
            fives = sum(1 for h in here if h[4][0] + h[4][1] >= 5)
            prev = [h for h in hist if h[1] != m.tid]
            days_rest = (d - _day(prev[-1][0])) if prev else None
            m28 = sum(1 for h in prev if 0 <= d - _day(h[0]) <= 28)
            # injury history: retirements and withdrawals in the recent past,
            # and whether this is a first match back from a long absence
            ret90 = sum(1 for h in hist
                        if 0 <= d - _day(h[0]) <= 90 and h[5][0])
            wo90 = sum(1 for h in hist
                       if 0 <= d - _day(h[0]) <= 90 and h[5][1])
            layoff = days_rest if days_rest is not None else 0
            # travel and conditions CHANGE between events -- a flight
            # across eight time zones or a jump from sea level to altitude
            # is a burden the ratings cannot see, and both fall out of the
            # venue table for nothing
            prev_ev = prev[-1] if prev else None
            travel = elev_ch = None
            surf_switch = 0
            if prev_ev is not None and ev_matches == 0:
                va = _venue(prev_ev[6])
                vb = _venue(m.tname)
                if va and vb:
                    travel = distance_km((va[0], va[1]), (vb[0], vb[1]))
                    elev_ch = vb[2] - va[2]
                surf_switch = 1 if (prev_ev[7] and m.surface
                                    and prev_ev[7] != m.surface) else 0
            win = pid == m.w_id
            my_entry = m.w_entry if win else m.l_entry
            my_seed = m.w_seed if win else m.l_seed
            opp_hand = m.l_hand if win else m.w_hand
            out[(m.tid, m.rnd, pid)] = {
                # How the player got into the draw (ENTRY codes) and whether
                # they were seeded.  A protected ranking is the archive's
                # one explicit injury mark; a qualifier arrives with three
                # wins banked; a wild card is usually a weak local.  None of
                # this was ever read before 2026-09-11.
                "entry": ENTRY.get(my_entry or "", 6),
                "seeded": 1 if my_seed else 0,
                # the player's OWN ranking, as a residual: rank is a
                # results-based aggregate over 52 weeks, and "already inside
                # the ratings" had been asserted, never measured
                "log_rank": math.log10(my_rank) if my_rank else None,
                "rank_gap": ((math.log10(my_rank) - math.log10(my_opp_rank))
                             if (my_rank and my_opp_rank) else None),
                # facing a left-hander: the lefty's own edge is in their
                # rating; whether opponents under-perform against it beyond
                # that is a separate, per-player question
                "opp_lefty": (1 if opp_hand == "L" else
                              0 if opp_hand == "R" else None),
                # Round, three ways, because the label alone is ambiguous.
                # Both players share all three, so they cancel exactly in the
                # antisymmetric price adjustment -- these exist to be tested
                # as CONFIDENCE inputs and as interaction terms.
                "round_order": ROUND_ORDER.get(m.rnd, 9),
                "wins_to_title": _wins_to_title(m.rnd),
                "draw_size": m.draw_size,
                "age": (m.w_age if pid == m.w_id else m.l_age),
                "form_spw": _form_spw(hist, d),
                # rejected covariates, kept measurable but not paid for on
                # every build -- see EXTRA_FEATURES
                "bp_form": _bp_form(hist, d) if EXTRA_FEATURES else None,
                "event_opp_rank": _opp_rank(here) if EXTRA_FEATURES else None,
                # controls: is `age` really age, or is it thin data wearing
                # an age mask?  A 19-year-old has few service points, so the
                # rating shrinks him toward the tour mean -- and tour-level
                # 19-year-olds are better than the tour mean.
                "vs_quality": (_vs_quality(hist, d, my_opp_rank, xbar, tour_b)
                               if EXTRA_FEATURES else None),
                "opp_log_rank": (math.log10(my_opp_rank)
                                 if my_opp_rank else None),
                "opp_faced_mean": (_opp_faced_mean(hist, d)
                                   if EXTRA_FEATURES else None),
                "career_matches": len(hist),
                "career_pts": (_decayed_pts(hist, d)
                               if EXTRA_FEATURES else None),
                # trend measured directly rather than proxied by age; both
                # real alone, both hurt the set once `age` is in it
                "rank_change": (_rank_change(hist, d, my_rank)
                                if EXTRA_FEATURES else None),
                "peak_gap": (_peak_gap(hist, my_rank)
                             if EXTRA_FEATURES else None),
                "travel_km": travel,
                "elev_change_m": elev_ch,
                "surface_switch": surf_switch,
                "ret_90d": ret90,
                "wo_90d": wo90,
                "comeback": 1 if (ev_matches == 0 and layoff >= 60) else 0,
                "layoff_days": layoff if ev_matches == 0 else 0,
                "event_matches": ev_matches,
                "event_minutes": ev_minutes,
                "event_sets_lost": sets_lost,
                "event_gwp": (gw / (gw + gl)) if (gw + gl) else None,
                "event_5setters": fives,
                "days_rest": days_rest,
                "matches_28d": m28,
                "home": home_flag(m, pid),
                "home_km": home_km(m, pid) if EXTRA_FEATURES else None,
            }
        # append AFTER computing, so a match never counts itself.  Index 8
        # is a dict rather than more positions: the tuple is already eight
        # long and read by index in five places.
        per[m.w_id].append((m.tourney_date, m.tid, m.rnd, m.minutes,
                            score_parts(m.score, True),
                            injury_marks(m, m.w_id), m.tname, m.surface,
                            {"svpt": m.w_svpt if m.has_stats else 0,
                             "swon": m.w_won if m.has_stats else 0,
                             "bps": m.w_bps, "bpf": m.w_bpf,
                             "opp_rank": m.l_rank, "my_rank": m.w_rank}))
        per[m.l_id].append((m.tourney_date, m.tid, m.rnd, m.minutes,
                            score_parts(m.score, False),
                            injury_marks(m, m.l_id), m.tname, m.surface,
                            {"svpt": m.l_svpt if m.has_stats else 0,
                             "swon": m.l_won if m.has_stats else 0,
                             "bps": m.l_bps, "bpf": m.l_bpf,
                             "opp_rank": m.w_rank, "my_rank": m.l_rank}))
    return out


# Injury leaves fingerprints in the match log even though no column names
# it.  In Sackmann data the LOSER is the one who retired or withdrew, so
# "RET" and "W/O" identify a hurt player precisely, not just an odd result.
# Opponent-calibre features are OFF by default.  They were built, measured
# and rejected (see below), and the per-player regression inside
# _vs_quality costs 33 seconds of the 42 that build() would otherwise take
# -- a 4.6x slowdown on every cache rebuild and on the app's start-up, paid
# for a covariate that measures to nothing.  They stay in the file so the
# next person can re-measure rather than rebuild; tools/curves.py switches
# them on when it builds the residual cache.
EXTRA_FEATURES = False

QUALITY_HALF_LIFE = 1095.0   # a stable trait, like surface: long memory
# Rule 6: derived from MEASURED split-half reliability, not chosen.  The
# per-player slope was split in half by match and the two halves correlated:
#
#     >=60 matches   r 0.127   full-sample reliability 0.226   -> K 205
#     >=100 matches  r 0.183                            0.309  -> K 224
#     >=250 matches  r 0.350                            0.519  -> K 232
#
# One K fits all three, which is the evidence that n/(n+K) is the right
# form and not just a convenient one.  Below about 40 matches the two halves
# are UNCORRELATED (r = -0.065): there is no trait there to shrink toward.
#
# The first version of this feature used K = 40 and a 20-match floor, and it
# hurt out of sample with a telltale shape -- both extreme buckets negative,
# the middle positive, which is what applying an over-confident estimate in
# either direction looks like.
QUALITY_SHRINK = 220.0
QUALITY_MIN_MATCHES = 50
_QGRAD = {}


def _quality_gradient(seq):
    """(mean log10 opponent rank, tour-wide slope of serve% on it).

    Everyone serves better against weaker opponents -- that is what the
    opponent adjustment in the ratings is for, and it is a POPULATION
    quantity. What this file is after is each player's DEVIATION from it,
    so the population gradient has to be measured and subtracted first.

    Two global constants, estimated over the whole era from ~60,000 rows.
    Same status as load.tour_avg, which is computed the same way and used
    everywhere: a nuisance parameter whose contribution to any one match is
    negligible, not a fitted per-player effect.
    """
    key = len(seq)
    if key in _QGRAD:
        return _QGRAD[key]
    xs = []
    for m in seq:
        if not m.has_stats:
            continue
        for svpt, swon, orank in ((m.w_svpt, m.w_won, m.l_rank),
                                  (m.l_svpt, m.l_won, m.w_rank)):
            if svpt and orank:
                xs.append((math.log10(orank), swon / svpt, svpt))
    if len(xs) < 500:
        _QGRAD[key] = (1.8, 0.0)
        return _QGRAD[key]
    wt = sum(w for _x, _y, w in xs)
    xbar = sum(x * w for x, _y, w in xs) / wt
    ybar = sum(y * w for _x, y, w in xs) / wt
    num = sum(w * (x - xbar) * (y - ybar) for x, y, w in xs)
    den = sum(w * (x - xbar) ** 2 for x, _y, w in xs)
    _QGRAD[key] = (xbar, num / den if den else 0.0)
    return _QGRAD[key]


def _vs_quality(hist, day, opp_rank_now, xbar, tour_b):
    """How much better than usual this player does against THIS calibre.

    The ratings adjust for the opponent additively: a player's edge is
    assumed to be the same shift whatever the opposition. That is an
    assumption, not a measurement, and it is the one thing the style
    interaction deliberately does not test -- it strips the opponent's
    level out on purpose and keeps only their shape.

    So: fit this player's own slope of serve rate on log opponent rank over
    their prior matches, subtract the tour-wide slope, shrink what is left,
    and multiply by how far this opponent sits from the average. Positive
    means the model is expected to under-rate them in this particular
    matchup.

    Returns None rather than 0 when the player has too little history to
    have a slope, so "no read" never enters the same bucket as "no effect".
    """
    if not opp_rank_now:
        return None
    pts = []
    for h in hist:
        x = h[8]
        gap = day - _day(h[0])
        if gap < 0 or not x["svpt"] or not x["opp_rank"]:
            continue
        w = x["svpt"] * 0.5 ** (gap / QUALITY_HALF_LIFE)
        pts.append((math.log10(x["opp_rank"]), x["swon"] / x["svpt"], w))
    if len(pts) < QUALITY_MIN_MATCHES:
        return None
    wt = sum(w for _x, _y, w in pts)
    mx = sum(x * w for x, _y, w in pts) / wt
    my = sum(y * w for _x, y, w in pts) / wt
    den = sum(w * (x - mx) ** 2 for x, _y, w in pts)
    if den <= 0:
        return None
    b = sum(w * (x - mx) * (y - my) for x, y, w in pts) / den
    # rule 4/6: a raw per-player slope is a coin flip dressed as an insight,
    # and how much of it survives is a measurement -- see QUALITY_SHRINK
    dev = (b - tour_b) * len(pts) / (len(pts) + QUALITY_SHRINK)
    return dev * (math.log10(opp_rank_now) - xbar)


def _opp_faced_mean(hist, day):
    """The average calibre this player's rating was actually built on.

    Distinct from vs_quality, and a different mechanism: that one asks
    whether a player is unusually good or bad against strong opposition,
    this one asks whether their rating is TRUSTWORTHY against one. A record
    assembled against qualifiers may be inflated in a way an additive
    opponent adjustment does not undo.
    """
    n = w = 0.0
    for h in hist:
        x = h[8]
        gap = day - _day(h[0])
        if gap < 0 or not x["svpt"] or not x["opp_rank"]:
            continue
        ww = x["svpt"] * 0.5 ** (gap / QUALITY_HALF_LIFE)
        n += math.log10(x["opp_rank"]) * ww
        w += ww
    return (n / w) if w > 0 else None


# How many more matches this player must win to take the title.  Independent
# of draw size, which ROUND_ORDER is not: "R32" is the opening round of a
# 32-draw and the third match of a 128-draw.  A final is a final everywhere.
_TO_TITLE = {"F": 1, "SF": 2, "QF": 3, "R16": 4, "R32": 5, "R64": 6,
             "R128": 7, "RR": 4, "BR": 1}


def _wins_to_title(rnd):
    return _TO_TITLE.get(rnd)


def _rate(hist, day, window, num, den, floor):
    """(numerator / denominator) over a trailing window, or None if thin."""
    n = q = 0
    for h in hist:
        if 0 <= day - _day(h[0]) <= window:
            x = h[8]
            if x[den]:
                n += x[num] or 0
                q += x[den]
    return (n / q) if q >= floor else None


def _form_spw(hist, day):
    """Recent serve level MINUS the player's own longer-run serve level.

    The ratings decay with a 270-day half-life, so they already lean recent.
    This asks whether the last 28 days say anything on top of that -- and it
    asks it in MARGIN (points won on serve), which is where this project has
    repeatedly found the signal, rather than in match COUNT, where
    matches_28d already sits.

    Measured against the player's own baseline rather than the tour's, so
    that a career-long weak server does not read as being out of form.
    Rule 8 in the other direction: a short window ON TOP OF a long one, not
    instead of it.
    """
    short = _rate(hist, day, 28, "swon", "svpt", 150)
    long_ = _rate(hist, day, 365, "swon", "svpt", 800)
    return None if (short is None or long_ is None) else short - long_


def _bp_form(hist, day):
    """Break points saved lately minus the player's own long-run rate.

    The only clutch measurement the file contains.  Break points are the
    points that decide games, and a point model treats every point as
    identical by construction -- so if clutch exists as anything other than
    noise, this is where it would show.  Break points are sparse, so the
    windows are wider than for serve.
    """
    short = _rate(hist, day, 180, "bps", "bpf", 30)
    long_ = _rate(hist, day, 730, "bps", "bpf", 120)
    return None if (short is None or long_ is None) else short - long_


HALF_LIFE = 270.0        # the same decay weights.py fits the ratings with


def _decayed_pts(hist, day):
    """Service points behind this player's rating, decayed as the rating is.

    This is the quantity that decides how hard weights.py shrinks a player
    toward the tour mean, so it is the right control for "thin data" -- not
    a raw career count, which would call a 34-year-old who stopped playing
    two years ago well-measured.
    """
    tot = 0.0
    for h in hist:
        gap = day - _day(h[0])
        if gap >= 0:
            tot += (h[8]["svpt"] or 0) * 0.5 ** (gap / HALF_LIFE)
    return tot


def _rank_change(hist, day, rank_now):
    """log10(rank now) - log10(rank about a year ago).  Negative = improving.

    Age is a proxy for trend: young players are rising and old ones are
    falling, on average.  This measures the trend itself, so if it carries
    the signal then `age` is the crude version of it and should give way.
    """
    if not rank_now:
        return None
    old = [h for h in hist if 300 <= day - _day(h[0]) <= 450
           and h[8]["opp_rank"] is not None]
    # the player's OWN rank a year ago is not stored on their row -- but a
    # rank one year back is recoverable from the rank recorded on their
    # matches then, which is exactly what `mine_rank` below carries
    mine = [h[8]["my_rank"] for h in hist
            if 300 <= day - _day(h[0]) <= 450 and h[8].get("my_rank")]
    if not mine:
        return None
    then = sum(mine) / len(mine)
    return math.log10(rank_now) - math.log10(then)


def _peak_gap(hist, rank_now):
    """log10(rank now) - log10(best rank ever).  How far off their peak.

    A player a long way below their own ceiling is declining or hurt, and
    the ratings -- a decaying average -- take months to catch up.
    """
    if not rank_now:
        return None
    best = [h[8]["my_rank"] for h in hist if h[8].get("my_rank")]
    if not best:
        return None
    return math.log10(rank_now) - math.log10(min(best))


def _live_form_spw(hist, day):
    """_form_spw for a player being priced today, from (date, (svpt, swon))."""
    def rate(window, floor):
        n = q = 0
        for date, (svpt, swon) in hist:
            if 0 <= day - _day(date) <= window and svpt:
                n += swon
                q += svpt
        return (n / q) if q >= floor else None
    short, long_ = rate(28, 150), rate(365, 800)
    return None if (short is None or long_ is None) else short - long_


def _opp_rank(here):
    """Mean log10 rank of the opponents already beaten at this event.

    event_gwp is the strongest curve here, and its blind spot is WHO the
    margin came against: 60% of games against two qualifiers is not 60%
    against the top ten.  Log scale because the gap between rank 1 and 20
    is not the gap between 200 and 220.
    """
    rs = [h[8]["opp_rank"] for h in here if h[8]["opp_rank"]]
    return (sum(math.log10(r) for r in rs) / len(rs)) if rs else None


_VCACHE = {}


def _venue(tname):
    """Cached venue lookup -- build() calls this ~60,000 times."""
    if tname not in _VCACHE:
        from venues import lookup
        _VCACHE[tname] = lookup(tname)
    return _VCACHE[tname]


_CCACHE = {}


def _country(tname):
    """Cached host nation for a tournament -- same call volume as _venue."""
    if tname not in _CCACHE:
        from venues import country
        _CCACHE[tname] = country(tname)
    return _CCACHE[tname]


def home_km(m, pid):
    """How far this player is from home, in km, with own country = 0.

    The binary home flag says "at home or not"; this says how far away,
    which is the version that can see a Frenchman at Monte Carlo or an
    Argentine in Santiago.  Both are emitted -- which one carries the
    signal is a measurement, not a preference.
    """
    from venues import home_distance_km
    ioc = m.w_ioc if pid == m.w_id else m.l_ioc
    return home_distance_km(ioc, m.tname)


def home_flag(m, pid):
    """1 if this player is playing in their own country, 0 if not, None if
    it cannot be established.

    None matters.  A missing IOC and a venue with no country on file are
    both "did not look", and coding them 0 would put every unknown into the
    away bucket and dilute exactly the contrast being measured.  The
    season-ending finals are None by design -- they rotate.
    """
    host = _country(m.tname)
    if not host:
        return None
    ioc = m.w_ioc if pid == m.w_id else m.l_ioc
    return None if not ioc else int(ioc == host)


RETIRED = ("RET", "RETIRED")
WALKOVER = ("W/O", "WALKOVER", "DEF")


def injury_marks(m, pid):
    """(retired_here, walked_over_here) for this player in this match."""
    s = (m.score or "").upper()
    if m.l_id != pid:
        return False, False
    return (any(t in s for t in RETIRED),
            any(t in s for t in WALKOVER))


_LOG = None
_TRAITS = None


def _traits():
    """data/player_traits.json, written by tools/curves.py write: each
    player's mean walk-forward residual, shrunk -- the live form of the
    resid_prior curve input.  Missing file means no trait, never an error."""
    global _TRAITS
    if _TRAITS is None:
        import json
        import os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                         "player_traits.json")
        try:
            with open(p) as fh:
                _TRAITS = json.load(fh)
        except (OSError, ValueError):
            _TRAITS = {}
    return _TRAITS


def match_log(y0=2015, y1=2026):
    """The match list, loaded once per process.

    Pricing needs the same workload the curves were fitted on, and that has
    to be recomputed from matches rather than stored, because it depends on
    the as-of date being asked about.
    """
    global _LOG
    if _LOG is None:
        from load import load
        _LOG = load(y0, y1)[0]
    return _LOG


def live_workload(pid, asof_day, tournament=None, matches=None, entry=None,
                  seeded=None, surface=None):
    """Workload for a player being priced TODAY, not inside a stored match.

    matches_28d needs only a date.  The dominance terms need to know which
    event the player is currently in, which is what `tournament` supplies --
    the same argument that already selects the venue's conditions.  Returns
    None for anything that cannot be established rather than a zero, so the
    caller can tell "no run yet" from "did not look".

    `entry` / `seeded` are how the player got into THIS draw, supplied by
    the caller (a --entry flag, an app control): the archive records them on
    every row but the live results feed carries neither, so a first-round
    qualifier is invisible to the log.  Without them they are read off the
    player's earlier matches at this event when those rows carry a code,
    else None -- never guessed.  `surface` selects the surface-specific
    residual trait.
    """
    matches = matches if matches is not None else match_log()
    mine = [m for m in matches if pid in (m.w_id, m.l_id)]
    out = {"matches_28d": 0, "event_gwp": None, "event_sets_lost": None,
           "event_matches": 0, "event_minutes": 0,
           "days_rest": None, "layoff_days": 0, "comeback": 0,
           "ioc": None, "home": None, "home_km": None,
           "age": None, "form_spw": None,
           # the player's own ranking off their most recent row (stale by
           # however long since they played; build() has it fresh), and
           # the residual traits from data/player_traits.json
           "log_rank": None, "rank_gap": None,
           "resid_prior": None, "bo5_resid_prior": None,
           "resid_365": None, "resid_surface": None,
           "entry": None, "seeded": None}
    tr = _traits().get(pid)
    if tr:
        out["resid_prior"] = tr.get("resid_prior")
        out["bo5_resid_prior"] = tr.get("bo5_resid_prior")
        out["resid_365"] = tr.get("resid_365")
        if surface:
            out["resid_surface"] = (tr.get("surf") or {}).get(surface)
    if entry is not None:
        out["entry"] = ENTRY.get(str(entry).upper().replace("MAIN", ""), 6)
    if seeded is not None:
        out["seeded"] = 1 if seeded else 0

    # nationality is not in weights.json -- it comes off the player's own
    # most recent match, which is where every other live quantity here comes
    # from too.  Taking the LAST one matters: a handful of players changed
    # federation mid-career and the current one is the one that decides
    # whether they are at home.
    if mine:
        # the most recent match THAT CARRIES ONE.  The tennisabstract feed
        # leaves winner_ioc/loser_ioc blank -- all 847 rows of 2026 -- so
        # taking simply the latest match would return None for every active
        # player, which is the whole population being priced.
        for m in sorted(mine, key=lambda m: m.tourney_date, reverse=True):
            ioc = m.w_ioc if m.w_id == pid else m.l_ioc
            if ioc:
                out["ioc"] = ioc
                break
        for m in sorted(mine, key=lambda m: m.tourney_date, reverse=True):
            rk = m.w_rank if m.w_id == pid else m.l_rank
            if rk:
                out["log_rank"] = math.log10(rk)
                break
    for m in mine:
        d = _day(m.tourney_date)
        if 0 <= asof_day - d <= 28:
            out["matches_28d"] += 1

    # age and recent serve level, derived exactly as build() derives them so
    # a live price and a fitted residual mean the same thing.  build() reads
    # them off the match row; here there is no match row, so age comes off
    # the most recent one plus the time since, which is the same arithmetic
    # load.fill_ages uses.
    if mine:
        # the shared birthday, not one row's age: load.fill_ages takes the
        # MEDIAN implied birthday over every row that carries an age, and
        # reading a single row instead would import that row's rounding
        from load import BIRTHDAYS
        b = BIRTHDAYS.get(pid)
        if b is not None:
            out["age"] = (asof_day - b) / 365.25
        else:
            last = max(mine, key=lambda m: m.tourney_date)
            a = last.w_age if last.w_id == pid else last.l_age
            if a is not None:
                out["age"] = a + (asof_day - _day(last.tourney_date)) / 365.25
        hist = [(m.tourney_date,
                 (m.w_svpt, m.w_won) if m.w_id == pid else (m.l_svpt, m.l_won))
                for m in mine if m.has_stats]
        out["form_spw"] = _live_form_spw(hist, asof_day)

    if tournament and out["ioc"]:
        from venues import country as _host, home_distance_km
        host = _host(tournament)
        if host:
            out["home"] = int(out["ioc"] == host)
        out["home_km"] = home_distance_km(out["ioc"], tournament)

    key = norm_event(tournament) if tournament else None
    here = ([m for m in mine if norm_event(m.tname) == key
             and 0 <= asof_day - _day(m.tourney_date) <= 21] if key else [])

    # Layoff, derived exactly as build() derives it: days since the previous
    # OTHER event started, and a comeback is a player with no run here who
    # has been away 60+ days.  build() has always produced these; this
    # function did not, so every LIVE price scored `comeback` as 0 -- and
    # comeback is the heaviest term in the confidence band (weight 2, and a
    # measured +0.052 deficit against the closing line, roughly double).
    # A player returning from six months out was being reported as a price
    # you could trust.
    # everything that is not part of the current run counts as "before" --
    # matching on the event NAME alone would push a previous year's edition
    # of the same tournament out of the history and overstate the layoff
    here_ids = {id(m) for m in here}
    prev = [m for m in mine if id(m) not in here_ids]
    if prev:
        last = max(_day(m.tourney_date) for m in prev)
        out["days_rest"] = asof_day - last
    if not here:
        out["layoff_days"] = out["days_rest"] or 0
        out["comeback"] = 1 if out["layoff_days"] >= 60 else 0

    if not here:
        return out
    gw = gl = sl = mins = 0
    for m in here:
        won = m.w_id == pid
        s = score_parts(m.score, won)
        sl += s[1]
        gw += s[2]
        gl += s[3]
        mins += m.minutes or 0
        # entry / seed off a row at this event that carries one (archive
        # rows do; the results feed leaves both blank, which is "unknown",
        # not "main draw")
        code = m.w_entry if won else m.l_entry
        seed = m.w_seed if won else m.l_seed
        if out["entry"] is None and code:
            out["entry"] = ENTRY.get(code, 6)
        if out["seeded"] is None and seed:
            out["seeded"] = 1
    out["event_matches"] = len(here)
    out["event_minutes"] = mins
    out["event_sets_lost"] = sl
    out["event_gwp"] = (gw / (gw + gl)) if (gw + gl) else None
    return out


def norm_event(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def recent(matches, pid, limit=10):
    """That player's last few matches with the workload carried into each."""
    feats = build(matches)
    seq = sorted((m for m in matches if pid in (m.w_id, m.l_id)),
                 key=lambda m: (m.tourney_date, ROUND_ORDER.get(m.rnd, 9)))
    rows = []
    for m in seq[-limit:]:
        f = feats.get((m.tid, m.rnd, pid), {})
        rows.append((m, f, m.w_id == pid))
    return rows


# ------------------------------------------------------------------- gate

def _gate(matches):
    """Sanity properties any correct derivation must satisfy."""
    feats = build(matches)
    bad = 0
    # A "first round" is whichever round an event actually opens with: a
    # 128-draw opens at R128, a 32-draw at R32, and in a 128-draw the R64 is
    # a SECOND match, so players there rightly have one behind them.
    opener = {}
    for tid, rnd, _pid in feats:
        o = ROUND_ORDER.get(rnd, 9)
        if tid not in opener or o < opener[tid]:
            opener[tid] = o
    # Round-robin and bronze matches are excluded: they are not a knockout
    # round at all, so a player plays SEVERAL of them at one event and having
    # earlier matches there is correct.  Davis Cup ties and the Tour Finals
    # groups are the bulk of them.
    firsts = [(k, v) for k, v in feats.items()
              if k[1] not in ("RR", "BR")
              and ROUND_ORDER.get(k[1], 9) == opener.get(k[0])]
    off = [k for k, v in firsts if v["event_matches"] > 0]
    if off:
        print(f"  FAIL {len(off)} opening-round rows claim earlier "
              f"matches at the same event")
        bad += 1
    # a final must have prior matches at the same event
    finals = [(k, v) for k, v in feats.items() if k[1] == "F"]
    off = [k for k, v in finals if v["event_matches"] == 0]
    if len(off) > len(finals) * 0.05:
        print(f"  FAIL {len(off)}/{len(finals)} finals show no earlier matches")
        bad += 1
    # minutes must never be negative, rest must never be
    if any((v["event_minutes"] or 0) < 0 or (v["days_rest"] or 0) < 0
           for v in feats.values()):
        print("  FAIL negative minutes or rest")
        bad += 1
    # --- the bug that hid for two sessions, gated
    #
    # `comeback` was emitted by build(), FITTED into confidence.py at the
    # heaviest weight it has, and never set by live_workload -- so every
    # interactive price scored it 0 and the band was blind to a layoff.  The
    # same shape of bug would silently disable any fitted curve.  So: every
    # key the fitted curves consume must exist in what live pricing produces,
    # and the two derivations must agree where they are comparable.
    import json as _json
    import os as _os
    cfile = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "fitted_curves.json")
    if _os.path.exists(cfile):
        need = set(_json.load(open(cfile)).get("curves", {}))
        sample = matches[-1]
        live = live_workload(sample.w_id, _day(sample.tourney_date),
                             sample.tname, matches)
        missing = sorted(need - set(live))
        if missing:
            print(f"  FAIL live_workload does not supply {missing} -- those "
                  f"curves are fitted but never applied to a live price")
            bad += 1
        else:
            print(f"  live pricing supplies all {len(need)} fitted curve "
                  f"inputs: {', '.join(sorted(need))}")

        # and they must MEAN the same thing.  age and home are unambiguous;
        # form_spw and matches_28d legitimately differ, because build sees a
        # match log with the match removed and live sees one without it yet.
        seq = sorted(matches, key=lambda m: (m.tourney_date,
                                             ROUND_ORDER.get(m.rnd, 9)))
        checked = disagree = 0
        for m in seq[-4000::37]:
            for pid in (m.w_id, m.l_id):
                f = feats.get((m.tid, m.rnd, pid))
                if not f or f.get("age") is None:
                    continue
                lw = live_workload(pid, _day(m.tourney_date), m.tname, matches)
                checked += 1
                # the source stores age to one decimal, so 0.1 y IS the
                # precision; anything inside it is the file rounding, not
                # two derivations disagreeing
                if lw["age"] is None or abs(lw["age"] - f["age"]) > 0.1:
                    disagree += 1
                elif lw["home"] != f["home"]:
                    disagree += 1
        print(f"  live vs build agree on age and home: "
              f"{checked - disagree:,}/{checked:,}")
        if disagree:
            print(f"  FAIL {disagree} disagreements")
            bad += 1

    print(f"  {len(feats):,} player-match rows derived")
    print(f"  opening rounds with no prior event matches : "
          f"{sum(1 for _k, v in firsts if v['event_matches'] == 0):,}/{len(firsts):,}")
    print(f"  finals with prior event matches            : "
          f"{len(finals) - len(off) if len(finals) else 0:,}/{len(finals):,}")
    return bad


if __name__ == "__main__":
    from load import load
    matches, _bad = load(2015, 2026)
    matches = [m for m in matches if m.tourney_date >= "20150101"]

    if len(sys.argv) > 1:
        import price as P
        book = P.Book(verbose=False)
        c = book.candidates(" ".join(sys.argv[1:]), limit=1)
        if not c:
            sys.exit(f"no player matching {' '.join(sys.argv[1:])!r}")
        pid, name = c[0]["id"], c[0]["name"]
        print(f"\n{name} -- last matches and the workload carried into each")
        print(f"  {'date':<10} {'event':<22} {'rd':<5} {'prior':>5} "
              f"{'mins':>6} {'rest':>5} {'28d':>4}")
        for m, f, won in recent(matches, pid):
            print(f"  {m.tourney_date:<10} {m.tname[:21]:<22} {m.rnd:<5} "
                  f"{f.get('event_matches',0):>5} {f.get('event_minutes',0):>6} "
                  f"{str(f.get('days_rest','-')):>5} {f.get('matches_28d',0):>4}"
                  f"   {'W' if won else 'L'}")
        raise SystemExit(0)

    print("\nworkload derivation")
    raise SystemExit(1 if _gate(matches) else 0)
