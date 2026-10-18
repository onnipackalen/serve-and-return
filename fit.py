"""
Fit real ATP ratings with the M2 estimator.   python3 fit.py [start_year]

Bridges load.py -> ratings.fit_iterative.  Reports convergence explicitly:
an unconverged fit returns attenuated ratings that look entirely plausible,
so the sweep count is part of the output, not a debug detail.
"""

import csv
import datetime as dt
import os
import sys
import time
from collections import defaultdict

from load import load, DATA_DIR
from ratings import fit_iterative, fit_line, TOUR_AVG


def to_day(yyyymmdd):
    """Days since 2000-01-01.  NOTE: tourney_date is the tournament START
    date, shared by every match in the event -- decay is therefore coarse to
    the week.  Reconstructing true match dates from round order is M2b."""
    d = dt.date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    return (d - dt.date(2000, 1, 1)).days


def to_tuples(matches):
    out = []
    for m in matches:
        if not m.has_stats:
            continue
        out.append((to_day(m.tourney_date), m.w_id, m.l_id,
                    m.w_svpt, m.w_won, m.l_svpt, m.l_won))
    out.sort(key=lambda r: r[0])
    return out


def name_map(y0, y1):
    names = {}
    for y in range(y0, y1 + 1):
        p = os.path.join(DATA_DIR, f"atp_matches_{y}.csv")
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                names[r["winner_id"]] = r["winner_name"]
                names[r["loser_id"]] = r["loser_name"]
    return names


if __name__ == "__main__":
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2015
    y1 = 2026

    raw, _ = load(y0, y1)
    data = to_tuples(raw)
    names = name_map(y0, y1)
    asof = max(t for t, *_ in data)
    print(f"{len(data):,} rated matches, {y0}-{y1}, asof day {asof}\n")

    t0 = time.time()
    serve, ret, den, info = fit_iterative(data, asof=asof, half_life=730,
                                          prior_weight=300)
    el = time.time() - t0
    tag = "converged" if info["converged"] else "HIT THE CAP -- ratings attenuated"
    print(f"fit: {info['players']:,} players, {info['iters']} sweeps, "
          f"shift {info['shift']:.2e}, {el:.1f}s  -> {tag}\n")

    # raw (unadjusted) rates over the same decayed window, for comparison
    rn, rd = defaultdict(float), defaultdict(float)
    for t, a, b, asv, awn, bsv, bwn in data:
        w = 0.5 ** ((asof - t) / 730)
        rn[a] += w * awn; rd[a] += w * asv
        rn[b] += w * bwn; rd[b] += w * bsv
    rawr = {p: rn[p] / rd[p] for p in rd if rd[p] > 0}

    elig = [p for p in serve if den.get(p, 0) >= 1500]
    print(f"{len(elig)} players with >=1,500 decayed service points\n")

    print("top 12 serve, opponent-adjusted   (raw = unadjusted, d = adjustment)")
    for p in sorted(elig, key=lambda p: -serve[p])[:12]:
        d = serve[p] - rawr[p]
        print(f"  {names.get(p,p):<26} {serve[p]:.4f}   raw {rawr[p]:.4f}   d {d:+.4f}")

    print("\ntop 12 return, opponent-adjusted")
    for p in sorted(elig, key=lambda p: -ret[p])[:12]:
        print(f"  {names.get(p,p):<26} {ret[p]:.4f}")

    print("\nlargest adjustments -- who raw serve stats most mislead you about")
    mv = sorted(elig, key=lambda p: -abs(serve[p] - rawr[p]))[:8]
    for p in mv:
        d = serve[p] - rawr[p]
        why = "faced strong returners" if d > 0 else "faced weak returners"
        print(f"  {names.get(p,p):<26} {rawr[p]:.4f} -> {serve[p]:.4f}  "
              f"({d:+.4f}, {why})")

    sl, ic, rm = fit_line([rawr[p] for p in elig], [serve[p] for p in elig])
    madj = sum(serve[p] - rawr[p] for p in elig) / len(elig)
    print(f"\nadjusted vs raw: slope {sl:.3f}, mean adjustment {madj:+.4f}")
    print("  The adjustment is mostly a LEVEL shift, not a re-ranking.")
    print("  Winning a match earns you another one, so strong players appear")
    print("  far more often (top-50 ~3x the bottom-50) and the average")
    print("  OPPONENT is better than the average PLAYER.  Every raw serve %")
    print("  is therefore biased down by roughly this amount.")
    print("  serve[] means 'vs a league-average returner'; matchup_p puts the")
    print("  opponent effect back.  serve and ret shift together, so the two")
    print("  cancel in matchup_p and the tour-average level still holds.")
    sys.exit(0 if info["converged"] else 1)
