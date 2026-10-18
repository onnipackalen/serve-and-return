"""Test the totals model against a market -- as soon as a market exists.

    python3 tools/odds/totals_market.py data/totals.csv

WHY THIS IS A STUB WITH A REAL TEST INSIDE IT.  Historical totals lines are
not freely available anywhere I could reach:

  tennis-data.co.uk   moneyline only.  Confirmed twice: the sheets carry
                      B365/PS/Max/Avg/BFE for W and L and nothing else, and
                      alldata.php links no other files.
  The Odds API        needs a key; historical odds are a paid add-on.
  Betfair historical  unreachable from here, and needs an account.
  oddsportal          renders odds in JS and its terms forbid scraping.

Every one of those needs an account or a payment, which is the user's call
to make, not mine.  So the join and the scoring are written and tested here
against a plain CSV, and the only missing piece is the file.

EXPECTED CSV COLUMNS (any order, extra columns ignored):

    date        YYYY-MM-DD, the day the match was played
    player_a    either player, any spelling players.py can resolve
    player_b    the other
    line        the total-games line, e.g. 22.5
    over_odds   decimal odds on the over
    under_odds  decimal odds on the under

The model's side comes from fastgames.p_over_form, which integrates the
match-day form draw and applies the fitted bias correction -- the same
numbers `sim` reports, not a separate path.
"""

import csv
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

REQUIRED = ("date", "player_a", "player_b", "line", "over_odds", "under_odds")


def devig(o_over, o_under):
    io, iu = 1.0 / o_over, 1.0 / o_under
    return io / (io + iu)


def logloss(ps):
    return -sum(math.log(max(min(p, 1 - 1e-12), 1e-12)) for p in ps) / len(ps)


def load_lines(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (rd.fieldnames or [])]
        if missing:
            sys.exit(f"{path} is missing columns: {', '.join(missing)}\n"
                     f"needs: {', '.join(REQUIRED)}")
        for r in rd:
            try:
                rows.append({"date": r["date"].strip(),
                             "a": r["player_a"].strip(),
                             "b": r["player_b"].strip(),
                             "line": float(r["line"]),
                             "over": float(r["over_odds"]),
                             "under": float(r["under_odds"])})
            except (TypeError, ValueError):
                continue
    return rows


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nNo totals file supplied.  See the header for the columns "
              "and the sources that would need an account.")
        return 1
    path = sys.argv[1]
    if not os.path.exists(path):
        sys.exit(f"no such file: {path}")

    import datetime as dt
    import fastgames as FG
    import price as P
    from features import score_parts
    from fit import to_day
    from load import load

    lines = load_lines(path)
    print(f"{len(lines):,} totals lines loaded from {path}")

    matches, _ = load(2015, 2026)
    by_pair = {}
    for m in matches:
        if not m.score or any(t in m.score.upper()
                              for t in ("RET", "W/O", "DEF")):
            continue
        _a, _b, gw, gl = score_parts(m.score, True)
        if gw + gl:
            by_pair.setdefault((m.w_id, m.l_id), []).append((m, gw + gl))

    book = P.Book(verbose=False)
    scored, skipped = [], 0
    for r in lines:
        try:
            pa = P.pick(book, r["a"])
            pb = P.pick(book, r["b"])
        except Exception:                                      # noqa: BLE001
            skipped += 1
            continue
        d = dt.date.fromisoformat(r["date"])
        day = (d - dt.date(2000, 1, 1)).days
        cand = (by_pair.get((pa["id"], pb["id"]), [])
                + by_pair.get((pb["id"], pa["id"]), []))
        near = [(m, g) for m, g in cand
                if abs(to_day(m.tourney_date) - day) <= 20]
        if not near:
            skipped += 1
            continue
        m, realised = min(near, key=lambda x:
                          abs(to_day(x[0].tourney_date) - day))
        pr = P.price(book, pa["id"], pb["id"], m.surface, m.best_of or 3)
        fa, fb = pr["form"]
        model_over = FG.p_over_form(pr["pa_serve"], pr["pb_serve"], r["line"],
                                    m.best_of or 3, fa, fb)
        mkt_over = devig(r["over"], r["under"])
        went_over = realised > r["line"]
        scored.append((model_over, mkt_over, went_over))

    if not scored:
        sys.exit(f"nothing scored ({skipped} unmatched) -- check names/dates")
    print(f"  scored {len(scored):,}   unmatched {skipped:,}\n")

    mp = [p if o else 1 - p for p, _b, o in scored]
    bp = [b if o else 1 - b for _p, b, o in scored]
    print(f"  {'':<26} {'log loss':>9} {'brier':>8}")
    for nm, ps in (("model totals", mp), ("market totals (devig)", bp)):
        br = sum((1 - p) ** 2 for p in ps) / len(ps)
        print(f"  {nm:<26} {logloss(ps):>9.5f} {br:>8.5f}")
    gap = logloss(mp) - logloss(bp)
    print(f"\n  gap {gap:+.5f} nats "
          f"({'model WORSE' if gap > 0 else 'model BETTER'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
