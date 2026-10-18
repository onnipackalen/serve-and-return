"""Turn Tennis Abstract fragments into Sackmann-schema rows for the gap.

Only matches after the archive's last tournament date are emitted, because
load.py appends manual_matches.csv without deduplicating.
"""
import csv, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_frag import parse
from recon import solve, best, games

S = os.path.dirname(os.path.abspath(__file__))
FRAGS = os.path.join(S, "frags")
def _archive_cut(root=None):
    """The last tournament date the archive has USABLE STATS for.

    Not the last date it has rows for.  The mirror was snapshotted while
    Roland Garros 2026 was in progress, so the archive holds all 127 of its
    matches as results with every stat column blank -- and a cut based on
    "the last date present" skipped the event on the grounds that the
    archive already had it.  127 matches of a Grand Slam, absent from the
    ratings, because the boundary event is exactly the one a mid-tournament
    freeze breaks.

    Deriving it from the data means the next freeze cannot repeat this.
    """
    import csv as _csv
    import glob as _glob
    root = root or os.path.join(os.path.dirname(os.path.dirname(S)),
                                "data", "sackmann", "atp")
    best_date = "00000000"
    for fn in _glob.glob(os.path.join(root, "atp_matches_2*.csv")):
        try:
            with open(fn, newline="", encoding="utf-8") as fh:
                for r in _csv.DictReader(fh):
                    if (r.get("w_svpt") or "").strip() and \
                            r["tourney_date"] > best_date:
                        best_date = r["tourney_date"]
        except OSError:
            continue
    return best_date if best_date > "00000000" else "20260525"


CUT = os.environ.get("TA_CUT") or _archive_cut()
SACK = "data/sackmann/atp"

COLUMNS = ("tourney_id,tourney_name,surface,draw_size,tourney_level,"
           "tourney_date,match_num,winner_id,winner_seed,winner_entry,"
           "winner_name,winner_hand,winner_ht,winner_ioc,winner_age,loser_id,"
           "loser_seed,loser_entry,loser_name,loser_hand,loser_ht,loser_ioc,"
           "loser_age,score,best_of,round,minutes,w_ace,w_df,w_svpt,w_1stIn,"
           "w_1stWon,w_2ndWon,w_SvGms,w_bpSaved,w_bpFaced,l_ace,l_df,l_svpt,"
           "l_1stIn,l_1stWon,l_2ndWon,l_SvGms,l_bpSaved,l_bpFaced,winner_rank,"
           "winner_rank_points,loser_rank,loser_rank_points").split(",")

