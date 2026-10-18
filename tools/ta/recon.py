"""Recover integer serve counts from Tennis Abstract's rounded percentages.

TA publishes A%, DF%, 1stIn, 1st%, 2nd% to one decimal.  Every one is a ratio
over the same unknown denominator (service points), so testing candidate
denominators against all five at once pins it.

Three things this has to get right, each of which was a real bug caught by
tools/ta/gate.py against matches the archive already had:

  * ROUNDING CONVENTION.  Python's round() is round-half-to-even, so it turns
    6.25 into 6.2 where the source publishes 6.3.  Comparing rounded values
    for equality therefore rejects the true denominator outright.  Compare
    against the published figure with a half-ulp tolerance instead.

  * THE FLOOR ON A SERVICE GAME.  Rounded ratios are also satisfied by exact
    multiples of the truth, so 30 and 60 service points look equally valid.
    A game cannot be won on fewer than four points, so points-per-service-game
    below 4.0 is not a close call, it is impossible -- that is what separates
    them.

  * RETIREMENTS.  A match abandoned at 4-0 has ~13 service points.  Starting
    the search at a "sane" lower bound silently made those unsolvable.
"""

TOL = 0.05 + 1e-9          # a published 1-decimal figure is +/- half a ulp
MIN_PTS_PER_GAME = 4.0     # four points is the shortest possible game
MAX_PTS_PER_GAME = 14.0    # long deuce games, averaged over a whole match


def _pct(s):
    s = (s or "").strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _ints(pub, total):
    """Integers whose share of `total` rounds to the published percentage."""
    if total <= 0:
        return []
    guess = int(round(pub * total / 100))
    return [x for x in (guess - 1, guess, guess + 1)
            if 0 <= x <= total and abs(100 * x / total - pub) <= TOL]


def solve(ace_pct, df_pct, first_in_pct, first_pct, second_pct,
          lo=1, hi=300):
    """All (svpt, ace, df, 1stIn, 1stWon, 2ndWon) consistent with the rates."""
    a, d, fi = _pct(ace_pct), _pct(df_pct), _pct(first_in_pct)
    fw, sw = _pct(first_pct), _pct(second_pct)
    if None in (a, d, fi, fw, sw):
        return []
    out = []
    for svpt in range(max(1, lo), hi + 1):
        aces = _ints(a, svpt)
        dfs = _ints(d, svpt)
        f_ins = [x for x in _ints(fi, svpt) if x > 0]
        if not (aces and dfs and f_ins):
            continue
        for f_in in f_ins:
            f_wons = _ints(fw, f_in)
            second = svpt - f_in
            if second == 0:
                s_wons = [0] if abs(sw) <= TOL else []
            else:
                s_wons = _ints(sw, second)
            if not (f_wons and s_wons):
                continue
            out.append((svpt, aces[0], dfs[0], f_in, f_wons[0], s_wons[0]))
            break
    return out


import re

_SET = re.compile(r"^(\d+)-(\d+)")


def games(score):
    """Total games in a score string, or None if it cannot be counted."""
    if not score or any(t in score.upper() for t in ("W/O", "WALKOVER", "DEF")):
        return None
    tot = 0
    for tok in score.split():
        m = _SET.match(tok)
        if m:
            tot += int(m.group(1)) + int(m.group(2))
    return tot or None


def best(cands, score):
    """Pick the physically possible candidate.

    Rounded ratios admit exact multiples of the truth (2x, 3x ...).  The score
    says how many service games were played, and no one holds serve on fewer
    than four points, so the multiple that puts a match below that floor is
    not the real one.
    """
    if not cands:
        return None
    g = games(score)
    if g:
        sv = max(1, round(g / 2))
        ok = [c for c in cands
              if MIN_PTS_PER_GAME <= c[0] / sv <= MAX_PTS_PER_GAME]
        if ok:
            return min(ok, key=lambda c: c[0])
    return min(cands, key=lambda c: c[0])
