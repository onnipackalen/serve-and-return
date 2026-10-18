"""
M1 -- load Sackmann ATP match data and compute serve/return ability.

Gate:  python3 load.py       tour average serve must land near 0.645.

Two things this file is careful about, both flagged in data_plan.md:

  * return points won is NOT a column.  It is derived from the opponent's
    serve columns in the same row, so both ratings come from one pass.

  * `tourney_date` is the tournament START date, shared by every match in
    the event.  Stored as-is here and labelled, so M2 cannot silently treat
    it as a match date when it builds decay weights.

Data source is a third-party archival mirror (Sackmann's own repos were
taken down), so `validate` below checks arithmetic identities that any
corrupted or fabricated row would fail.  It is a provenance test, not a
formality -- read its output.
"""

import csv
import datetime as dt
import json
import glob
import os
import sys
from collections import defaultdict

# Anchored to this file, not to the working directory. A relative path meant
# that running from anywhere but the repo root silently loaded ZERO matches and
# still produced a price -- a wrong number with no error attached.
# TENNIS_DATA overrides it for a checkout kept elsewhere.
DATA_DIR = os.environ.get("TENNIS_DATA") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "sackmann", "atp")
INCOMPLETE = ("RET", "W/O", "DEF", "WEA", "ABN", "Walkover", "Default", "UNK")


