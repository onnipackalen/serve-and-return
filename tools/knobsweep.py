"""Sweep a constant that was chosen rather than fitted, paired, one walk per value.

    python3 tools/knobsweep.py run surface_hl 730 1095 1460 2190
    python3 tools/knobsweep.py run long_years 8 12 16
    python3 tools/knobsweep.py run carry_cap 0.03 0.05 0.08 0.12
    python3 tools/knobsweep.py run refit_days 45 91 182
    python3 tools/knobsweep.py run age_knots 20,26,32 22,28,34 24,30,36
    python3 tools/knobsweep.py run prior_mode own
    TENNIS_PRIOR_MODE=own python3 tools/knobsweep.py run prior_weight 100 300 600
    TENNIS_PRIOR_MODE=age python3 tools/knobsweep.py run prior_age 1,0 0.5,0 0,0
    python3 tools/knobsweep.py compare surface_hl

Each value is a full walk-forward in its own subprocess (the constants are
module-level, read once at import, so a process per value is the honest
way to vary them), run several at a time, cached as a pickle.  `compare`
scores every cached value on the intersection of what they all price,
fits form_scale on the train half per value, and pairs each against the
shipped value with a per-match t (rule 1).  About ninety seconds a value
at the 91-day cadence, six or seven minutes at the shipped 7.

`compare` reports BOTH halves, always.  A wide sweep read off one half is
a wide sweep of chances to be lucky: prior_age was fourteen values, and
the guard is that a value winning on test also wins on train, in the same
order (rule 32).  A "test only" row is a flag, not a result.
"""

import math
import os
import pickle
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OUT = os.path.join(HERE, "_knobsweep")
SCALES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2)
def _shipped():
    """knob -> (environment variable, the value that SHIPS right now), read
    from the modules so an adopted value is the baseline of the next sweep."""
    import backtest as B
    import ratings as R
    import weights as W
    return {
        "surface_hl": ("TENNIS_SURFACE_HL", f"{W.SURFACE_HALF_LIFE:g}"),
        "long_years": ("TENNIS_LONG_YEARS", str(W.LONG_YEARS)),
        "carry_cap":  ("TENNIS_CARRY_CAP", f"{W.CARRY_CAP:g}"),
        "refit_days": ("TENNIS_REFIT_DAYS", str(B.REFIT_DAYS)),
        "age_knots":  ("TENNIS_AGE_KNOTS", ",".join(f"{k:g}" for k in R.AGE_KNOTS)),
        "prior_mode": ("TENNIS_PRIOR_MODE", W.PRIOR_MODE),
        "prior_weight": ("TENNIS_PRIOR_WEIGHT", f"{W.PRIOR_WEIGHT:g}"),
        "prior_age": ("TENNIS_PRIOR_AGE", ",".join(f"{x:g}" for x in W.PRIOR_AGE)),
    }


KNOBS = _shipped()
POOL = int(os.environ.get("TENNIS_POOL") or 5)


def _one(knob, value):
    """Run in a subprocess with the knob's environment variable set."""
    import backtest as B
    recs = B.records(2005, 2026)
    t0 = time.time()
    preds = dict(B.walk_forward(recs))
    os.makedirs(os.path.join(OUT, knob), exist_ok=True)
    with open(os.path.join(OUT, knob, f"{value}.pkl"), "wb") as fh:
        pickle.dump(preds, fh)
    print(f"  {knob}={value}  {len(preds):,} scorable  "
          f"({time.time() - t0:.0f}s)", flush=True)


def run(knob, values):
    env_name, shipped = KNOBS[knob]
    values = list(dict.fromkeys([shipped] + values))     # shipped first, once
    procs = []
    for v in values:
        env = dict(os.environ, **{env_name: v})
        while len([p for p in procs if p.poll() is None]) >= POOL:
            time.sleep(2)
        print(f"  starting {knob}={v}", flush=True)
        procs.append(subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "_one", knob, v],
            env=env, cwd=ROOT))
    for p in procs:
        p.wait()
    bad = [p.returncode for p in procs if p.returncode]
    print(f"  {len(values)} runs, {len(bad)} failed")
    return 1 if bad else 0


def compare(knob):
    import backtest as B
    env_name, shipped = KNOBS[knob]
    d = os.path.join(OUT, knob)
    store = {}
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".pkl"):
            with open(os.path.join(d, fn), "rb") as fh:
                store[fn[:-4]] = pickle.load(fh)
    if shipped not in store:
        sys.exit(f"shipped value {shipped} not run yet")
    recs = B.records(2005, 2026)
    common = sorted(set.intersection(*(set(v) for v in store.values())))
    span = recs[common[-1]][0] - recs[common[0]][0]
    cut = recs[common[0]][0] + span // 2
    tr = [i for i in common if recs[i][0] < cut]
    te = [i for i in common if recs[i][0] >= cut]
    dens_w = B._FP.get("dens_w", 0.0)
    print(f"\n  {knob}: {len(store)} values, common {len(common):,}   "
          f"train {len(tr):,} / test {len(te):,}\n")

    def priced(preds, idxs, sc):
        return [B.price_player(preds[i], sc, dens_w=dens_w) for i in idxs]

    def scored(preds):
        """form_scale fitted on TRAIN, then both halves priced with it."""
        best, bs = 1e9, None
        for sc in SCALES:
            ll = B.logloss(priced(preds, tr, sc))
            if ll < best:
                best, bs = ll, sc
        return priced(preds, tr, bs), priced(preds, te, bs), bs

    base_tr, base_te, _ = scored(store[shipped])

    def key(v):
        try:
            return float(v.split(",")[0])
        except ValueError:
            return v

    print(f"  {'value':>12} {'scale':>6} {'test ll':>9} {'vs shipped':>11} "
          f"{'paired t':>9} {'on train':>10} {'t':>7} {'alone':>9}")
    for v in sorted(store, key=key):
        ps_tr, ps_te, sc = scored(store[v])
        mu, t = B.paired_t(base_te, ps_te)
        mu_tr, t_tr = B.paired_t(base_tr, ps_tr)
        # a value read off the test half alone is the thing to catch (rule 32)
        tag = ("  <- shipped" if v == shipped else
               "  TEST ONLY -- flag" if (-mu < 0 <= -mu_tr) else "")
        print(f"  {v:>12} {sc:>6.2f} {B.logloss(ps_te):>9.5f} {-mu:>+11.5f} "
              f"{t:>+9.2f} {-mu_tr:>+10.5f} {t_tr:>+7.2f} "
              f"{len(store[v]):>9,}{tag}")
    print("\n  vs shipped: change in log loss; negative is better, t > 0 means better."
          "\n  A value that wins on test must also win on train, or it was read off"
          "\n  the half it is scored on (rule 32).")


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in KNOBS:
        sys.exit(__doc__)
    cmd, knob = sys.argv[1], sys.argv[2]
    if cmd == "_one":
        _one(knob, sys.argv[3])
        return 0
    if cmd == "run":
        return run(knob, sys.argv[3:])
    if cmd == "compare":
        compare(knob)
        return 0
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