MON = {m: f"{i+1:02d}" for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"])}
SLAMS = ("Australian Open", "Roland Garros", "Wimbledon", "US Open")


def ta_date(d):
    dd, mm, yy = d.split("-")
    return f"{yy}{MON[mm]}{int(dd):02d}"


def level_of(t):
    if t in SLAMS:
        return "G", 5
    if "Masters" in t or t in ("Tour Finals", "Masters Cup"):
        return ("F", 3) if "Finals" in t else ("M", 3)
    if "Davis Cup" in t or "Laver" in t or "United Cup" in t:
        return "D", 3
    return "A", 3


MAIN_ROUNDS = {"R128", "R64", "R32", "R16", "QF", "SF", "F", "RR", "BR"}


def is_main_tour(t):
    """Challengers and ITF Futures are outside the model's world.

    Futures are named M15/M25/M15+H; challengers carry a CH suffix.  The
    archive's atp_matches files contain neither, so admitting them here would
    change what the tour average even means.
    """
    if re.match(r"^[MW]\d{2}\b", t.strip()):
        return False
    bad = (" CH", "Challenger", "ITF", "Futures", "Qualifying")
    return not any(b in t for b in bad)


def minutes_of(t):
    m = re.match(r"^(\d+):(\d+)$", (t or "").strip())
    return str(int(m.group(1)) * 60 + int(m.group(2))) if m else ""


PREFIX = re.compile(r"^\((\w{1,4})\)")


def clean(n):
    """Strip seed/entry prefixes and the country suffix from a result name."""
    n = PREFIX.sub("", n.strip())
    n = re.sub(r"\s*\[[A-Z]{3}\]\s*$", "", n).strip()
    return n


def prefix_of(n):
    """(seed, entry) from the '(3)' / '(Q)' prefix of a result name.

    The page prints how each player got into the draw exactly as the archive
    records it -- a seed number, or Q / WC / LL / PR / SE / Alt -- and the
    entry curve (features.ENTRY) reads both columns, so a reconstructed row
    carries them too.  Blanks when there is no prefix: main draw, unseeded.
    """
    m = PREFIX.match(n.strip())
    if not m:
        return "", ""
    tag = m.group(1)
    if tag.isdigit():
        return tag, ""
    return "", ("Alt" if tag.lower() == "alt" else tag.upper())


def split_result(res):
    """(winner_text, loser_text, owner_won) from 'X d. Y'.

    Only the opponent carries a [CTY] tag, which is how the page's own player
    is identified without needing their full name.
    """
    sp = split_result_full(res)
    return sp[:3] if sp else None


def split_result_full(res):
    """split_result plus each side's (seed, entry) prefix."""
    if " d. " not in res:
        return None
    left, right = res.split(" d. ", 1)
    owner_won = "[" not in left
    return clean(left), clean(right), owner_won, prefix_of(left), prefix_of(right)


def load_sackmann():
    """name -> id, plus the full display name for every known player."""
    ids = {}
    for p in sorted(glob.glob(os.path.join(SACK, "atp_matches_[0-9]*.csv"))):
        if int(re.search(r"(\d{4})", os.path.basename(p)).group(1)) < 2015:
            continue
        for r in csv.DictReader(open(p)):
            for who in ("winner", "loser"):
                n = r[f"{who}_name"]
                if n:
                    ids[n] = r[f"{who}_id"]
    return ids


def key_to_name(ids):
    """TA url key -> Sackmann display name, e.g. CarlosAlcaraz -> Carlos Alcaraz."""
    return {re.sub(r"[^A-Za-z0-9]", "", n): n for n in ids}


def observed_names():
    """TA url key -> full display name, learned from opponents' pages.

    A page prints its own player as a bare surname but prints opponents in
    full, so every player's full name is recoverable from somebody else's
    page.  Without this a player missing from the archive appears as both
    "Hewitt" and "Cruz Hewitt" and their matches split into two halves that
    never join.
    """
    seen = {}
    for f in glob.glob(os.path.join(FRAGS, "*.js")):
        for row in parse(f):
            k = row["opp_key"]
            if not k or k in seen:
                continue
            sp = split_result(row["result"])
            if sp:
                seen[k] = sp[1] if sp[2] else sp[0]
    return seen


def mint_ids(names, known):
    """Stable synthetic ids for players the archive has never seen.

    They must be distinct: a blank id would merge every new player into one
    phantom that accumulates all their points.
    """
    new = sorted(n for n in names if n not in known)
    return {n: str(900001 + i) for i, n in enumerate(new)}


def main():
    ids = load_sackmann()
    k2n = key_to_name(ids)                       # archive spelling wins
    for k, n in observed_names().items():        # then what other pages print
        k2n.setdefault(k, n)
    sides, unknown_key, upcoming, prelim, nonmain = {}, set(), 0, 0, 0

    for f in sorted(glob.glob(os.path.join(FRAGS, "*.js"))):
        key = os.path.basename(f)[:-3]
        owner = k2n.get(key)
        if not owner:
            unknown_key.add(key)
        for row in parse(f):
            d = ta_date(row["date"])
            if d <= CUT:
                prelim += 1
                continue
            if not is_main_tour(row["tourney"]) or \
                    row["round"] not in MAIN_ROUNDS:
                nonmain += 1
                continue
            sp = split_result_full(row["result"])
            if not sp or not row["score"].strip():
                upcoming += 1
                continue
            wtxt, ltxt, owner_won, wpre, lpre = sp
            # the url key is exact; the printed name varies between pages
            opp = k2n.get(row["opp_key"]) or clean(ltxt if owner_won else wtxt)
            me = owner or clean(wtxt if owner_won else ltxt)
            mkey = (d, row["tourney"], row["round"], frozenset((me, opp)))
            mine, theirs = (wpre, lpre) if owner_won else (lpre, wpre)
            sides.setdefault(mkey, {})[me] = {
                "row": row, "won": owner_won, "opp": opp,
                "seed": mine[0], "entry": mine[1],
                "opp_seed": theirs[0], "opp_entry": theirs[1]}
    everyone = {n for v in sides.values() for n in v}
    everyone |= {s["opp"] for v in sides.values() for s in v.values()}
    ids.update(mint_ids(everyone, ids))
    return sides, ids, dict(unknown=unknown_key, upcoming=upcoming,
                            prelim=prelim, nonmain=nonmain)


if __name__ == "__main__":
    sides, ids, stats = main()
    both = sum(1 for v in sides.values() if len(v) == 2)
    print(f"post-{CUT} matches seen : {len(sides)}")
    print(f"  both sides present   : {both}")
    print(f"  one side only        : {len(sides)-both}")
    print(f"  skipped (pre-cutoff) : {stats['prelim']}")
    print(f"  skipped (non-main)   : {stats['nonmain']}")
    print(f"  skipped (no score)   : {stats['upcoming']}")
    print(f"  frag keys not in Sackmann: {len(stats['unknown'])}")
    ev = {}
    for (d, t, _r, _p) in sides:
        ev[(d, t)] = ev.get((d, t), 0) + 1
    for k in sorted(ev):
        print(f"    {k[0]}  {k[1]:<28} {ev[k]:4}")
