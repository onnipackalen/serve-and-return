"""
Extended sweep.   python3 tune2.py

The first sweep put the optimum at the EDGE of the grid on two axes
(half_life=270, train_years=5), which means it found the boundary, not the
optimum.  This searches below both.

It also settles the old-vs-new comparison honestly.  The new config scores
fewer matches (a shorter half-life means fewer players clear MIN_PTS), so
comparing raw test log loss across configs rewards shrinking the sample.
Everything below is scored on the intersection.
"""

import json
import time

from backtest import (records, walk_forward, price_player, logloss, score,
                      fit_calibration, apply_cal)

CONFIGS = [
    (730, 300, 8),      # what shipped before
    (270, 150, 5),      # winner of the first sweep
    (180, 150, 5),
    (180, 75, 5),
    (120, 150, 5),
    (120, 75, 4),
    (220, 150, 4),
    (270, 150, 3),
]
SCALES = (0.6, 0.75, 0.85, 1.0, 1.2, 1.4)


if __name__ == "__main__":
    recs = records(2005, 2026)
    print(f"{len(recs):,} matches\n")

    store = {}
    for hl, pw, yy in CONFIGS:
        t0 = time.time()
        store[(hl, pw, yy)] = dict(walk_forward(
            recs, half_life=hl, prior_weight=pw, train_years=yy,
            player_mode=True))
        print(f"  ran hl={hl:<5} pw={pw:<4} yrs={yy}   "
              f"{len(store[(hl,pw,yy)]):>7,} scorable   "
              f"{time.time()-t0:.0f}s", flush=True)

    common = sorted(set.intersection(*(set(v) for v in store.values())))
    span = recs[common[-1]][0] - recs[common[0]][0]
    cut = recs[common[0]][0] + span // 2
    tr = [i for i in common if recs[i][0] < cut]
    te = [i for i in common if recs[i][0] >= cut]
    print(f"\ncommon set {len(common):,}  (train {len(tr):,} / test {len(te):,})")
    print("every config scored on exactly these matches\n")

    print(f"{'half_life':>10} {'prior_w':>8} {'years':>6} {'scale':>6}"
          f"   {'train ll':>9}   {'TEST ll':>9} {'brier':>8} {'acc':>7}")
    out = []
    for (hl, pw, yy), preds in store.items():
        best, bs = 1e9, None
        for sc in SCALES:
            ll = logloss([price_player(preds[i], sc) for i in tr])
            if ll < best:
                best, bs = ll, sc
        b = fit_calibration([price_player(preds[i], bs) for i in tr])
        tll, tbr, tac, _ = score([apply_cal(price_player(preds[i], bs), b)
                                  for i in te])
        out.append((tll, hl, pw, yy, bs, b, best))
        tag = "  <- previous" if (hl, pw, yy) == (730, 300, 8) else ""
        print(f"{hl:>10} {pw:>8} {yy:>6} {bs:>6.2f}   {best:>9.5f}   "
              f"{tll:>9.5f} {tbr:>8.5f} {tac:>7.4f}{tag}", flush=True)

    # selection on TRAIN, never on TEST
    out.sort(key=lambda r: r[6])
    tll, hl, pw, yy, sc, b, trll = out[0]
    prev = [r for r in out if (r[1], r[2], r[3]) == (730, 300, 8)][0]
    print(f"\n{'='*66}")
    print(f"BEST ON TRAIN   half_life={hl}  prior_weight={pw}  train_years={yy}"
          f"  form_scale={sc:.2f}")
    print(f"  test log loss {tll:.5f}   vs previous config {prev[0]:.5f}"
          f"   ({prev[0]-tll:+.5f})")

    fp = json.load(open("fitted_params.json"))
    fp.update({"half_life_days": hl, "prior_weight": pw, "train_years": yy,
               "form_scale": sc, "calibration_b": b, "test_log_loss": tll,
               "tuned_on": "2005-2026 walk-forward, common-set, train half only"})
    json.dump(fp, open("fitted_params.json", "w"), indent=2)
    print("\nwrote fitted_params.json")
