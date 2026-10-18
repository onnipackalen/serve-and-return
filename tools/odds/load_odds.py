"""Load tennis-data.co.uk ATP odds and join them to archive matches.

    python3 tools/odds/load_odds.py 2025        join report for one season

Source note: www.tennis-data.co.uk currently returns 503, but the bare
domain (no www) serves fine, and the files are .xlsx now rather than .zip.

THE JOIN IS THE WORK, as HANDOFF says.  Two different naming worlds:

    archive   "Carlos Alcaraz"      full first name
    odds      "Alcaraz C."          surname plus an initial

players.search already resolves surname-plus-initial in either order, so
the resolver does the heavy lifting.  What it cannot do is disambiguate two
players who share a surname AND an initial, so those are resolved against
the set of players actually in the match's own tournament first, and only
then against the whole tour.

Nothing here is allowed to peek: the join matches on names and dates only,
never on the result.
"""

import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from xlsx import rows_as_dicts
import players

# Excel's 1900 date system, including its deliberate leap-year bug: serial 1
# is 1900-01-01 and serial 60 is the non-existent 1900-02-29, so anchoring at
# 1899-12-30 makes every modern date come out right.
EXCEL_EPOCH = dt.date(1899, 12, 30)

ROUND_MAP = {
    "1st Round": "R1", "2nd Round": "R2", "3rd Round": "R3",
    "4th Round": "R4", "Quarterfinals": "QF", "Semifinals": "SF",
    "The Final": "F", "Round Robin": "RR",
}


def excel_date(v):
    try:
        return EXCEL_EPOCH + dt.timedelta(days=int(float(v)))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def load_season(path):
    """Rows with a usable closing price, as dicts."""
    out = []
    for r in rows_as_dicts(path):
        psw, psl = _f(r.get("PSW")), _f(r.get("PSL"))
        avgw, avgl = _f(r.get("AvgW")), _f(r.get("AvgL"))
        d = excel_date(r.get("Date"))
        if not d or not r.get("Winner") or not r.get("Loser"):
            continue
        out.append({
            "date": d,
            "tournament": r.get("Tournament", ""),
            "surface": r.get("Surface", ""),
            "round": ROUND_MAP.get(r.get("Round", ""), r.get("Round", "")),
            "best_of": r.get("Best of", ""),
            "winner": r["Winner"], "loser": r["Loser"],
            "wrank": r.get("WRank", ""), "lrank": r.get("LRank", ""),
            "psw": psw, "psl": psl, "avgw": avgw, "avgl": avgl,
            "comment": r.get("Comment", ""),
        })
    return out


def devig(o_win, o_lose):
    """Closing odds -> implied probability for the winner, vig removed.

    Both sides are inverted and renormalised, which removes the bookmaker's
    margin proportionally.  It is the standard treatment and the one the
    model has to beat.
    """
    if not o_win or not o_lose:
        return None
    iw, il = 1.0 / o_win, 1.0 / o_lose
    return iw / (iw + il)


def odds_name_key(name):
    """'Alcaraz C.' -> a query players.search understands."""
    return (name or "").replace(".", " ").strip()


def resolve(name, names_table, prominence, pool=None):
    """Best archive player for an odds-sheet name.

    `pool` restricts to ids known to be in this tournament, which is what
    separates two players sharing a surname and an initial.  Falling back to
    the whole tour is deliberate: a slightly wrong pool should degrade the
    match, not drop it.
    """
    q = odds_name_key(name)
    if pool:
        sub = {pid: n for pid, n in names_table.items() if pid in pool}
        hits = players.search(sub, q, prominence, limit=3)
        if hits and hits[0]["score"] >= players.INITIAL_LAST:
            return hits[0]
    hits = players.search(names_table, q, prominence, limit=3)
    return hits[0] if hits else None


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else "2025"
    path = os.path.join(HERE, "data", f"{year}.xlsx")
    if not os.path.exists(path):
        sys.exit(f"missing {path} -- run tools/odds/fetch.py first")
    rows = load_season(path)
    print(f"{len(rows)} rows with dates in {year}")
    have_ps = sum(1 for r in rows if r["psw"] and r["psl"])
    print(f"  with Pinnacle closing : {have_ps}")
    print(f"  date range            : {min(r['date'] for r in rows)} .. "
          f"{max(r['date'] for r in rows)}")
    for r in rows[:3]:
        p = devig(r["psw"], r["psl"])
        print(f"  {r['date']}  {r['winner']:<18} d. {r['loser']:<18} "
              f"PS {r['psw']}/{r['psl']}  devig P(win) {p:.4f}"
              if p else f"  {r['date']}  {r['winner']} d. {r['loser']}  (no PS)")
