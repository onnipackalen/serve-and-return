"""Where does the model actually lose to the market?

    python3 tools/odds/disagree.py build     join odds + prices + features
    python3 tools/odds/disagree.py           analyse the cache
    python3 tools/odds/disagree.py bands     re-measure confidence.MEASURED_DEFICIT

M4 established that the model is 0.024 nats behind Pinnacle closing, and
that essentially all of it sits in matches where the model departs from the
market by 10%+.  That is a diagnosis, not an explanation.  This asks what
those matches have in common, because a feature that explains them is worth
more than another feature fitted to the average match.

Each candidate is scored the only way that matters: split the joined matches
on it, and compare the model's deficit inside each split.  A variable that
"looks associated" with disagreement but does not concentrate the LOSS is
not the answer.
"""

import collections
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

CACHE = os.path.join(HERE, "disagree_cache.json")


def build(years=(2024, 2025, 2026)):
    import backtest as B
    import features as F
    from fit import to_day
    from load import load
    from join import archive_matches, join
    from load_odds import load_season, devig

    lo, hi = min(years), max(years)
    matches, _ = load(lo - 11, hi)
    feats = F.build([m for m in matches if m.tourney_date >= f"{lo-11}0101"])
    print("pricing walk-forward (slow) ...", flush=True)
    recs = B.records(lo - 11, hi)
    scale = B._FP.get("form_scale", 0.85)
    dens_w = B._FP.get("dens_w", 0.0)
    model_p, den_at = {}, {}
    blk = {}
    for idx, tup in B.walk_forward(recs, player_mode=True, book_out=blk):
        key = (recs[idx][0], recs[idx][1], recs[idx][2])
        model_p[key] = B.price_player(
            tup, scale, style_w=0.0, h2h_w=0.0, dens_w=dens_w)
        # service points behind each rating AS OF THIS MATCH.  This used to
        # read them out of the shipped weights.json -- today's numbers, for
        # a match played two years ago -- which put well-measured players in
        # the thin bucket and made the confidence band's own check wrong.
        d = blk["book"].overall["den"]
        den_at[key] = (d.get(recs[idx][1], 0.0), d.get(recs[idx][2], 0.0))
    print(f"  priced {len(model_p):,}", flush=True)

    rows = []
    for year in years:
        p = os.path.join(HERE, "data", f"{year}.xlsx")
        if not os.path.exists(p):
            continue
        odds = [o for o in load_season(p) if o["psw"] and o["psl"]]
        arch = archive_matches(year - 1, year + 1)
        pairs, _f, _u = join(odds, arch)
        for o, m in pairs:
            key = (to_day(m["date"].strftime("%Y%m%d")), m["w_id"], m["l_id"])
            mp = model_p.get(key)
            bp = devig(o["psw"], o["psl"])
            if mp is None or bp is None:
                continue
            fw = feats.get((m["tid"], m["round"], m["w_id"]), {})
            fl = feats.get((m["tid"], m["round"], m["l_id"]), {})
            rows.append({
                "mp": mp, "bp": bp, "round": m["round"],
                "surface": m["tname"], "best_of": o["best_of"],
                "wrank": o["wrank"], "lrank": o["lrank"],
                "den_w": den_at.get(key, (0.0, 0.0))[0],
                "den_l": den_at.get(key, (0.0, 0.0))[1],
                "fw": {k: fw.get(k) for k in
                       ("ret_90d", "wo_90d", "comeback", "layoff_days",
                        "matches_28d", "event_gwp", "days_rest")},
                "fl": {k: fl.get(k) for k in
                       ("ret_90d", "wo_90d", "comeback", "layoff_days",
                        "matches_28d", "event_gwp", "days_rest")},
            })
    json.dump(rows, open(CACHE, "w"))
    print(f"  cached {len(rows):,} joined+priced matches")
    return rows


def ll(ps):
    return -sum(math.log(max(min(p, 1 - 1e-12), 1e-12)) for p in ps) / len(ps)


def split_report(rows, label, keyfn, order=None):
    """Model deficit vs the market inside each split of the data."""
    by = collections.defaultdict(list)
    for r in rows:
        k = keyfn(r)
        if k is not None:
            by[k].append(r)
    print(f"\n  {label}")
    print(f"    {'group':>22} {'n':>6} {'model':>8} {'market':>8} "
          f"{'deficit':>9} {'|disagree|':>11}")
    keys = order or sorted(by)
    for k in keys:
        v = by.get(k, [])
        if len(v) < 60:
            continue
        m_ = ll([r["mp"] for r in v])
        b_ = ll([r["bp"] for r in v])
        dis = sum(abs(r["mp"] - r["bp"]) for r in v) / len(v)
        print(f"    {str(k):>22} {len(v):>6,} {m_:>8.4f} {b_:>8.4f} "
              f"{m_-b_:>+9.4f} {dis:>11.4f}")


