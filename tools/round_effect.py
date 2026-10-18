"""Does surviving rounds reveal information the rating has not absorbed?

    python3 tools/round_effect.py [start_year]

THE HYPOTHESIS.  Ratings are re-derived every REFIT_DAYS (91), so inside a
tournament nobody's rating moves.  A player who was rated poorly but has
already won three matches at this event has demonstrated something the price
does not know.  If that is true, such players should beat their price
systematically, and the effect should grow with the number of wins already
banked.

HOW IT IS MEASURED, and why this shape:

  * on WALK-FORWARD prices only.  Rule 5 in HANDOFF: never measure an effect
    on the data that fitted the ratings, because fit_iterative drives those
    residuals toward zero by construction.  These prices never saw their own
    match.
  * per PLAYER, not per match.  Each match contributes both players, so the
    two residuals cancel unless the players differ in wins-so-far.  Any
    signal that survives is asymmetry, which is exactly the claim.
  * by WINS ALREADY BANKED at this event, not by round name.  A round of 16
    means one win in a 32-draw and three in a 128-draw; "how much has this
    player shown us" is the actual quantity.
  * split by whether the player was RATED WEAK, because the claim is
    specifically about players the model underrates.

A residual near zero would mean the opponent adjustment already absorbs
this, which is what the VARIABLES table has assumed about `round` up to now.
"""

import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import backtest as B
import features as F
from fit import to_day
from load import load


def se_of_mean(xs):
    n = len(xs)
    if n < 2:
        return float("inf")
    m = sum(xs) / n
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(v / n)


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2015
    y1 = 2026
    print(f"round / survival effect, walk-forward {y0}-{y1}\n")

    matches, _bad = load(y0 - 3, y1)
    matches = [m for m in matches if m.tourney_date >= f"{y0-3}0101"]
    feats = F.build(matches)

    # meta keyed the same way m4.py keys, which avoids depending on the
    # index alignment of two separately-built lists
    meta = {}
    for m in matches:
        meta.setdefault((to_day(m.tourney_date), m.w_id, m.l_id), []).append(m)

    print("pricing walk-forward (slow) ...", flush=True)
    recs = B.records(y0 - 3, y1)
    scale = B._FP.get("form_scale", 0.85)
    dens_w = B._FP.get("dens_w", 0.0)
    rows = []
    for idx, tup in B.walk_forward(recs, player_mode=True):
        day, w_id, l_id = recs[idx][0], recs[idx][1], recs[idx][2]
        cand = meta.get((day, w_id, l_id))
        if not cand:
            continue
        m = cand[0]
        p_w = B.price_player(tup, scale, style_w=0.0, h2h_w=0.0, dens_w=dens_w)
        fw = feats.get((m.tid, m.rnd, w_id), {})
        fl = feats.get((m.tid, m.rnd, l_id), {})
        # one entry per player: (wins banked at this event, predicted, actual)
        rows.append((fw.get("event_matches", 0), p_w, 1, w_id, m))
        rows.append((fl.get("event_matches", 0), 1 - p_w, 0, l_id, m))
    print(f"  {len(rows)//2:,} matches, {len(rows):,} player-rows\n")

    def table(sel, label):
        print(f"  {label}")
        print(f"    {'wins so far':>12} {'n':>7} {'predicted':>10} "
              f"{'realised':>9} {'residual':>9} {'SE':>7}")
        by = collections.defaultdict(list)
        for wins, pred, act, _pid, _m in sel:
            k = min(wins, 4)
            by[k].append((pred, act))
        for k in sorted(by):
            v = by[k]
            pred = sum(x[0] for x in v) / len(v)
            act = sum(x[1] for x in v) / len(v)
            resid = [x[1] - x[0] for x in v]
            se = se_of_mean(resid)
            flag = ""
            if se and abs(act - pred) > 2 * se:
                flag = "  <-- significant"
            print(f"    {k if k < 4 else '4+':>12} {len(v):>7,} {pred:>10.4f} "
                  f"{act:>9.4f} {act-pred:>+9.4f} {se:>7.4f}{flag}")
        print()

    table(rows, "ALL players, by wins already banked at this event")

    # the claim is about players the model rates poorly.  Split on the
    # model's own opinion of them in this match, which is the thing that
    # would be wrong.
    weak = [r for r in rows if r[1] < 0.40]
    strong = [r for r in rows if r[1] > 0.60]
    table(weak, "players the model priced as UNDERDOGS (p < 0.40)")
    table(strong, "players the model priced as FAVOURITES (p > 0.60)")

    # NOT a table by round name.  Both players of a match share its round, so
    # per-player residuals cancel to exactly zero inside every round and the
    # table can only ever print 0.5000 / 0.5000 / +0.0000.  It looks like
    # "round has no effect" and is in fact arithmetic.  Round only carries
    # information through how the two players DIFFER, which is what the
    # wins-banked tables above measure.
    print("  (a by-round-name table is omitted on purpose: both players share")
    print("   a round, so per-player residuals cancel to zero by construction")
    print("   and such a table measures nothing.)")

    # pooled test of the actual claim: underdogs who have banked wins
    pool = [(p, a) for w, p, a, _pid, _m in rows if 1 <= w <= 3 and p < 0.40]
    if pool:
        pred = sum(x[0] for x in pool) / len(pool)
        act = sum(x[1] for x in pool) / len(pool)
        resid = [x[1] - x[0] for x in pool]
        se = se_of_mean(resid)
        print(f"\n  POOLED: underdogs (p<0.40) with 1-3 wins banked")
        print(f"    n={len(pool):,}   predicted {pred:.4f}   realised {act:.4f}"
              f"   residual {act-pred:+.4f}   SE {se:.4f}   "
              f"({(act-pred)/se:+.1f} SE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
