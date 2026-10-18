"""Write the reconstructed gap matches as a Sackmann-schema CSV.

Three tiers of row, and the counts are reported separately because they are
not the same thing:

  full     both players' rates recovered into exact counts -- these are what
           the ratings actually train on
  result   a genuine result with no serve stats (the source has not published
           them, or only one player's page was reachable).  load.py accepts
           these and excludes them from ratings by design.

Validation that does not depend on the fields used to reconstruct: Tennis
Abstract also publishes DR (dominance ratio), a function of BOTH players'
totals that was never fed to the solver.  If the reconstructed counts
reproduce the published DR, the two independently-solved sides agree.
"""
import csv, hashlib, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import COLUMNS, CUT, level_of, main, minutes_of
from recon import solve, best, games

S = os.path.dirname(os.path.abspath(__file__))
OUT = "data/manual_matches.csv"


def bp(s):
    m = re.match(r"^(\d+)\s*/\s*(\d+)$", (s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else ("", "")


def counts(row):
    if not (row["ace_pct"] or "").strip():
        return None
    return best(solve(row["ace_pct"], row["df_pct"], row["first_in"],
                      row["first_pct"], row["second_pct"]), row["score"])


def dr_check(w, l, published):
    """Does the reconstruction reproduce TA's published dominance ratio?"""
    try:
        pub = float(published)
    except (TypeError, ValueError):
        return None
    w_sv, l_sv = w[0], l[0]
    w_won, l_won = w[4] + w[5], l[4] + l[5]
    if not (w_sv and l_sv):
        return None
    spl = (w_sv - w_won) / w_sv
    if spl == 0:
        return None
    return abs(round(((l_sv - l_won) / l_sv) / spl, 2) - pub) <= 0.02


BLANK = {c: "" for c in COLUMNS}


def row_for(date, tname, rnd, wname, lname, wrow, lrow, ids, wc, lc):
    lev, bo = level_of(tname)
    g = games(wrow["score"]) or 0
    wg, lg = ((g + 1) // 2, g // 2) if g else ("", "")
    r = dict(BLANK)
    r.update({
        # md5, not hash(): Python randomises string hashing per process, so
        # hash() gave the same event a different id on every re-emit -- and
        # features.py keys workload on tourney_id.
        "tourney_id": f"{date[:4]}-TA{int(hashlib.md5(tname.encode()).hexdigest()[:6], 16) % 9000 + 1000}",
        "tourney_name": tname,
        "surface": wrow["surface"] or "Unknown",
        "tourney_level": lev, "tourney_date": date,
        "winner_id": ids.get(wname, ""), "winner_name": wname,
        "loser_id": ids.get(lname, ""), "loser_name": lname,
        "score": wrow["score"], "best_of": bo, "round": rnd,
        "minutes": minutes_of(wrow["time"]),
        "winner_rank": wrow["rk"], "loser_rank": wrow["vrk"],
    })
    if wc and lc:
        wbs, wbf = bp(wrow["bpsvd"])
        lbs, lbf = bp(lrow["bpsvd"])
        r.update({
            "w_ace": wc[1], "w_df": wc[2], "w_svpt": wc[0], "w_1stIn": wc[3],
            "w_1stWon": wc[4], "w_2ndWon": wc[5], "w_SvGms": wg,
            "w_bpSaved": wbs, "w_bpFaced": wbf,
            "l_ace": lc[1], "l_df": lc[2], "l_svpt": lc[0], "l_1stIn": lc[3],
            "l_1stWon": lc[4], "l_2ndWon": lc[5], "l_SvGms": lg,
            "l_bpSaved": lbs, "l_bpFaced": lbf})
    return r


def main_emit():
    sides, ids, _stats = main()
    rows = []
    full = result_only = dr_bad = no_id = 0

    for (date, tname, rnd, _pair), by_player in sorted(sides.items()):
        winners = [n for n, v in by_player.items() if v["won"]]
        if len(by_player) == 2:
            if len(winners) != 1:
                continue
            wname = winners[0]
            lname = [n for n in by_player if n != wname][0]
            wrow, lrow = by_player[wname]["row"], by_player[lname]["row"]
        else:
            # only one page reachable: still a real result, just no stats
            (only, v), = by_player.items()
            wname, lname = (only, v["opp"]) if v["won"] else (v["opp"], only)
            wrow = lrow = v["row"]

        wc = lc = None
        if len(by_player) == 2:
            wc, lc = counts(wrow), counts(lrow)
            if wc and lc and dr_check(wc, lc, wrow["dr"]) is False:
                dr_bad += 1
                wc = lc = None          # sides disagree; keep the result only

        if wc and lc:
            full += 1
        else:
            result_only += 1
        if not ids.get(wname) or not ids.get(lname):
            no_id += 1
        r = row_for(date, tname, rnd, wname, lname, wrow, lrow, ids, wc, lc)
        # how each player got into the draw: their own page's prefix first,
        # else what the other side's page printed about them
        for who, name in (("winner", wname), ("loser", lname)):
            for k in ("seed", "entry"):
                own = by_player.get(name, {}).get(k, "")
                seen = next((v.get("opp_" + k, "") for n, v in by_player.items()
                             if n != name and v.get("opp") == name), "")
                r[f"{who}_{k}"] = own or seen
        rows.append(r)

    rows.sort(key=lambda r: (r["tourney_date"], r["tourney_name"], r["round"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"\nwrote {len(rows)} matches to {OUT}")
    print(f"  with full serve stats (train the ratings) : {full}")
    print(f"  result only (source has no stats yet)     : {result_only}")
    print(f"  dropped stats on DR disagreement          : {dr_bad}")
    print(f"  rows with an unmapped player id           : {no_id}")
    ev = {}
    for r in rows:
        k = (r["tourney_date"], r["tourney_name"])
        ev.setdefault(k, [0, 0])
        ev[k][0] += 1
        ev[k][1] += 1 if r["w_svpt"] != "" else 0
    print(f"\n  {'event':<38} {'matches':>8} {'with stats':>11}")
    for k in sorted(ev):
        n, s = ev[k]
        print(f"    {k[0]}  {k[1]:<26} {n:5} {s:10}")
    return rows


if __name__ == "__main__":
    main_emit()
