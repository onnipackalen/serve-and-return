"""Measure one knob of the SHIPPED pricing path, paired, in one walk-forward.

    python3 tools/pathsweep.py event_w 0 0.5 1 2 4     sweep the in-event weight
    python3 tools/pathsweep.py all                     shipped, minus each layer
    python3 tools/pathsweep.py carry                   surface carry-over on/off

Why this exists.  tools/inevent.py, tools/twostage.py and tools/combo.py
each measured a structural change on the SINGLE-NUMBER model -- no surface
split, no per-player form, no other layer -- and inevent/combo banked the
event in file order, which for several seasons of the archive is
alphabetical by round.  A layer worth -0.002 alone can be worth nothing
once the layers it overlaps with are present, and every near-substitute
this project has tested has looked positive alone and cancelled in company.

So: ONE walk-forward, refits shared (that is the slow part), every config
priced through price.serve_probs exactly as the CLI prices, all on
identical matches (rule 1).  form_scale is fitted on the train half per
config; the test half is scored paired against the first config.
"""

import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import backtest as B                                              # noqa: E402

SCALES = (0.3, 0.4, 0.5, 0.6, 0.7, 0.85, 1.0, 1.2)
OUT = os.path.join(HERE, "_pathsweep")


def paired(recs, store, labels):
    """Fit form_scale on train per config, score test, pair against the first."""
    idxs = sorted(store[0])
    span = recs[idxs[-1]][0] - recs[idxs[0]][0]
    cut = recs[idxs[0]][0] + span // 2
    tr = [i for i in idxs if recs[i][0] < cut]
    te = [i for i in idxs if recs[i][0] >= cut]
    dens_w = B._FP.get("dens_w", 0.0)
    print(f"\n  {len(idxs):,} matches, identical across configs   "
          f"train {len(tr):,} / test {len(te):,}\n")

    def scored(preds):
        best, bs = 1e9, None
        for sc in SCALES:
            ll = B.logloss([B.price_player(preds[i], sc, dens_w=dens_w)
                            for i in tr])
            if ll < best:
                best, bs = ll, sc
        return [B.price_player(preds[i], bs, dens_w=dens_w) for i in te], bs

    base_ps, _ = scored(store[0])
    print(f"  {'config':<32} {'scale':>6} {'test ll':>9} "
          f"{'vs first':>9} {'paired t':>9}")
    out = []
    for lbl, preds in zip(labels, store):
        ps, sc = scored(preds)
        mu, t = B.paired_t(base_ps, ps)          # >0: this config is better
        ll = B.logloss(ps)
        tag = "  <- baseline" if preds is store[0] else ""
        print(f"  {lbl:<32} {sc:>6.2f} {ll:>9.5f} {-mu:>+9.5f} {t:>+9.2f}{tag}")
        out.append({"config": lbl, "scale": sc, "test_log_loss": ll,
                    "vs_first": -mu, "paired_t": t, "n_test": len(te)})
    print("\n  vs first: change in log loss against the baseline row; "
          "negative is better, t > 0 means better")
    return out


def run(mode, args):
    c = B.config
    if mode == "event_w":
        ws = sorted(set([0.0] + [float(a) for a in args]))
        labels = [f"in-event w={w:g}" for w in ws]
        configs = [c(event_w=w) for w in ws]
    elif mode == "carry":
        labels = ["surface carry-over OFF", "surface carry-over ON (shipped)"]
        configs = [c(carry=False), c(carry=True)]
    elif mode == "all":
        # each row flips ONE knob away from what ships, whichever way it
        # ships, so the table reads the same whether a layer is on or off
        st, ev = B.STAGES, B.EVENT_W
        labels = ["shipped",
                  f"three-stage serve {'OFF' if st else 'ON'}",
                  f"in-event update {'OFF' if ev else 'ON (w=2)'}",
                  "both of those flipped",
                  f"surface carry-over {'OFF' if B.CARRY else 'ON'}",
                  "no surface split at all"]
        configs = [c(),
                   c(stages=not st),
                   c(event_w=0.0 if ev else 2.0),
                   c(stages=not st, event_w=0.0 if ev else 2.0),
                   c(carry=not B.CARRY),
                   c(surface=False)]
    else:
        sys.exit(__doc__)

    recs = B.records(2005, 2026)
    print(f"  {len(recs):,} rated matches; {len(configs)} configs, one walk",
          flush=True)
    t0 = time.time()
    store = [dict() for _ in configs]
    for idx, tups in B.walk_forward(recs, configs=configs):
        for s, tup in zip(store, tups):
            s[idx] = tup
    print(f"  walk-forward {time.time() - t0:.0f}s", flush=True)
    res = paired(recs, store, labels)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{mode}.json")
    json.dump({"mode": mode, "args": args, "shipped": c(), "results": res},
              open(path, "w"), indent=2)
    print(f"\n  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "all", sys.argv[2:]))
