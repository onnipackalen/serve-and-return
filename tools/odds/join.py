"""Join bookmaker rows to archive matches, and report honestly on the misses.

    python3 tools/odds/join.py 2025

Matching is on PLAYERS plus DATE PROXIMITY, never on the result:

  * the archive dates a match by when its TOURNAMENT started, the odds sheet
    by the day it was played, so the two differ by up to a fortnight.  A
    window, not an equality.
  * the same pair can meet twice in a season, so ties inside the window go
    to the nearest date.

A join is only trustworthy if you know what it dropped, so the report breaks
the failures down by cause instead of printing one percentage.
"""

import collections
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import csv
import glob
import players
from load_odds import load_season, devig, resolve, odds_name_key

WINDOW = 20         # days between tournament start and a late-round match


def archive_matches(y0, y1):
    """Archive rows with ids, names and dates -- the CSV directly, because
    load.Match drops player names and this join needs them to be audited."""
    out = []
    files = [f"data/sackmann/atp/atp_matches_{y}.csv" for y in range(y0, y1 + 1)]
    files = [f for f in files if os.path.exists(os.path.join(ROOT, f))]
    if os.path.exists(os.path.join(ROOT, "data/manual_matches.csv")):
        files.append("data/manual_matches.csv")
    for f in files:
        for r in csv.DictReader(open(os.path.join(ROOT, f))):
            d = r["tourney_date"]
            if not (d and len(d) == 8):
                continue
            y = int(d[:4])
            if not (y0 <= y <= y1):
                continue
            out.append({
                "date": dt.date(int(d[:4]), int(d[4:6]), int(d[6:])),
                "w_id": r["winner_id"], "l_id": r["loser_id"],
                "w_name": r["winner_name"], "l_name": r["loser_name"],
                "tname": r["tourney_name"], "round": r["round"],
                "tid": r["tourney_id"], "score": r["score"],
                "has_stats": bool(r["w_svpt"] and r["l_svpt"]),
            })
    return out


def name_table(matches):
    t = {}
    for m in matches:
        t[m["w_id"]] = m["w_name"]
        t[m["l_id"]] = m["l_name"]
    return t


def build_prominence(matches):
    c = collections.Counter()
    for m in matches:
        c[m["w_id"]] += 1
        c[m["l_id"]] += 1
    return lambda pid: c.get(pid, 0)


def join(odds_rows, matches, window=WINDOW):
    """[(odds_row, archive_match)] plus a breakdown of what failed."""
    names = name_table(matches)
    prom = build_prominence(matches)
    by_pair = collections.defaultdict(list)
    for m in matches:
        by_pair[(m["w_id"], m["l_id"])].append(m)

    # players seen around each date, to disambiguate a shared surname+initial
    by_date = collections.defaultdict(set)
    for m in matches:
        by_date[m["date"]].add(m["w_id"])
        by_date[m["date"]].add(m["l_id"])

    def pool_for(d):
        pool = set()
        for k in range(-window, window + 1):
            pool |= by_date.get(d + dt.timedelta(days=k), set())
        return pool

    pairs, fails = [], collections.Counter()
    unresolved = collections.Counter()
    for o in odds_rows:
        pool = pool_for(o["date"])
        w = resolve(o["winner"], names, prom, pool)
        l = resolve(o["loser"], names, prom, pool)
        if not w or not l:
            fails["name did not resolve"] += 1
            if not w:
                unresolved[o["winner"]] += 1
            if not l:
                unresolved[o["loser"]] += 1
            continue
        if w["id"] == l["id"]:
            fails["both names resolved to one player"] += 1
            continue
        cands = by_pair.get((w["id"], l["id"]), [])
        near = [m for m in cands if abs((m["date"] - o["date"]).days) <= window]
        if not near:
            # the pair may exist but with the archive recording the other
            # winner, which would be a genuine data disagreement worth seeing
            rev = by_pair.get((l["id"], w["id"]), [])
            if any(abs((m["date"] - o["date"]).days) <= window for m in rev):
                fails["winner disagrees with archive"] += 1
            else:
                fails["no archive match for this pair+date"] += 1
            continue
        m = min(near, key=lambda m: abs((m["date"] - o["date"]).days))
        pairs.append((o, m))
    return pairs, fails, unresolved


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    path = os.path.join(HERE, "data", f"{year}.xlsx")
    if not os.path.exists(path):
        sys.exit(f"missing {path}")
    odds = [o for o in load_season(path) if o["psw"] and o["psl"]]
    matches = archive_matches(year - 1, year + 1)
    print(f"odds rows with Pinnacle closing : {len(odds):,}")
    print(f"archive matches {year-1}-{year+1}        : {len(matches):,}")

    pairs, fails, unresolved = join(odds, matches)
    print(f"\njoined                          : {len(pairs):,}  "
          f"({len(pairs)/len(odds):.1%})")
    for k, v in fails.most_common():
        print(f"  {k:<34} {v:,}")
    if unresolved:
        print("\n  most common unresolved names:")
        for n, c in unresolved.most_common(8):
            print(f"    {n!r:26} {c}")

    # audit: the join must not be silently pairing the wrong people
    print("\n  sample joins:")
    for o, m in pairs[:5]:
        print(f"    {o['date']}  {o['winner']:<16} d. {o['loser']:<16} -> "
              f"{m['date']}  {m['w_name']} d. {m['l_name']}  ({m['tname']})")
    stats = sum(1 for _o, m in pairs if m["has_stats"])
    print(f"\n  joined matches the model can price (have serve stats): "
          f"{stats:,}/{len(pairs):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
