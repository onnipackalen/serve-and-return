"""Refresh results past the archive's cutoff, from tennisabstract.com.

    python3 tools/ta/refresh.py            fetch what is missing, rebuild the CSV
    python3 tools/ta/refresh.py --seeds N  how deep into the rankings to seed
    python3 tools/ta/refresh.py --rebuild-only   re-emit from cached pages

Why this exists: Jeff Sackmann's GitHub repos are deleted and the
`Aneeshers` mirror stopped at 2026-06-25 (data to 2026-05-25).  His own site
is still live and current, so results after the cutoff come from there and
land in data/manual_matches.csv, which load.py merges.

What it costs in fidelity, stated plainly: the site publishes serve
*percentages*, not counts.  All five rates share one unknown denominator, so
brute-forcing the denominator against every rate at once recovers the counts
exactly -- verified 53/53 against matches the archive already had, and every
emitted row is re-checked against the site's published dominance ratio, which
is a function of BOTH players' totals and is never fed to the solver.

Matches whose stats the site has not published yet (a tournament still in
progress) are still written, with the score and blank stat columns.  load.py
accepts those and excludes them from ratings by design.

The fetch is polite (0.7s apart) and fully resumable: it skips pages already
on disk, so killing it loses nothing.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

RANK_URL = "https://www.tennisabstract.com/jsplayers/curr_rank_atp.js"


def refresh_rankings():
    """The seed list -- who to fetch first.  Cheap, so always take a fresh one."""
    path = os.path.join(HERE, "rank.js")
    subprocess.run(["curl", "-sL", "-m", "60", RANK_URL, "-o", path],
                   check=False)
    return os.path.exists(path) and os.path.getsize(path) > 10000


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=400,
                    help="how far down the rankings to seed the crawl")
    ap.add_argument("--rebuild-only", action="store_true",
                    help="skip the network; re-emit from cached pages")
    a = ap.parse_args()

    os.chdir(ROOT)
    if not a.rebuild_only:
        if not refresh_rankings():
            sys.exit("could not fetch the ranking list -- is the site up?")
        import fetch
        from fetch import fetch as get, key_of, ranked
        os.makedirs(os.path.join(HERE, "frags"), exist_ok=True)
        names = ranked(a.seeds)
        print(f"seeding from the top {len(names)} ranked players")
        ok = sum(get(key_of(n)) for n in names)
        print(f"  {ok}/{len(names)} pages")

        # opponents are the point: whoever beat a seed in round one is often
        # ranked well outside any seed list, and both players' pages are
        # needed to reconstruct both sides of a match
        import expand_lib
        expand_lib.close(get)

    import emit
    emit.main_emit()
    print("\nnow run:  python3 tennis.py gates && python3 tennis.py fit")


if __name__ == "__main__":
    main()
