"""M4 -- the gate.  Does the model beat the bookmaker's closing line?

    python3 tools/odds/m4.py 2025

Everything else in this project is measured against Elo, which knows only
who beat whom.  Closing odds are the real benchmark: they are the market's
final word, they already contain the information Elo lacks, and if the model
cannot match them then no further feature will save it.

Method, and the parts that matter:

  * model prices are WALK-FORWARD.  Each match is priced from a fit derived
    only from matches before it, exactly as backtest.py does.  Nothing here
    sees a result before pricing it.
  * the book's price is DEVIGGED.  Raw decimal odds sum to more than 1 in
    probability; the margin is removed proportionally so the comparison is
    against the market's opinion rather than its markup.
  * both sides are scored on the SAME matches, oriented the same way
    (probability assigned to the player who actually won), so log loss is
    directly comparable.

Beating closing on log loss is a strong claim and unlikely.  Matching it
would already be notable.  Losing to it by a little tells you where the gap
is; losing by a lot tells you the premise needs work.
"""

import collections
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import backtest as B
from fit import to_day
from join import archive_matches, join
from load_odds import load_season, devig


def record(year, rows, buckets):
    """Leave the headline where the app can read it: data/market_check.json,
    one entry per season, overwritten each time the season is re-scored."""
    path = os.path.join(ROOT, "data", "market_check.json")
    try:
        with open(path) as fh:
            cur = json.load(fh)
    except (OSError, ValueError):
        cur = {}
    mps = [r[0] for r in rows]
    bps = [r[1] for r in rows]
    cur[str(year)] = {
        "n": len(rows), "model": logloss(mps), "closing": logloss(bps),
        "gap": logloss(mps) - logloss(bps),
        "buckets": {b: {"n": len(v),
                        "model": logloss([x[0] for x in v]),
                        "closing": logloss([x[1] for x in v])}
                    for b, v in buckets.items() if v},
        "computed": dt.date.today().isoformat(),
        "note": "walk-forward model before the residual curves and news, "
                "against Pinnacle closing devigged proportionally; buckets "
                "are |model - closing|",
    }
    with open(path, "w") as fh:
        json.dump(cur, fh, indent=2)
    return path


def logloss(ps):
    return -sum(math.log(max(min(p, 1 - 1e-12), 1e-12)) for p in ps) / len(ps)


def brier(ps):
    return sum((1.0 - p) ** 2 for p in ps) / len(ps)


def main():
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    path = os.path.join(HERE, "data", f"{year}.xlsx")
    if not os.path.exists(path):
        sys.exit(f"missing {path}")

    print(f"M4: model vs Pinnacle closing, {year}\n")

    odds = [o for o in load_season(path) if o["psw"] and o["psl"]]
    matches = archive_matches(year - 1, year + 1)
    pairs, fails, _unres = join(odds, matches)
    print(f"joined {len(pairs):,}/{len(odds):,} odds rows to archive matches")

    # walk-forward model prices.  The burn-in inside walk_forward needs
    # several years of history before the season being scored.
    y0 = year - 10
    print(f"pricing walk-forward from {y0} (this is the slow part) ...",
          flush=True)
    recs = B.records(y0, year + 1)
    scale = B._FP.get("form_scale", 0.85)
    dens_w = B._FP.get("dens_w", 0.0)
    model_p = {}
    for idx, tup in B.walk_forward(recs, player_mode=True):
        day, w_id, l_id = recs[idx][0], recs[idx][1], recs[idx][2]
        model_p[(day, w_id, l_id)] = B.price_player(
            tup, scale, style_w=0.0, h2h_w=0.0, dens_w=dens_w)
    print(f"  priced {len(model_p):,} matches")

    rows = []
    for o, m in pairs:
        key = (to_day(m["date"].strftime("%Y%m%d")), m["w_id"], m["l_id"])
        mp = model_p.get(key)
        if mp is None:
            continue
        bp = devig(o["psw"], o["psl"])
        if bp is None:
            continue
        rows.append((mp, bp, o, m))

    if not rows:
        sys.exit("nothing to score -- the model priced none of the joined matches")

    mps = [r[0] for r in rows]
    bps = [r[1] for r in rows]
    print(f"\nscored on {len(rows):,} matches "
          f"(both a model price and a closing price)\n")

    print(f"  {'':<26} {'log loss':>9} {'brier':>8} {'acc':>7}")
    for nm, ps in (("model (walk-forward)", mps),
                   ("Pinnacle closing (devig)", bps)):
        acc = sum(1 for p in ps if p > 0.5) / len(ps)
        print(f"  {nm:<26} {logloss(ps):>9.5f} {brier(ps):>8.5f} {acc:>7.4f}")
    gap = logloss(mps) - logloss(bps)
    print(f"\n  gap: {gap:+.5f} nats "
          f"({'model is WORSE' if gap > 0 else 'model is BETTER'})")

    # where the disagreement lives
    print("\n  by how far the model departs from the market:")
    buckets = collections.defaultdict(list)
    for mp, bp, _o, _m in rows:
        d = abs(mp - bp)
        b = "0-2%" if d < .02 else "2-5%" if d < .05 else \
            "5-10%" if d < .10 else "10%+"
        buckets[b].append((mp, bp))
    for b in ("0-2%", "2-5%", "5-10%", "10%+"):
        v = buckets.get(b, [])
        if not v:
            continue
        m_ = logloss([x[0] for x in v])
        k_ = logloss([x[1] for x in v])
        print(f"    {b:<7} n={len(v):>5}   model {m_:.4f}   closing {k_:.4f}   "
              f"gap {m_-k_:+.4f}")

    print(f"\n  recorded in {os.path.relpath(record(year, rows, buckets), ROOT)}")

    # flat-stake test: bet when the model thinks the price is wrong
    print("\n  flat-stake betting on model edge (1 unit, closing price):")
    print(f"    {'edge':>6} {'bets':>6} {'won':>6} {'ROI':>8}")
    for thr in (0.02, 0.05, 0.08, 0.12):
        stake = won = ret = 0
        for mp, bp, o, _m in rows:
            # back the winner's side if the model likes it more than the book
            if mp - bp > thr:
                stake += 1
                won += 1
                ret += o["psw"] - 1
            # or the loser's side, where the model is lower than the book
            elif (1 - mp) - (1 - bp) > thr:
                stake += 1
                ret -= 1
        if stake:
            print(f"    {thr:>6.0%} {stake:>6} {won:>6} "
                  f"{ret/stake:>+8.2%}")
    print("\n  (a positive ROI at closing prices would be a real edge; "
          "at these sample sizes treat it as a hint, not a result)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
