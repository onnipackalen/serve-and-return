"""Score the model's TOTAL-GAMES predictions against what actually happened.

    python3 tools/totals.py [start_year]

The moneyline has been measured to death; the games distribution never has.
That matters because HANDOFF calls totals the highest-value build, and the
argument for it is specific: air density, wind and court speed are SYMMETRIC
-- both players share them -- so they barely move the match winner (dens_w
is worth 0.00006 there) but should move how long the match lasts.

No totals odds exist in the source, so there is no market to beat here.  The
question this answers is the one that has to come first: are the model's
games predictions even calibrated?  A totals model that is biased by two
games is not worth pricing against anyone.

Scored on walk-forward prices, against the realised score, so nothing sees
its own match.
"""

import collections
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import backtest as B
import fastgames as FG
from features import score_parts
from fit import to_day
from load import load

INCOMPLETE = ("RET", "W/O", "DEF", "WEA", "ABN", "Walkover", "Default", "UNK")


def realised_games(score):
    if not score or any(t in score.upper() for t in
                        ("W/O", "WALKOVER", "DEF", "RET")):
        return None
    sw, sl, gw, gl = score_parts(score, True)
    return gw + gl if (gw + gl) else None


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2015
    y1 = 2026
    matches, _ = load(y0 - 3, y1)
    truth = {}
    for m in matches:
        g = realised_games(m.score)
        if g:
            truth[(to_day(m.tourney_date), m.w_id, m.l_id)] = (g, m.best_of)

    print("pricing walk-forward (slow) ...", flush=True)
    recs = B.records(y0 - 3, y1)
    scale = B._FP.get("form_scale", 0.85)
    rows = []
    for idx, tup in B.walk_forward(recs, player_mode=True):
        key = (recs[idx][0], recs[idx][1], recs[idx][2])
        t = truth.get(key)
        if not t:
            continue
        pa, pb, bo = tup[0], tup[1], tup[2]
        rows.append((pa, pb, bo, t[0]))
    print(f"  {len(rows):,} matches with a price and a completed score\n")

    # 1. is the expected total unbiased?
    err = [FG.expected(pa, pb, bo) - g for pa, pb, bo, g in rows]
    n = len(err)
    mean_e = sum(err) / n
    mae = sum(abs(e) for e in err) / n
    sd = math.sqrt(sum((e - mean_e) ** 2 for e in err) / (n - 1))
    print("  EXPECTED TOTAL GAMES vs realised")
    print(f"    bias {mean_e:+.3f} games   MAE {mae:.3f}   SD {sd:.3f}"
          f"   SE(bias) {sd/math.sqrt(n):.3f}")

    by_bo = collections.defaultdict(list)
    for (pa, pb, bo, g), e in zip(rows, err):
        by_bo[bo].append(e)
    for bo in sorted(by_bo):
        v = by_bo[bo]
        m_ = sum(v) / len(v)
        print(f"    best of {bo}: n={len(v):>6,}  bias {m_:+.3f}  "
              f"MAE {sum(abs(x) for x in v)/len(v):.3f}")

    # 2. are the over/under probabilities calibrated?
    print("\n  OVER/UNDER CALIBRATION (predicted vs realised frequency)")
    print(f"    {'line':>7} {'bo':>3} {'n':>7} {'predicted':>10} "
          f"{'realised':>9} {'gap':>8}")
    for bo, lines in ((3, (19.5, 21.5, 22.5, 23.5, 25.5)),
                      (5, (35.5, 37.5, 39.5, 41.5))):
        for line in lines:
            v = [(pa, pb, g) for pa, pb, b_, g in rows if b_ == bo]
            if len(v) < 300:
                continue
            pred = sum(FG.p_over(pa, pb, line, bo) for pa, pb, _g in v) / len(v)
            real = sum(1 for _pa, _pb, g in v if g > line) / len(v)
            flag = "  <-- off" if abs(pred - real) > 0.03 else ""
            print(f"    {line:>7} {bo:>3} {len(v):>7,} {pred:>10.4f} "
                  f"{real:>9.4f} {pred-real:>+8.4f}{flag}")

    # 3. does the model DISCRIMINATE, or just predict the average?
    print("\n  DISCRIMINATION: sort matches by predicted total, decile realised")
    ranked = sorted(zip(rows, [FG.expected(pa, pb, bo)
                               for pa, pb, bo, _g in rows]),
                    key=lambda x: x[1])
    d = len(ranked) // 10
    print(f"    {'decile':>7} {'predicted':>10} {'realised':>9} {'n':>7}")
    for i in range(10):
        chunk = ranked[i * d:(i + 1) * d] if i < 9 else ranked[9 * d:]
        pr = sum(x[1] for x in chunk) / len(chunk)
        re = sum(x[0][3] for x in chunk) / len(chunk)
        print(f"    {i+1:>7} {pr:>10.2f} {re:>9.2f} {len(chunk):>7,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