def _i(s):
    """CSV int or None -- these fields are frequently blank."""
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _f(v):
    """CSV float or None -- age is blank for a few thousand older rows."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ VALIDATE

def validate(svpt, f_in, f_won, s_won):
    """Arithmetic identities every genuine row must satisfy.

    first serves in cannot exceed points served; first-serve points won
    cannot exceed first serves in; second-serve points won cannot exceed
    the second-serve points that were actually played.
    """
    if svpt is None or svpt <= 0:
        return False
    if None in (f_in, f_won, s_won):
        return False
    if not 0 <= f_in <= svpt:
        return False
    if not 0 <= f_won <= f_in:
        return False
    if not 0 <= s_won <= svpt - f_in:
        return False
    return True


# ---------------------------------------------------------------- LOAD

class Match:
    __slots__ = ("tid", "tname", "surface", "level", "tourney_date", "rnd",
                 "best_of", "minutes", "score", "completed", "w_id", "l_id",
                 "w_svpt", "w_won", "l_svpt", "l_won", "has_stats",
                 "w_ioc", "l_ioc", "w_age", "l_age", "w_rank", "l_rank",
                 "w_bps", "w_bpf", "l_bps", "l_bpf", "draw_size",
                 "w_1in", "w_1won", "w_2won", "l_1in", "l_1won", "l_2won",
                 "w_entry", "l_entry", "w_seed", "l_seed", "w_hand", "l_hand")

    def __init__(self, r):
        self.tid = r["tourney_id"]
        self.tname = r["tourney_name"]
        self.surface = r["surface"] or "Unknown"
        self.level = r["tourney_level"]
        self.tourney_date = r["tourney_date"]      # TOURNAMENT START, not match date
        self.rnd = r["round"]
        self.best_of = _i(r["best_of"])
        # draw size separates "R32" the OPENING round of a 32-draw from
        # "R32" the third match of a 128-draw -- the same label, two
        # completely different situations
        self.draw_size = _i(r.get("draw_size"))
        self.minutes = _i(r["minutes"])
        self.score = r["score"] or ""
        self.completed = not any(t in self.score for t in INCOMPLETE) and bool(self.score)
        self.w_id, self.l_id = r["winner_id"], r["loser_id"]
        # nationality, for the home-advantage term.  Blank in a few thousand
        # older rows; None rather than "" so a missing country can never
        # accidentally equal a venue's missing country.
        self.w_ioc = (r.get("winner_ioc") or "").strip().upper() or None
        self.l_ioc = (r.get("loser_ioc") or "").strip().upper() or None

        # Columns the model has never used.  Carried as None when blank
        # rather than 0: an age of 0 and a rank of 0 are both meaningful
        # numbers that would quietly become the youngest and best player
        # on tour.
        self.w_age, self.l_age = _f(r.get("winner_age")), _f(r.get("loser_age"))
        self.w_rank = _i(r.get("winner_rank"))
        self.l_rank = _i(r.get("loser_rank"))
        # how each player got into the draw, and whether they were seeded.
        # Q qualified (three wins already), WC wild card, LL lucky loser,
        # PR protected ranking -- a player back from a long injury, which is
        # the one injury mark the archive carries explicitly.  Never used
        # before 2026-09-11.
        self.w_entry = (r.get("winner_entry") or "").strip().upper() or None
        self.l_entry = (r.get("loser_entry") or "").strip().upper() or None
        self.w_seed, self.l_seed = _i(r.get("winner_seed")), _i(r.get("loser_seed"))
        self.w_hand = (r.get("winner_hand") or "").strip().upper() or None
        self.l_hand = (r.get("loser_hand") or "").strip().upper() or None
        # break points: the only clutch measurement in the file
        self.w_bps, self.w_bpf = _i(r.get("w_bpSaved")), _i(r.get("w_bpFaced"))
        self.l_bps, self.l_bpf = _i(r.get("l_bpSaved")), _i(r.get("l_bpFaced"))

        ws, wi, w1, w2 = (_i(r["w_svpt"]), _i(r["w_1stIn"]),
                          _i(r["w_1stWon"]), _i(r["w_2ndWon"]))
        ls, li, l1, l2 = (_i(r["l_svpt"]), _i(r["l_1stIn"]),
                          _i(r["l_1stWon"]), _i(r["l_2ndWon"]))

        self.has_stats = validate(ws, wi, w1, w2) and validate(ls, li, l1, l2)
        if self.has_stats:
            self.w_svpt, self.w_won = ws, w1 + w2      # winner serving
            self.l_svpt, self.l_won = ls, l1 + l2      # loser serving
            # the same points, undivided: a serve is two stages, and two
            # players with one overall rate can have very different shapes
            self.w_1in, self.w_1won, self.w_2won = wi, w1, w2
            self.l_1in, self.l_1won, self.l_2won = li, l1, l2
        else:
            self.w_svpt = self.w_won = self.l_svpt = self.l_won = 0
            self.w_1in = self.w_1won = self.w_2won = 0
            self.l_1in = self.l_1won = self.l_2won = 0


# data/, NOT data/sackmann/ -- the mirror is a git checkout that update.py
# resets --hard, so a hand-maintained file inside it would be deleted on the
# next refresh.  update.py and the docstring above always meant this path.
MANUAL = os.path.join(
    os.path.dirname(os.path.dirname(DATA_DIR)) or ".", "manual_matches.csv")


class NoData(SystemExit):
    """Raised when the match archive is absent.

    The data is not distributed with this repository and cannot be (see
    NOTICE), so an empty data directory is the NORMAL state of a fresh clone,
    not an exotic failure. It therefore has to be reported as itself. Before
    this existed, `tennis.py fit` exited 0 on no data and wrote a structurally
    valid, entirely empty weights.json marked "converged": true -- which then
    masked the missing archive from every later command, permanently.
    """


def require_data(what="this command"):
    """Fail loudly and usefully when the archive is missing. Returns DATA_DIR."""
    import glob
    if os.path.isdir(DATA_DIR) and glob.glob(os.path.join(DATA_DIR,
                                                          "atp_matches_*.csv")):
        return DATA_DIR
    raise NoData(
        f"no match data, so {what} cannot run.\n\n"
        f"  looked in : {DATA_DIR}\n"
        f"  expected  : atp_matches_<year>.csv, one per season\n\n"
        "  This repository does not ship tennis data and cannot -- see NOTICE.\n"
        "  Put Jeff Sackmann's ATP match CSVs at the path above, then re-run.\n"
        "  Set TENNIS_DATA to point somewhere else.")


def load(y0=1968, y1=2026, qual_chall=False, manual=True):
    """Yields Match objects. Main tour only unless qual_chall=True.

    Also merges data/manual_matches.csv if present -- same 49-column schema,
    for results newer than the mirror's last snapshot.  Blank stat columns
    are fine; such rows load but do not contribute to ratings.
    """
    pat = "atp_matches_qual_chall_%d.csv" if qual_chall else "atp_matches_%d.csv"
    out, bad = [], 0
    for year in range(y0, y1 + 1):
        path = os.path.join(DATA_DIR, pat % year)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                try:
                    out.append(Match(r))
                except (KeyError, TypeError):
                    bad += 1

    if manual and not qual_chall and os.path.exists(MANUAL):
        # The manual file may OVERLAP the archive rather than only extend it.
        # A mirror snapshotted mid-tournament leaves that event in the archive
        # as results with every stat column blank, and the scrape then
        # supplies the same matches WITH stats.  Appending blindly counted
        # Roland Garros 2026 twice; keying the merge lets the better row win.
        seen = {(m.tourney_date, m.w_id, m.l_id, m.rnd): i
                for i, m in enumerate(out)}
        for r in csv.DictReader(open(MANUAL, newline="", encoding="utf-8")):
            try:
                m = Match(r)
            except (KeyError, TypeError):
                bad += 1
                continue
            if not (str(y0) <= m.tourney_date[:4] <= str(y1)):
                continue
            key = (m.tourney_date, m.w_id, m.l_id, m.rnd)
            j = seen.get(key)
            if j is None:
                seen[key] = len(out)
                out.append(m)
            elif m.has_stats and not out[j].has_stats:
                out[j] = m                      # the row that carries stats wins
    fill_iocs(out)
    fill_ages(out)
    return out, bad


# pid -> implied birthday in days since 2000-01-01, filled by fill_ages.
# Exposed because a live price has no match row to read an age off, and
# re-deriving it from one row would inherit that row's rounding -- the
# median below is the better estimate and both paths should use it.
BIRTHDAYS = {}


def _daynum(yyyymmdd):
    return (dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
            - dt.date(2000, 1, 1)).days


_BDAY_CACHE = os.path.join(os.path.dirname(MANUAL), "birthdays.json")
_AGE_SPREAD = {}   # pid -> [earliest, latest] implied birthday, for the gate


def _archive_stamp():
    """Every CSV the birthday table is derived from, with size and mtime, so
    the cache is keyed to the data and a refresh rebuilds it."""
    files = sorted(glob.glob(os.path.join(DATA_DIR, "atp_matches_*.csv")))
    if os.path.exists(MANUAL):
        files.append(MANUAL)
    return [[os.path.basename(f), os.path.getsize(f), int(os.path.getmtime(f))]
            for f in files]


def birthdays():
    """pid -> implied birthday (days since 2000-01-01), from EVERY row in
    the archive that carries an age -- main tour, qualifying and Challengers,
    every year -- so the table cannot depend on which files a caller loaded.

    Until 2026-09-11 fill_ages rebuilt BIRTHDAYS from whatever load() had
    just parsed, and the LAST call won.  weights.build ended up with the
    2013+ qualifying files' birthdays and the backtest harness with the
    2005+ ones; a player missing from the table silently got the base
    half-life instead of the age-decayed one, and the two derivations of the
    shipped ratings disagreed by hundreds of decayed points.  The gate that
    caught it is `backtest.py --gate`.

    Cached to data/birthdays.json, keyed on the archive's file list, sizes
    and mtimes.  The one-off scan costs a few seconds.
    """
    if BIRTHDAYS:
        return BIRTHDAYS
    stamp = _archive_stamp()
    try:
        with open(_BDAY_CACHE) as fh:
            c = json.load(fh)
        if c.get("stamp") == stamp:
            BIRTHDAYS.update(c["birthdays"])
            _AGE_SPREAD.update(c["spread"])
            return BIRTHDAYS
    except (OSError, ValueError, KeyError):
        pass
    seen = {}
    for f in [os.path.join(DATA_DIR, s[0]) if s[0] != os.path.basename(MANUAL)
              else MANUAL for s in stamp]:
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                d = None
                for side in ("winner", "loser"):
                    age = _f(r.get(f"{side}_age"))
                    if age:
                        if d is None:
                            d = _daynum(r["tourney_date"])
                        seen.setdefault(r[f"{side}_id"], []).append(
                            d - age * 365.25)
    # The MEDIAN over every dated age, not the mean.  The source's age
    # column is off by exactly one year on a scattering of rows -- 59
    # players of 4,539 show a spread near 365 days, and one shows five
    # years -- and a mean lets those rows drag the birthday by months.
    birth, spread = {}, {}
    for pid, v in seen.items():
        v = sorted(v)
        birth[pid] = v[len(v) // 2] if len(v) % 2 else \
            (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2.0
        spread[pid] = [v[0], v[-1]] if len(v) > 1 else [v[0]]
    # mutate in place, never rebind.  `from load import BIRTHDAYS` binds the
    # OBJECT at import time, so rebinding the module attribute leaves every
    # module that imported it holding the original empty dict -- which is
    # exactly what happened: an entire hyperparameter sweep ran with no
    # birthdays at all and every config came out identical to the baseline.
    BIRTHDAYS.update(birth)
    _AGE_SPREAD.update(spread)
    try:
        with open(_BDAY_CACHE, "w") as fh:
            json.dump({"stamp": stamp, "birthdays": birth, "spread": spread},
                      fh)
    except OSError:
        pass
    return BIRTHDAYS


def fill_ages(matches):
    """Back-fill a blank age.  This is arithmetic, not imputation.

    An age at one date fixes the birthday, and the birthday fixes the age at
    every other date.  So a player with a single dated age anywhere in the
    archive has a known age in every row -- which matters because the
    tennisabstract feed publishes no age column either, leaving all 851 rows
    of 2026 blank.

    The birthday table comes from birthdays(): the whole archive, once,
    whatever subset of it these matches are.  The residual spread of a
    player's implied birthday is pure rounding -- the source stores age to
    one decimal, so 0.1 yr = 37 days is the floor -- and load.py's gate
    asserts the MEDIAN spread stays near it and no derived age is absurd.

    Returns (rows filled, the table, pid -> [earliest, latest] implied
    birthday) -- the last for the gate's spread check.
    """
    birth = birthdays()
    filled = 0
    for m in matches:
        d = _daynum(m.tourney_date)
        for side in ("w", "l"):
            if getattr(m, f"{side}_age") is not None:
                continue
            b = birth.get(getattr(m, f"{side}_id"))
            if b is None:
                continue
            setattr(m, f"{side}_age", (d - b) / 365.25)
            filled += 1
    return filled, birth, _AGE_SPREAD


# Serve baseline by level, measured over 2015-2026.  A point at a Challenger
# is not a point on tour: the population serves 0.611 there against 0.637 in
# a main draw.  How much of that gap is CONDITIONS and how much is simply
# weaker players is not separable by inspection -- the within-player
# comparison comes out with the opposite sign, because the same player faces
# far better returners on tour -- so the correction is a fitted scalar, k,
# swept by tools/qcsweep.py.  k = 0 treats every point alike; k = 1 puts each
# level fully onto the main-draw baseline.
LEVEL_SERVE = {"C": 0.6109, "A": 0.6243, "G": 0.6242, "M": 0.6242}
MAIN_SERVE = 0.6374


def qc_records(y0, y1, k=1.0):
    """Qualifying and Challenger matches ALONE, on the main-draw scale.

    Returned separately from the tour so they can supplement what the
    ratings are FITTED on without joining what the model is SCORED on.
    Scoring them would change the match set and make every comparison
    incomparable, which is rule 1.

    Rows are the shared record layout (weights.rich): the first seven
    fields feed the single-number fit and the stage counts feed the
    three-stage fits, so both are fitted on the SAME matches.  Until
    2026-09-11 the supplement carried only the seven, the stages were fitted
    on the main tour alone, and every player rated from Challenger points
    had no stage rating -- price.Book.stage_serve then priced them at the
    tour average, worth +0.0068 nats of damage in the shipped path.

    The level shift k*(main - level) is applied to the points won, split
    across first and second serve in proportion to the points each was
    played on, so the three stages still sum to the single number.
    """
    from fit import to_day
    out = []
    for m in load(y0, y1, qual_chall=True, manual=False)[0]:
        if not m.has_stats:
            continue
        base = LEVEL_SERVE.get(m.level)
        if base is None:
            continue
        shift = k * (MAIN_SERVE - base) if k else 0.0

        def sh(won, pts):
            return min(max(won + shift * pts, 0.0), float(pts))

        w2d, l2d = m.w_svpt - m.w_1in, m.l_svpt - m.l_1in
        out.append((to_day(m.tourney_date), m.w_id, m.l_id,
                    float(m.w_svpt), sh(m.w_won, m.w_svpt),
                    float(m.l_svpt), sh(m.l_won, m.l_svpt),
                    m.best_of, m.surface,
                    m.w_1in, sh(m.w_1won, m.w_1in), sh(m.w_2won, w2d),
                    m.l_1in, sh(m.l_1won, m.l_1in), sh(m.l_2won, l2d)))
    out.sort(key=lambda r: r[0])
    return out


def load_with_qc(y0, y1, k=1.0, manual=True):
    """Main tour plus qualifying and Challengers, on one serving scale.

    Returns record tuples ready for fit_iterative, with each lower-level
    match's served-points-won shifted by k * (main baseline - that level's
    baseline).  Adding to the server's count subtracts from the returner's
    by construction, which is the right symmetry: the baseline says nothing
    about whether it is the serving or the returning that differs.
    """
    from fit import to_day
    out = []
    for ms, is_qc in ((load(y0, y1, manual=manual)[0], False),
                      (load(y0, y1, qual_chall=True, manual=False)[0], True)):
        for m in ms:
            if not m.has_stats:
                continue
            shift = 0.0
            if is_qc and k:
                base = LEVEL_SERVE.get(m.level)
                if base is None:
                    continue                 # unknown level: leave it out
                shift = k * (MAIN_SERVE - base)
            t = to_day(m.tourney_date)
            wn = min(max(m.w_won + shift * m.w_svpt, 0.0), float(m.w_svpt))
            ln = min(max(m.l_won + shift * m.l_svpt, 0.0), float(m.l_svpt))
            out.append((t, m.w_id, m.l_id, float(m.w_svpt), wn,
                        float(m.l_svpt), ln))
    out.sort(key=lambda r: r[0])
    return out


def fill_iocs(matches):
    """Back-fill a blank nationality from the same player's other matches.

    The tennisabstract feed publishes no country column, so every row newer
    than the frozen mirror -- all 847 of 2026 -- arrives with winner_ioc and
    loser_ioc blank.  Anything keyed on nationality would then silently drop
    the most recent season, which is the season being priced.

    Filled from the nearest known row in TIME, not from the most common
    value: a handful of players change federation mid-career, and the mode
    would keep assigning them the country they left.  Returns how many
    fields it filled so a caller can gate on it.
    """
    known = {}
    for m in matches:
        for pid, ioc in ((m.w_id, m.w_ioc), (m.l_id, m.l_ioc)):
            if ioc:
                known.setdefault(pid, []).append((m.tourney_date, ioc))
    for v in known.values():
        v.sort()
    filled = 0
    for m in matches:
        for side in ("w", "l"):
            if getattr(m, f"{side}_ioc"):
                continue
            hist = known.get(getattr(m, f"{side}_id"))
            if not hist:
                continue
            # last one at or before this match, else the earliest after it
            best = None
            for date, ioc in hist:
                if date <= m.tourney_date:
                    best = ioc
                else:
                    break
            setattr(m, f"{side}_ioc", best if best else hist[0][1])
            filled += 1
    return filled


# ------------------------------------------------------------- RATINGS

def player_totals(matches):
    """{player_id: [serve_won, serve_pts, return_won, return_pts]}.

    Return points come from the opponent's serve columns in the same row --
    a point the opponent served and did not win is a return point won.
    """
    t = defaultdict(lambda: [0, 0, 0, 0])
    for m in matches:
        if not m.has_stats:
            continue
        w, l = t[m.w_id], t[m.l_id]
        w[0] += m.w_won;              w[1] += m.w_svpt        # winner serving
        l[0] += m.l_won;              l[1] += m.l_svpt        # loser serving
        w[2] += m.l_svpt - m.l_won;   w[3] += m.l_svpt        # winner returning
        l[2] += m.w_svpt - m.w_won;   l[3] += m.w_svpt        # loser returning
    return t


_TBL = None


def data_asof():
    """Newest tourney_date in the data, as 'YYYY-MM-DD', or None.

    The as-of date of a price is today; the date the *data* stops is not, and
    the gap between them is how stale the number is.  Reads only the newest
    year file plus the manual sheet, so it costs nothing to call before
    printing a price.
    """
    dates = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR,
                                              "atp_matches_[0-9]*.csv")))[-1:] \
            + ([MANUAL] if os.path.exists(MANUAL) else []):
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    d = (r.get("tourney_date") or "").strip()
                    if len(d) == 8 and d.isdigit():
                        dates.append(d)
        except OSError:
            continue
    if not dates:
        return None
    d = max(dates)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def tour_avg(surface=None, era="recent_2015_2026", path="tour_avg.json"):
    """Empirical serve average for a surface. Falls back to all-surface.

    Use this rather than tennis_sim.TOUR_AVG_SERVE whenever the surface is
    known -- clay and grass differ by 4 points of serve, which is larger
    than most player-vs-player edges you will be trying to price.
    """
    global _TBL
    if _TBL is None:
        with open(os.path.join(os.path.dirname(__file__) or ".", path)) as fh:
            _TBL = json.load(fh)
    block = _TBL[era]
    return block.get(surface, block["all"])


def tour_average(matches):
    won = sum(m.w_won + m.l_won for m in matches if m.has_stats)
    pts = sum(m.w_svpt + m.l_svpt for m in matches if m.has_stats)
    return (won / pts if pts else 0.0), pts


# --------------------------------------------------------------- MAIN

if __name__ == "__main__":
    if not os.path.isdir(DATA_DIR):
        sys.exit(f"missing {DATA_DIR} -- clone the archive first")

    matches, bad = load()
    print(f"loaded {len(matches):,} main-tour matches, {bad} unparseable\n")

    # --- coverage: stats are patchy before ~2000, do not trust the early years
    print("stats coverage by decade")
    dec = defaultdict(lambda: [0, 0])
    for m in matches:
        d = dec[m.tourney_date[:3] + "0s"]
        d[0] += m.has_stats
        d[1] += 1
    for k in sorted(dec):
        got, tot = dec[k]
        bar = "#" * int(40 * got / tot)
        print(f"  {k}  {got:>6,}/{tot:<6,} {100*got/tot:5.1f}%  {bar}")

    # --- nationality, which the newest feed does not publish at all
    recent = [m for m in matches if m.tourney_date >= "20150101"]
    have = sum(1 for m in recent if m.w_ioc and m.l_ioc)
    print(f"\nIOC GATE  nationality after back-fill, 2015-2026")
    print(f"  {have:,}/{len(recent):,} matches carry both  "
          f"({have/len(recent):.2%})")
    # A player's country must not flip around inside one season -- that
    # would mean the back-fill is picking neighbours rather than history.
    by_year = defaultdict(set)
    for m in recent:
        for pid, ioc in ((m.w_id, m.w_ioc), (m.l_id, m.l_ioc)):
            if ioc:
                by_year[(pid, m.tourney_date[:4])].add(ioc)
    flips = sum(1 for v in by_year.values() if len(v) > 1)
    ioc_ok = have / len(recent) >= 0.99 and flips == 0
    print(f"  players with two countries inside one season: {flips}")
    print(f"  expected >=99% and 0 flips   ->  {'ok' if ioc_ok else 'FAIL'}")

    # --- age, which is back-filled by arithmetic and so must be consistent
    _n, _birth, seen = fill_ages(matches)
    spread = sorted(max(v) - min(v) for v in seen.values() if len(v) > 1)
    worst = spread[-1] if spread else 0.0
    aged = sum(1 for m in recent if m.w_age is not None and m.l_age is not None)
    print(f"\nAGE GATE  implied birthday, from ages the source does publish")
    print(f"  {aged:,}/{len(recent):,} matches carry both  "
          f"({aged/len(recent):.2%})")
    med = spread[len(spread) // 2] if spread else 0.0
    off_by_year = sum(1 for v in seen.values()
                      if len(v) > 1 and max(v) - min(v) > 180)
    print(f"  spread of one player's implied birthday: median "
          f"{med:.0f} d, worst {worst:.0f} d")
    print(f"  players whose source age is off by a year somewhere: "
          f"{off_by_year} of {len(spread):,}  (median birthday ignores them)")
    # What actually has to hold: rounding-level median spread, and no
    # back-filled age that is not a tennis player's age.
    ages = [a for m in recent for a in (m.w_age, m.l_age) if a is not None]
    lo, hi = min(ages), max(ages)
    print(f"  derived ages run {lo:.1f} to {hi:.1f}")
    age_ok = (med < 60 and aged / len(recent) >= 0.99
              and 14 <= lo and hi <= 50)
    print(f"  expected median <60 d (37 d is pure rounding) and ages in "
          f"[14, 50]   ->  {'ok' if age_ok else 'FAIL'}")

    # --- the M1 gate
    modern = [m for m in matches if m.tourney_date >= "20000101"]
    avg, pts = tour_average(modern)
    print(f"\nM1 GATE  tour average serve, 2000-2026")
    print(f"  {avg:.4f}   over {pts:,} service points")
    ok = (0.630 <= avg <= 0.660) and ioc_ok and age_ok
    print(f"  expected ~0.645   ->  {'ok' if ok else 'FAIL'}")

    # --- TOUR_AVG_SERVE is not a constant: show the drift
    print("\ntour average by surface (2000-2026)")
    surf = defaultdict(lambda: [0, 0])
    for m in modern:
        if m.has_stats:
            s = surf[m.surface]
            s[0] += m.w_won + m.l_won
            s[1] += m.w_svpt + m.l_svpt
    for k, (w, p) in sorted(surf.items(), key=lambda kv: -kv[1][0] / max(kv[1][1], 1)):
        if p > 10_000:
            print(f"  {k:<8} {w/p:.4f}   ({p:,} pts)")

    print("\ntour average by 5-year block")
    blk = defaultdict(lambda: [0, 0])
    for m in modern:
        if m.has_stats:
            b = 5 * (int(m.tourney_date[:4]) // 5)
            e = blk[b]
            e[0] += m.w_won + m.l_won
            e[1] += m.w_svpt + m.l_svpt
    for k in sorted(blk):
        w, p = blk[k]
        print(f"  {k}-{k+4}  {w/p:.4f}   ({p:,} pts)")

    # --- provenance: independent arithmetic, plus a coverage sanity read
    tot = sum(1 for m in matches if m.tourney_date >= "20000101")
    good = sum(1 for m in matches if m.tourney_date >= "20000101" and m.has_stats)
    print(f"\nintegrity   {good:,}/{tot:,} modern matches pass all arithmetic "
          f"identities ({100*good/tot:.1f}%)")
    print(f"            {tot-good:,} rejected (blank stats or impossible values)")

    tp = player_totals(modern)
    print(f"\n{len(tp):,} players with at least one rated point, 2000-2026")
    ranked = sorted((v for v in tp.values() if v[1] >= 5000), key=lambda v: -v[0] / v[1])
    print(f"{len(ranked):,} with >=5,000 service points")
    print(f"  best serve  {ranked[0][0]/ranked[0][1]:.4f}")
    print(f"  worst serve {ranked[-1][0]/ranked[-1][1]:.4f}")

    sys.exit(0 if ok else 1)
