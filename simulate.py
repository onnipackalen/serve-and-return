"""
Simulate a real matchup point by point.

    python3 tennis.py sim Sinner Alcaraz --surface Clay --best-of 5
    python3 tennis.py sim Zverev Fritz --at Cincinnati -n 50000

tennis_sim.py already had a simulator, but running it directly only ever
played a demo between two invented players.  This wires it to the derived
ratings, so you can simulate a matchup that actually exists.

Why simulate at all when price.py has an exact recursion for the winner?
Because the recursion only returns P(win).  The simulator returns the whole
distribution -- total games, set scores, how often it goes the distance --
and that is what a games-total or set-betting model needs.  The moneyline
is the one number both produce, which makes it a free cross-check: they are
fed identical serve probabilities, so if they disagree by more than
simulation noise, one of them is wrong.
"""

import argparse
import collections
import math
import random
import sys

import price as P
import tennis_sim as TS


def simulate(pa, pb, best_of=3, n=20000, form=(0.0, 0.0), seed=0):
    """Play the match n times from two serve probabilities.

    pa/pb come from price.price(), so every adjustment the pricing path
    makes -- surface, opponent, air density -- is already inside them and
    cannot drift between the two code paths.
    """
    rng = random.Random(seed)
    wins = 0
    games = []
    sets_played = []
    scorelines = collections.Counter()
    total_points = 0

    for _ in range(n):
        # the same match-day ability draw the analytic price integrates over
        qa = min(max(pa + rng.gauss(0, form[0]), 0.01), 0.99)
        qb = min(max(pb + rng.gauss(0, form[1]), 0.01), 0.99)
        ctx = TS.Ctx(players=(None, None), base_p=(qa, qb))
        st = TS.sim_match(ctx, TS.static_p, best_of, rng)
        a_won = st.sets[0] > st.sets[1]
        wins += a_won
        g = sum(x + y for x, y in st.set_scores) if st.set_scores else 0
        games.append(g)
        sets_played.append(sum(st.sets))
        scorelines[(st.sets[0], st.sets[1])] += 1
        total_points += st.points_played

    games.sort()
    return {
        "p_a": wins / n,
        "games": games,
        "mean_games": sum(games) / n,
        "median_games": games[n // 2],
        "mean_sets": sum(sets_played) / n,
        "mean_points": total_points / n,
        "scorelines": scorelines,
        "n": n,
    }


def over_under(games, line):
    """(P(over), P(under), P(exactly the line)) for a total-games line."""
    n = len(games)
    over = sum(1 for g in games if g > line)
    push = sum(1 for g in games if g == line)
    return over / n, (n - over - push) / n, push / n


def report(book, a, b, surface=None, best_of=3, n=20000, dens=0.0,
           dens_why=None, seed=0, out=sys.stdout):
    p_ = lambda s="": print(s, file=out)
    r = P.price(book, a["id"], b["id"], surface, best_of, dens=dens)
    an, bn = a["name"], b["name"]
    fa, fb = r["form"]

    s = simulate(r["pa_serve"], r["pb_serve"], best_of, n, form=(fa, fb),
                 seed=seed)

    p_(f"\n{an}  vs  {bn}")
    p_("-" * 66)
    p_(f"  as of {P.asof_date(book)}   {surface or 'all surfaces'}   "
       f"best of {best_of}   {n:,} simulations")
    if dens_why:
        p_(f"  conditions   {dens_why}")
    p_(f"  serve p      {an}: {r['pa_serve']:.4f}   {bn}: {r['pb_serve']:.4f}")
    p_(f"  form_sd      {fa:.4f} / {fb:.4f}")

    p_(f"\n  WINNER")
    p_(f"    P({an})  {s['p_a']:.4f}   fair {1/max(s['p_a'],1e-9):.3f}")
    p_(f"    P({bn})  {1-s['p_a']:.4f}   fair {1/max(1-s['p_a'],1e-9):.3f}")
    # Compare against the RAW recursion, not the calibrated price: the
    # simulator plays out the model itself and knows nothing about a
    # post-hoc calibration layer.  Comparing to the calibrated number made
    # the two look like they disagreed by 4 SE when both were correct.
    se = math.sqrt(max(s["p_a"] * (1 - s["p_a"]), 1e-9) / s["n"])
    d = s["p_a"] - r["p_raw"]
    flag = "ok" if abs(d) < 3 * se else "DISAGREES -- investigate"
    p_(f"    exact recursion {r['p_raw']:.4f}   diff {d:+.4f}  "
       f"({d/se:+.1f} sim SE, {flag})")
    if getattr(P, "_FC", {}).get("curves"):
        p_("    note: the form/run curves `price` applies are NOT in this "
           "number.")
        p_("          They adjust P(win) directly, and there is no principled "
           "way to")
        p_("          push a match-level shift back into per-point serve "
           "probabilities,")
        p_("          which is all the simulator consumes. Totals below are "
           "pre-curve.")
    if r["cal_b"] and abs(r["p_a"] - r["p_raw"]) > 5e-5:
        p_(f"    calibrated price {r['p_a']:.4f}  (slope {r['cal_b']:.3f}; "
           f"the simulator prices the model before this layer)")

    p_(f"\n  TOTAL GAMES")
    p_(f"    mean {s['mean_games']:.2f}   median {s['median_games']}   "
       f"mean sets {s['mean_sets']:.2f}   mean points {s['mean_points']:.0f}")
    # the raw simulation runs long: independent points finish matches later
    # than real ones do, measured and validated in tools/totals.py
    try:
        import fastgames as FG
        corr = FG.expected_form(r["pa_serve"], r["pb_serve"], best_of,
                                fa, fb)
        p_(f"    bias-corrected mean {corr:.2f}   "
           f"({-FG.BIAS.get(best_of, 0):+.2f} games; real matches end sooner "
           f"than independent points imply)")
    except Exception:                                          # noqa: BLE001
        pass
    lo = int(s["mean_games"]) - 3
    p_(f"    {'line':>6}  {'over':>7} {'under':>7} {'push':>7}")
    for line in range(lo, lo + 7):
        o, u, pu = over_under(s["games"], line + 0.5)
        p_(f"    {line + 0.5:>6}  {o:>7.3f} {u:>7.3f} {pu:>7.3f}")

    p_(f"\n  SET SCORES")
    for (x, y), c in s["scorelines"].most_common(6):
        who = an if x > y else bn
        p_(f"    {x}-{y}  {c / s['n']:>6.1%}   {who}")
    return s


def main():
    ap = argparse.ArgumentParser(
        description="Simulate a matchup point by point and show the "
                    "distribution, not just the winner.")
    ap.add_argument("player_a", nargs="?")
    ap.add_argument("player_b", nargs="?")
    ap.add_argument("extra", nargs="*",
                    help="shorthand: clay/hard/grass/carpet, bo3/bo5, a date")
    ap.add_argument("-n", type=int, default=20000, help="simulations")
    ap.add_argument("--surface", choices=["Hard", "Clay", "Grass", "Carpet"])
    ap.add_argument("--best-of", type=int, default=3, choices=[3, 5])
    ap.add_argument("--date", help="YYYY-MM-DD; uses only earlier matches")
    ap.add_argument("--at", metavar="TOURNAMENT",
                    help="venue + cached weather -> air density")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    surface, best_of, date = a.surface, a.best_of, a.date
    names = []
    for w in [a.player_a, a.player_b] + list(a.extra):
        if not w:
            continue
        lw = w.lower().strip(".,")
        if lw in P.SURFACES:
            surface = P.SURFACES[lw]
        elif lw in ("bo3", "bo5"):
            best_of = int(lw[-1])
        elif P._DATE.match(lw):
            date = lw
        else:
            names.append(w)

    sep = [i for i, w in enumerate(names)
           if w.lower() in ("vs", "vs.", "v", "v.", "versus", "-", "/")]
    if sep:
        i = sep[0]
        qa, qb = " ".join(names[:i]), " ".join(names[i + 1:])
    elif len(names) == 2:
        qa, qb = names
    else:
        ap.error("need two players, e.g. `tennis.py sim Sinner Alcaraz clay bo5`")

    day = P.to_day(date.replace("-", "")) if date else None
    book = P.Book(day, verbose=True)
    try:
        pa, pb = P.pick(book, qa), P.pick(book, qb)
    except P.Unknown as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if pa["id"] == pb["id"]:
        print(f"error: both names resolved to {pa['name']}", file=sys.stderr)
        return 2

    dens, why = P.resolve_conditions(a.at, book.asof)
    report(book, pa, pb, surface, best_of, a.n, dens=dens, dens_why=why,
           seed=a.seed)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
