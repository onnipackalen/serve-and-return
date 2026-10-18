"""
How much should you trust this particular price?

    python3 confidence.py fit      derive the bands from walk-forward residuals
    python3 confidence.py          show the bands

A single log loss describes the model on average and tells you nothing
about the match in front of you.  The disagreement study showed the average
hides a lot: matches where the model departs from the market by 10%+ carry
a +0.075 deficit while matches where it agrees carry -0.000, and a player
returning from a long absence roughly doubles the error.

So confidence is not a feeling attached to a number.  It is a PREDICTION of
how large this model's error tends to be on matches that look like this one,
fitted the same way everything else here is fitted:

  * the inputs are all knowable BEFORE the match -- how well-measured the
    two players are, how volatile their form, whether either is returning
    from a layoff, and how far the model's price sits from a coin flip
  * it is fitted on WALK-FORWARD residuals, so it never saw its own match
  * it is scored out of sample, and reported as realised log loss per band,
    which is the only claim that matters: a band saying "low confidence"
    must actually lose more.

What it is NOT: a probability that the pick is right.  A 60% favourite in a
HIGH band is still a 60% favourite; the band says the 60% is trustworthy.
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) or "."
MODEL = os.path.join(HERE, "confidence_model.json")


def features(min_pts, matches_28d_min, comeback):
    """The band's inputs, all knowable before the match.

    RE-DERIVED 2026-09-16 on the residual cache, which now carries the
    service points behind each rating and the model's own form_sd
    (tools/curves.py build).  What the earlier version measured and what a
    live price computed were not the same band: `fit` had no service-point
    count, substituted a recent-match count for it and pinned the
    volatility term to a constant, and the resulting score could not reach
    its own top band -- HIGH was unreachable, n = 0.

    The target is SURPRISE, the loss minus the entropy of the model's own
    price: zero when the model is calibrated at whatever confidence it
    chose, positive when it was more confident than it deserved.  Raw log
    loss cannot be the target (rule 16: a coin flip scores badly for
    everyone) and the market deficit cannot be, because it is a difference
    between two models and the band describes one of them.  The deficit is
    kept as the out-of-sample CHECK instead, and the band below sorts it.

    What survived, measured on the test half and not the half it was fitted
    on:

      comeback   +0.0053 / +0.0185 / +0.0304 for none / one / both.  The
                 heaviest term, as it always was.
      cold       +0.0007 / +0.0053 / +0.0102.  Weak, monotone, kept.
      thin       DROPPED.  Above the harness's 1,500-point floor it does
                 not sort: +0.0120 (best measured), -0.0016, +0.0134.  The
                 old thresholds -- 6,000 / 3,000 / 1,000 -- were set against
                 a service-point scale this model no longer has; the
                 THINNER of two players now runs 1,501 to 6,978 with a 99th
                 percentile of 5,934, so "well measured" almost never fired.
                 What remains below is not a fitted claim but a floor: under
                 1,500 points the harness never scores a match, so there is
                 no measurement, and a live price there gets the benefit of
                 the doubt in the only safe direction.
      best_of    DROPPED, and it is the interesting one.  Five-setters
                 carry -0.0212 surprise against +0.0112 for three -- the
                 model is systematically UNDER-confident over five sets,
                 which survives conditioning on how well measured the
                 players are.  That is a calibration error to fix in the
                 model, not a trust level to report in a band.
      form_sd    DROPPED.  Its sign is backwards (steady players carry MORE
                 surprise), which is the model's own volatility term already
                 doing its job inside the price rather than a signal about
                 it.
    """
    return {
        # not fitted: below the harness's floor there is no measurement
        "unmeasured": 1 if min_pts < 1500 else 0,
        "cold": 0 if matches_28d_min >= 4 else 1 if matches_28d_min >= 2 else 2,
        # the count, not a flag: both players returning is worse than one
        "comeback": min(int(comeback or 0), 2),
    }


# Deliberately NOT part of the band.  A coin-flip match has high log loss
# because it is genuinely uncertain, not because the model is untrustworthy,
# and including it made the bands separate beautifully while measuring the
# wrong thing.  It is reported beside the band instead.
def tightness(p):
    return ("coin-flip" if abs(p - 0.5) <= 0.10 else
            "close" if abs(p - 0.5) <= 0.20 else "clear")


def score(f):
    """Raw penalty; higher means expect a bigger error."""
    return f["cold"] + 2 * f["comeback"] + 2 * f["unmeasured"]


# THREE levels, not four.  The fourth claimed a resolution the data does not
# support: on the test half the old top two bands sat within 0.004 nats of
# each other and in the wrong order.  These three are monotone on BOTH
# halves of the residual cache and, independently, on the closing line.
BANDS = [(0, 0, "GOOD"), (1, 2, "FAIR"), (3, 99, "LOW")]

# The model's log-loss deficit against Pinnacle closing, by band, measured
# out of sample on odds-joined matches (tools/odds/disagree.py build, then
# `bands`; 4,966 matches, 2024-2026, re-measured 2026-09-16 with the band
# below).  This is the CHECK on the band, not its target, and it sorts:
# +0.0132 / +0.0201 / +0.0314.  The band it replaced did not -- its best
# level carried +0.0232, worse than its middle two -- because the
# best-measured matches are also the ones the market prices hardest, so a
# deficit cannot separate "the model is bad here" from "the market is
# unusually good here".  The chain re-measures these now.
MEASURED_DEFICIT = {"GOOD": 0.0132, "FAIR": 0.0201, "LOW": 0.0314}


def band(f):
    s = score(f)
    for lo, hi, name in BANDS:
        if lo <= s <= hi:
            return name
    return "LOW"


def _H(p):
    p = min(max(p, 1e-12), 1 - 1e-12)
    return -(p * math.log(p) + (1 - p) * math.log(1 - p))


def fit(cache=None):
    """Measure the band on the residual cache, out of sample.

    Uses exactly the inputs a live price feeds `features` -- the service
    points behind the thinner rating AS OF THAT MATCH, the thinner side's
    matches in 28 days, and how many players are back from a layoff -- so
    the band measured here is the band that ships (rule 19).
    """
    path = cache or os.path.join(HERE, "tools", "residuals.json")
    if not os.path.exists(path):
        sys.exit("need tools/residuals.json -- run: python3 tools/curves.py build")
    rows = json.load(open(path))
    if "den" not in rows[0]:
        sys.exit("the cache predates the band inputs -- rebuild it: "
                 "python3 tools/curves.py build")
    rows.sort(key=lambda r: r["day"])

    # rows come winner-then-loser; a band must describe the MATCH
    pairs = [(rows[i], rows[i + 1]) for i in range(0, len(rows) - 1, 2)
             if rows[i]["y"] == 1 and rows[i + 1]["y"] == 0]
    half = len(pairs) // 2
    out = {nm: {"n": 0, "ll": 0.0, "surprise": 0.0, "acc": 0}
           for _lo, _hi, nm in BANDS}
    for a, b in pairs[half:]:
        m28 = [x for x in (a["f"].get("matches_28d"), b["f"].get("matches_28d"))
               if x is not None]
        f = features(min(a.get("den", 0.0), b.get("den", 0.0)),
                     min(m28) if m28 else 0,
                     (a["f"].get("comeback") or 0) + (b["f"].get("comeback") or 0))
        nm = band(f)
        p = max(min(a["p"], 1 - 1e-12), 1e-12)
        out[nm]["n"] += 1
        out[nm]["ll"] -= math.log(p)
        out[nm]["surprise"] += -math.log(p) - _H(p)
        out[nm]["acc"] += 1 if a["p"] > 0.5 else 0
    print(f"\n  out of sample on {len(pairs) - half:,} matches "
          f"(the later half of {len(pairs):,})")
    print(f"  {'band':>6} {'n':>7} {'log loss':>9} {'surprise':>10} "
          f"{'accuracy':>9} {'vs closing':>11}")
    for _lo, _hi, nm in BANDS:
        v = out[nm]
        if not v["n"]:
            print(f"  {nm:>6} {0:>7}")
            continue
        print(f"  {nm:>6} {v['n']:>7,} {v['ll']/v['n']:>9.5f} "
              f"{v['surprise']/v['n']:>+10.4f} {v['acc']/v['n']:>9.4f} "
              f"{MEASURED_DEFICIT.get(nm, float('nan')):>+11.4f}")
    print("\n  surprise is the loss minus the entropy of the model's own price:")
    print("  positive means it was more confident than it turned out to deserve.")
    json.dump({"bands": [list(b) for b in BANDS],
               "measured": {k: {"n": v["n"],
                                "log_loss": (v["ll"] / v["n"]) if v["n"] else None,
                                "surprise": (v["surprise"] / v["n"]) if v["n"] else None,
                                "accuracy": (v["acc"] / v["n"]) if v["n"] else None}
                            for k, v in out.items()},
               "deficit_vs_closing": MEASURED_DEFICIT},
              open(MODEL, "w"), indent=2)
    print(f"\n  wrote {MODEL}")
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fit":
        fit()
        raise SystemExit(0)
    if os.path.exists(MODEL):
        m = json.load(open(MODEL))
        print("measured reliability per confidence band (out of sample):")
        for nm, v in m["measured"].items():
            if v["n"]:
                print(f"  {nm:>6} n={v['n']:>7,}  log loss {v['log_loss']:.5f}"
                      f"  surprise {v.get('surprise', float('nan')):+.4f}"
                      f"  accuracy {v['accuracy']:.4f}")
    else:
        print("not fitted yet -- run: python3 confidence.py fit")
