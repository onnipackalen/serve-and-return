"""
Head-to-head config comparison on the largest possible common set.

The extended sweep's common set collapsed to 12,403 matches because one
candidate (half_life=120) qualifies far fewer players.  Including a
restrictive config in the intersection costs every other comparison its
statistical power.  This compares only the two that matter.
"""
import math, time
from backtest import (records, walk_forward, price_player, logloss, score,
                      fit_calibration, apply_cal)

A = (730, 300, 8)     # previously shipped
B = (270, 150, 5)     # sweep winner
SCALES = (0.6, 0.75, 0.85, 1.0, 1.2)

recs = records(2005, 2026)
store = {}
for hl, pw, yy in (A, B):
    t0 = time.time()
    store[(hl, pw, yy)] = dict(walk_forward(recs, half_life=hl, prior_weight=pw,
                                            train_years=yy, player_mode=True))
    print(f"  hl={hl} pw={pw} yrs={yy}  {len(store[(hl,pw,yy)]):,} scorable "
          f"({time.time()-t0:.0f}s)", flush=True)

common = sorted(set(store[A]) & set(store[B]))
span = recs[common[-1]][0] - recs[common[0]][0]
cut = recs[common[0]][0] + span // 2
tr = [i for i in common if recs[i][0] < cut]
te = [i for i in common if recs[i][0] >= cut]
print(f"\ncommon {len(common):,}   train {len(tr):,} / test {len(te):,}\n")

res = {}
for k, preds in store.items():
    best, bs = 1e9, None
    for sc in SCALES:
        ll = logloss([price_player(preds[i], sc) for i in tr])
        if ll < best: best, bs = ll, sc
    b = fit_calibration([price_player(preds[i], bs) for i in tr])
    ps = [apply_cal(price_player(preds[i], bs), b) for i in te]
    tll, tbr, tac, n = score(ps)
    res[k] = (tll, tbr, tac, bs, b, ps)
    print(f"  hl={k[0]:<4} pw={k[1]:<4} yrs={k[2]}  scale {bs:.2f}  "
          f"TEST ll {tll:.5f}  brier {tbr:.5f}  acc {tac:.4f}")

# paired test: the two models see identical matches, so compare per-match
pa, pb = res[A][5], res[B][5]
d = [-math.log(max(x,1e-12)) + math.log(max(y,1e-12)) for x, y in zip(pa, pb)]
mean = sum(d)/len(d)
sd = (sum((x-mean)**2 for x in d)/(len(d)-1))**0.5
se = sd/len(d)**0.5
print(f"\npaired difference (A - B) per match: {mean:+.5f} +/- {se:.5f} (SE)")
print(f"  t = {mean/se:+.2f}   ->  ", end="")
print("B is significantly better" if mean/se > 2 else
      "A is significantly better" if mean/se < -2 else
      "NOT statistically distinguishable")
