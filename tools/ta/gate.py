"""Gate: does the reconstruction reproduce data the archive already has?

    python3 tools/ta/gate.py

Two independent checks, because the source is a scrape and a scrape can drift
silently:

  1. ACCURACY.  For matches the archive already contains, solve the counts
     from Tennis Abstract's published percentages and compare to Sackmann's
     actual integers.  These must agree exactly -- a rounded percentage
     admits only a handful of denominators, and only one of them is real.

  2. COMPLETENESS.  For the same overlapping window, the set of matches the
     site lists must equal the set the archive holds.  Accuracy on the rows
     you scraped means nothing if the scrape silently drops rows.

Run this after any change to the parser, the solver, or the site's layout.
It needs the cached pages in tools/ta/frags (tools/ta/refresh.py puts them
there) and the archive CSVs.
"""
import csv
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from parse_frag import parse
from build import CUT, MAIN_ROUNDS, is_main_tour, split_result, ta_date, clean
from recon import solve, best

FRAGS = os.path.join(HERE, "frags")
STATS = ("ace", "df", "svpt", "1stIn", "1stWon", "2ndWon")


def archive():
    """(tourney_date, round, player) -> that player's own serve counts."""
    out = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data/sackmann/atp",
                                           "atp_matches_20[0-9][0-9].csv"))):
        for r in csv.DictReader(open(p)):
            for who, pre in (("winner", "w"), ("loser", "l")):
                out[(r["tourney_date"], r["round"], r[f"{who}_name"])] = {
                    k: r[f"{pre}_{k}"] for k in STATS}
    return out


def main():
    arc = archive()
    known = {n for _d, _r, n in arc}
    exact = wrong = skipped = 0
    ta_seen, misses = {}, []

    for f in sorted(glob.glob(os.path.join(FRAGS, "*.js"))):
        key = os.path.basename(f)[:-3]
        owner = next((n for n in known if n.replace(" ", "") == key), None)
        if not owner:
            continue
        for row in parse(f):
            d = ta_date(row["date"])
            if d > CUT or not is_main_tour(row["tourney"]) \
                    or row["round"] not in MAIN_ROUNDS:
                continue
            sp = split_result(row["result"])
            if not sp or not row["score"].strip():
                continue
            ta_seen.setdefault(owner, set()).add((d, row["round"]))

            t = arc.get((d, row["round"], owner))
            if not t or not t["svpt"] or not (row["ace_pct"] or "").strip():
                skipped += 1
                continue
            got = best(solve(row["ace_pct"], row["df_pct"], row["first_in"],
                             row["first_pct"], row["second_pct"]),
                       row["score"])
            want = (int(t["svpt"]), int(t["ace"]), int(t["df"]),
                    int(t["1stIn"]), int(t["1stWon"]), int(t["2ndWon"]))
            if got == want:
                exact += 1
            else:
                wrong += 1
                misses.append((owner, d, row["round"], got, want))

    print("\n1. count reconstruction vs the archive's own integers")
    tot = exact + wrong
    print(f"   {exact}/{tot} exact"
          + (f"   ({skipped} rows had no stats to compare)" if skipped else ""))
    for m in misses[:6]:
        print(f"     MISMATCH {m[0]} {m[1]} {m[2]}: got {m[3]} want {m[4]}")

    print("\n2. completeness over the same window")
    miss_rows = extra_rows = 0
    for owner, seen in sorted(ta_seen.items()):
        lo = min(d for d, _r in seen)
        arc_set = {(d, r) for (d, r, n) in arc if n == owner and lo <= d <= CUT}
        miss_rows += len(arc_set - seen)
        extra_rows += len(seen - arc_set)
    print(f"   {len(ta_seen)} players checked")
    print(f"   in the archive but missing from the site : {miss_rows}")
    print(f"   on the site but missing from the archive : {extra_rows}")

    bad = wrong + miss_rows + extra_rows
    print(f"\n{'TA SOURCE GATE PASSES' if not bad else f'{bad} PROBLEM(S)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