def bands(rows):
    """The model's deficit against closing INSIDE each confidence band.

    confidence.MEASURED_DEFICIT is what the tool prints beside a price as
    "how far to trust this one", and nothing in the refit chain updates it:
    it was measured once, in the M4-era odds study, and the model has
    improved several times since.  This re-measures it from the same cache
    the study used, so the number beside a price can be made current.

    The band is confidence.band() on the same three inputs the live path
    feeds it -- the thinner side's service points, the thinner side's
    matches in 28 days, and whether either player is back from a layoff.
    """
    import confidence as C
    by = collections.defaultdict(list)
    for r in rows:
        fw, fl = r["fw"], r["fl"]
        m28 = [x for x in (fw.get("matches_28d"), fl.get("matches_28d"))
               if x is not None]
        if not m28:
            continue
        f = C.features(min(r["den_w"], r["den_l"]), min(m28),
                       (fw.get("comeback") or 0) + (fl.get("comeback") or 0))
        by[C.band(f)].append(r)
    print(f"\n  confidence bands, deficit against Pinnacle closing")
    print(f"    {'band':>6} {'n':>6} {'model':>8} {'market':>8} {'deficit':>9}"
          f"   {'shipped':>8}")
    out = {}
    for _lo, _hi, name in C.BANDS:
        v = by.get(name, [])
        if not v:
            print(f"    {name:>6} {0:>6}   -- no matches in the cache --")
            continue
        m_ = ll([r["mp"] for r in v])
        b_ = ll([r["bp"] for r in v])
        out[name] = m_ - b_
        print(f"    {name:>6} {len(v):>6,} {m_:>8.4f} {b_:>8.4f} "
              f"{m_-b_:>+9.4f}   {C.MEASURED_DEFICIT.get(name, float('nan')):>+8.4f}")
    print("\n  shipped is confidence.MEASURED_DEFICIT, what a price prints today")
    print("  new dict: " + repr({k: round(v, 4) for k, v in out.items()}))
    return out


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "bands":
        if not os.path.exists(CACHE):
            sys.exit("no cache -- run: python3 tools/odds/disagree.py build")
        bands(json.load(open(CACHE)))
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
        return 0
    if not os.path.exists(CACHE):
        sys.exit("no cache -- run: python3 tools/odds/disagree.py build")
    rows = json.load(open(CACHE))
    print(f"{len(rows):,} matches with a model price and a closing price")
    print(f"  overall   model {ll([r['mp'] for r in rows]):.5f}   "
          f"market {ll([r['bp'] for r in rows]):.5f}   "
          f"deficit {ll([r['mp'] for r in rows])-ll([r['bp'] for r in rows]):+.5f}")

    def band(r):
        d = abs(r["mp"] - r["bp"])
        return "0-2%" if d < .02 else "2-5%" if d < .05 else \
            "5-10%" if d < .10 else "10%+"
    split_report(rows, "by disagreement size", band,
                 order=["0-2%", "2-5%", "5-10%", "10%+"])

    # how well-measured is the WORSE-measured player in the match?
    def thin(r):
        d = min(r["den_w"], r["den_l"])
        return "<1k pts" if d < 1000 else "1-3k" if d < 3000 else \
            "3-6k" if d < 6000 else "6k+"
    split_report(rows, "by how thin the worse-measured player's data is", thin,
                 order=["<1k pts", "1-3k", "3-6k", "6k+"])

    def injured(r):
        a = (r["fw"].get("ret_90d") or 0) + (r["fl"].get("ret_90d") or 0)
        w = (r["fw"].get("wo_90d") or 0) + (r["fl"].get("wo_90d") or 0)
        if a and w:
            return "both signals"
        if a:
            return "recent retirement"
        if w:
            return "recent walkover"
        return "none"
    split_report(rows, "by injury signal in the last 90 days", injured,
                 order=["none", "recent walkover", "recent retirement",
                        "both signals"])

    def comeback(r):
        c = (r["fw"].get("comeback") or 0) + (r["fl"].get("comeback") or 0)
        return "a player returning" if c else "neither returning"
    split_report(rows, "by first match back from 60+ days out", comeback)

    def rankgap(r):
        try:
            g = abs(int(r["wrank"]) - int(r["lrank"]))
        except (TypeError, ValueError):
            return None
        return "<20" if g < 20 else "20-60" if g < 60 else \
            "60-150" if g < 150 else "150+"
    split_report(rows, "by ranking gap", rankgap,
                 order=["<20", "20-60", "60-150", "150+"])

    split_report(rows, "by best-of", lambda r: f"best of {r['best_of']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
