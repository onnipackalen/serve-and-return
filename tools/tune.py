"""
Hyperparameter sweep.   python3 tune.py [start_year]

half_life, prior_weight and the training window have been chosen rather than
fitted since M2.  This fits them.

Two stages, because a full per-player walk-forward costs ~160s and a wide
grid of those would take hours:

  1. WIDE, in tour-wide mode (~10s per run) to find the region
  2. CONFIRM the best few in per-player mode, which is what actually ships

Selection happens on TRAIN only.  TEST is scored once, for the winner, at the
end -- searching a grid against the test set is just overfitting with extra
steps.

EVERY CONFIG IS SCORED ON THE SAME MATCHES.  This is not a detail.  A shorter
half-life means fewer players clear MIN_PTS, so it scores a SMALLER and
EASIER subset -- matches between well-established players.  Comparing raw log
loss across configs then rewards shrinking the sample, not predicting better:
half_life 270 "beat" 1460 by 0.008 while scoring 29,037 matches against
36,916.  All comparisons below run on the intersection.
"""

import json
import sys
import time

from backtest import (records, walk_forward, price_tour, price_player,
                      logloss, score, fit_calibration, apply_cal)

HALF_LIVES = (270, 365, 548, 730, 1095, 1460)
PRIOR_WEIGHTS = (75, 150, 300, 600)
TRAIN_YEARS = (5, 8, 12)


def split(recs, idxs):
    span = recs[idxs[-1]][0] - recs[idxs[0]][0]
    cut = recs[idxs[0]][0] + span // 2
    return ([i for i in idxs if recs[i][0] < cut],
            [i for i in idxs if recs[i][0] >= cut])


def best_form(preds, tr, player, grid):
    b, bs = 1e9, None
    for g in grid:
        ll = logloss([(price_player(preds[i], g) if player
                       else price_tour(preds[i], g)) for i in tr])
        if ll < b:
            b, bs = ll, g
    return b, bs


if __name__ == "__main__":
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2005
    recs = records(y0, 2026)
    print(f"{len(recs):,} matches {y0}-2026\n")

    print("STAGE 1 -- wide grid, tour-wide mode")
    store = {}
    for hl in HALF_LIVES:
        for pw in PRIOR_WEIGHTS:
            t0 = time.time()
            store[(hl, pw)] = dict(walk_forward(recs, half_life=hl,
                                                prior_weight=pw))
            print(f"   ran half_life {hl:>5} prior_w {pw:>4}   "
                  f"{len(store[(hl,pw)]):>7,} scorable   "
                  f"{time.time()-t0:.0f}s", flush=True)

    common = set.intersection(*(set(v) for v in store.values()))
    print(f"\n  common scorable set: {len(common):,} matches "
          f"(vs {max(len(v) for v in store.values()):,} for the loosest config)")
    print(f"  every config below is scored on those same matches.\n")

    idxs = sorted(common)
    tr, te = split(recs, idxs)
    print(f"{'half_life':>10} {'prior_w':>8}   {'train ll':>9}")
    rows = []
    for (hl, pw), preds in store.items():
        ll, sd = best_form(preds, tr, False, (0.02, 0.03, 0.04, 0.05, 0.06))
        rows.append((ll, hl, pw, 8, sd, len(common)))
        print(f"{hl:>10} {pw:>8}   {ll:>9.5f}", flush=True)

    rows.sort()
    print(f"\n  best: half_life={rows[0][1]}, prior_weight={rows[0][2]}")

    print("\nSTAGE 1b -- training window, at the best half_life/prior_weight")
    _, hl0, pw0 = rows[0][1], rows[0][1], rows[0][2]
    hl0 = rows[0][1]
    ystore = {yy: dict(walk_forward(recs, half_life=hl0, prior_weight=pw0,
                                    train_years=yy)) for yy in TRAIN_YEARS}
    ycommon = sorted(set.intersection(*(set(v) for v in ystore.values()))
                     & common)
    ytr, _ = split(recs, ycommon)
    ywin = []
    for yy, preds in ystore.items():
        ll, sd = best_form(preds, ytr, False, (0.02, 0.03, 0.04, 0.05, 0.06))
        ywin.append((ll, yy))
        print(f"   train_years {yy:>3}   train ll {ll:.5f}  "
              f"({len(ycommon):,} common matches)", flush=True)
    ywin.sort()
    yrs = ywin[0][1]
    print(f"   -> {yrs}")

    print(f"\nSTAGE 2 -- confirm top 3 in per-player mode "
          f"(train_years={yrs})")
    pstore = {}
    for ll0, hl, pw, _, _, _ in rows[:3]:
        t0 = time.time()
        pstore[(hl, pw)] = dict(walk_forward(recs, half_life=hl,
                                             prior_weight=pw,
                                             train_years=yrs,
                                             player_mode=True))
        print(f"   ran half_life {hl:>5} prior_w {pw:>4}   "
              f"{time.time()-t0:.0f}s", flush=True)
    pcommon = sorted(set.intersection(*(set(v) for v in pstore.values())))
    ptr, pte = split(recs, pcommon)
    print(f"   common set {len(pcommon):,} matches")
    finals = []
    for (hl, pw), preds in pstore.items():
        ll, sc = best_form(preds, ptr, True, (0.6, 0.75, 0.85, 1.0, 1.2))
        finals.append((ll, hl, pw, sc, preds, ptr, pte))
        print(f"   half_life {hl:>5}  prior_w {pw:>4}   train ll {ll:.5f}"
              f"   scale {sc:.2f}", flush=True)

    finals.sort(key=lambda r: r[0])
    ll, hl, pw, sc, preds, tr, te = finals[0]
    b = fit_calibration([price_player(preds[i], sc) for i in tr])
    test = [apply_cal(price_player(preds[i], sc), b) for i in te]
    tll, tbr, tac, n = score(test)

    print(f"\n{'='*60}\nWINNER  half_life={hl}  prior_weight={pw}  "
          f"train_years={yrs}  form_scale={sc:.2f}")
    print(f"TEST ({n:,} matches)  log loss {tll:.5f}   brier {tbr:.5f}"
          f"   acc {tac:.4f}")

    try:
        fp = json.load(open("fitted_params.json"))
    except OSError:
        fp = {}
    fp.update({"half_life_days": hl, "prior_weight": pw, "train_years": yrs,
               "form_scale": sc, "calibration_b": b, "test_log_loss": tll,
               "tuned_on": f"{y0}-2026 walk-forward, train half only"})
    json.dump(fp, open("fitted_params.json", "w"), indent=2)
    print("\nwrote fitted_params.json")
