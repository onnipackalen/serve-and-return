"""Crawl opponents to closure, so both sides of every match are available.

A match's counts can only be reconstructed if BOTH players' pages are on
disk -- each page carries only its own player's serve stats.  The seed list
is a ranking cut, but the person who beats a seed in round one is frequently
ranked outside it, so the player set has to be derived from the matches
themselves rather than assumed.
"""
import glob
import os

from parse_frag import parse
from build import ta_date, is_main_tour, MAIN_ROUNDS, CUT

HERE = os.path.dirname(os.path.abspath(__file__))
FRAGS = os.path.join(HERE, "frags")


def wanted():
    """Opponent keys named in any post-cutoff main-draw match."""
    need = set()
    for f in glob.glob(os.path.join(FRAGS, "*.js")):
        for r in parse(f):
            if ta_date(r["date"]) <= CUT:
                continue
            if not is_main_tour(r["tourney"]) or r["round"] not in MAIN_ROUNDS:
                continue
            if r["opp_key"]:
                need.add(r["opp_key"])
    return need


def have():
    return {os.path.basename(p)[:-3]
            for p in glob.glob(os.path.join(FRAGS, "*.js"))}


def close(get, max_rounds=4):
    """Fetch until no post-cutoff match names a player we do not have."""
    for rnd in range(1, max_rounds + 1):
        todo = sorted(wanted() - have())
        if not todo:
            print(f"opponent crawl: closed after {rnd - 1} round(s)")
            return
        print(f"opponent crawl round {rnd}: {len(todo)} to fetch")
        ok = sum(get(k) for k in todo)
        print(f"  {ok}/{len(todo)} pages")
    print("opponent crawl: hit the round cap; some matches may stay one-sided")
