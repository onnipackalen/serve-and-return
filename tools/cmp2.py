"""Tour-wide vs per-player, paired, on identical matches and correct params."""
import math, time
from backtest import (records, walk_forward, price_tour, price_player, logloss,
                      score, fit_calibration, apply_cal, HALF_LIFE, PRIOR_W,
                      TRAIN_YEARS)

print(f"half_life={HALF_LIFE}  prior_weight={PRIOR_W}  train_years={TRAIN_YEARS}")
recs = records(2005, 2026)
t0 = time.time(); tour = dict(walk_forward(recs, player_mode=False)); print(f"tour  {time.time()-t0:.0f}s")
t0 = time.time(); play = dict(walk_forward(recs, player_mode=True)); print(f"play  {time.time()-t0:.0f}s")

idxs = sorted(set(tour) & set(play))
span = recs[idxs[-1]][0] - recs[idxs[0]][0]
cut = recs[idxs[0]][0] + span // 2
tr = [i for i in idxs if recs[i][0] < cut]
te = [i for i in idxs if recs[i][0] >= cut]
print(f"common {len(idxs):,}  train {len(tr):,} / test {len(te):,}\n")

out = {}
for nm, preds, fn, grid in (("tour-wide ", tour, price_tour, (0.02,0.03,0.035,0.04,0.05)),
                            ("per-player", play, price_player, (0.6,0.75,0.85,1.0,1.2))):
    best, bs = 1e9, None
    for g in grid:
        ll = logloss([fn(preds[i], g) for i in tr])
        if ll < best: best, bs = ll, g
    b = fit_calibration([fn(preds[i], bs) for i in tr])
    ps = [apply_cal(fn(preds[i], bs), b) for i in te]
    tll, tbr, tac, n = score(ps)
    out[nm] = ps
    print(f"  {nm}  param {bs:.3f}  cal {b:.3f}  TEST ll {tll:.5f}  "
          f"brier {tbr:.5f}  acc {tac:.4f}")

a, b_ = out["tour-wide "], out["per-player"]
d = [-math.log(max(x,1e-12)) + math.log(max(y,1e-12)) for x, y in zip(a, b_)]
m = sum(d)/len(d); sd = (sum((x-m)**2 for x in d)/(len(d)-1))**0.5; se = sd/len(d)**0.5
print(f"\npaired (tour - player): {m:+.5f} +/- {se:.5f}   t = {m/se:+.2f}")
print("  ->", "per-player better" if m/se > 2 else
      "tour-wide better" if m/se < -2 else "not distinguishable")
