"""The Challenger test, run where the Challenger data is supposed to help.

    TENNIS_MIN_PTS=300 python3 tools/qcthin.py run none
    TENNIS_MIN_PTS=300 python3 tools/qcthin.py run 1.0
    TENNIS_MIN_PTS=300 python3 tools/qcthin.py compare

The first version of this comparison found nothing -- and could not have
found anything. Rule 1 scores every config on the INTERSECTION of what each
can price, and the baseline can only price matches where both players clear
MIN_PTS = 1500. Those are the well-measured players, for whom Challenger
data adds least. The 16,138 matches the supplement makes newly scorable are
thin-player matches: exactly the population the whole idea targets, and
exactly the ones the intersection throws away.

Lowering the threshold lets the baseline price them too -- badly, which is
the point -- so both models are scored on the same, much larger set.
"""
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import qcsweep as Q                                               # noqa: E402

Q.OUT = os.path.join(HERE, "_qcsweep_thin")


def main():
    os.makedirs(Q.OUT, exist_ok=True)
    import backtest as B
    print(f"  MIN_PTS = {B.MIN_PTS}", flush=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "compare"
    recs = Q.records(2005, 2026)
    if cmd == "run":
        for a in sys.argv[2:]:
            k = None if a == "none" else float(a)
            preds = Q.run(recs, k)
            with open(os.path.join(Q.OUT, f"{a}.pkl"), "wb") as fh:
                pickle.dump(preds, fh)
        return 0
    store = {}
    for fn in sorted(os.listdir(Q.OUT)):
        if fn.endswith(".pkl"):
            a = fn[:-4]
            with open(os.path.join(Q.OUT, fn), "rb") as fh:
                store[None if a == "none" else float(a)] = pickle.load(fh)
    if None not in store:
        sys.exit("baseline 'none' not scored yet")
    print(f"{len(store)} configs cached")
    Q.paired(recs, store, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
