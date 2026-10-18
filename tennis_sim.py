"""
Per-player tennis match simulation, logit space.

Both the server AND the returner contribute to each point's probability.
All behavioural coefficients default to 0.0, so an unfitted Player reduces
exactly to the static model. Never ship invented coefficients.

Run:  python3 tennis_sim.py
Gate: python3 check.py     (must pass after any change below)
"""

import math
import random
from dataclasses import dataclass, field

# Fallback only: ATP main tour, all surfaces, 2015-2026, measured in M1.
# Prefer load.tour_avg(surface) -- serve dominance ranges 0.619 (clay) to
# 0.660 (grass) and has drifted up ~0.019 since 2000.
#
# This enters matchup_p as (1 - tour_avg), i.e. a symmetric shift applied to
# BOTH players.  It cancels in a symmetric matchup but not otherwise, and it
# must come from the SAME data slice as serve_won/return_won or every price
# is biased.  The old 0.645 was 0.0078 too high for this dataset.
TOUR_AVG_SERVE = 0.6372


def logit(p): return math.log(p / (1 - p))
def expit(z): return 1 / (1 + math.exp(-z))


# ------------------------------------------------------------- PLAYER

@dataclass
class Player:
    name: str
    serve_won: float            # share of points won on own serve
    return_won: float           # share of points won when returning
    form_sd: float = 0.020      # match-to-match ability spread

    # --- serving, log-odds ---
    fat_lin: float = 0.0
    fat_quad: float = 0.0
    fat_hinge: float = 0.0
    bp_serving: float = 0.0
    gp_serving: float = 0.0

    # --- returning, log-odds ---
    ret_fat_lin: float = 0.0
    ret_fat_quad: float = 0.0
    ret_fat_hinge: float = 0.0
    bp_returning: float = 0.0
    gp_returning: float = 0.0

    momentum: float = 0.0


def matchup_p(server: Player, returner: Player, tour_avg=TOUR_AVG_SERVE):
    """Barnett-Clarke: server's p adjusted for this specific opponent."""
    return tour_avg + (server.serve_won - tour_avg) - (returner.return_won - (1 - tour_avg))


# -------------------------------------------------------------- STATE

@dataclass
class State:
    sets: list = field(default_factory=lambda: [0, 0])
    games: list = field(default_factory=lambda: [0, 0])
    points: list = field(default_factory=lambda: [0, 0])
    server: int = 0
    points_played: int = 0
    in_tiebreak: bool = False
    tb_first: int = 0
    set_scores: list = field(default_factory=list)


@dataclass
class Ctx:
    players: tuple              # (Player A, Player B)
    base_p: tuple               # this match's p after the form draw


# ------------------------------------------------------- p FUNCTIONS

def fatigue_basis(pts):
    x = pts / 250.0
    return x, x * x, max(0.0, x - 0.6)


def static_p(server, st, ctx):
    return ctx.base_p[server]


def dynamic_p(server, st, ctx):
    """P(server wins this point). Both players contribute."""
    r = 1 - server
    srv, ret = ctx.players[server], ctx.players[r]

    z = logit(ctx.base_p[server])
    f1, f2, f3 = fatigue_basis(st.points_played)

    # server tiring hurts him
    z -= srv.fat_lin * f1 + srv.fat_quad * f2 + srv.fat_hinge * f3
    z += srv.momentum * (st.sets[server] - st.sets[r])

    # returner tiring HELPS the server
    z += ret.ret_fat_lin * f1 + ret.ret_fat_quad * f2 + ret.ret_fat_hinge * f3
    z -= ret.momentum * (st.sets[r] - st.sets[server])

    # pressure, both sides
    if not st.in_tiebreak:
        mine, theirs = st.points[server], st.points[r]
        if theirs >= 3 and theirs > mine:          # break point
            z += srv.bp_serving + ret.bp_returning
        elif mine >= 3 and mine > theirs:          # game point for server
            z += srv.gp_serving + ret.gp_returning

    return expit(z)


# ------------------------------------------------------------- ENGINE

def sim_match(ctx, p_fn, best_of=3, rng=None):
    rng = rng or random.Random()
    st, need = State(), best_of // 2 + 1
    while max(st.sets) < need:
        p = p_fn(st.server, st, ctx)
        w = st.server if rng.random() < p else 1 - st.server
        st.points[w] += 1
        st.points_played += 1
        _resolve(st)
    return st


def _resolve(st):
    a, b = st.points
    if st.in_tiebreak:
        if max(a, b) >= 7 and abs(a - b) >= 2:
            st.games[0 if a > b else 1] += 1
            _end_set(st)
        else:
            n = a + b
            st.server = st.tb_first if ((n + 1) // 2) % 2 == 0 else 1 - st.tb_first
        return
    if max(a, b) >= 4 and abs(a - b) >= 2:
        st.games[0 if a > b else 1] += 1
        st.points = [0, 0]
        g0, g1 = st.games
        if max(g0, g1) >= 6 and abs(g0 - g1) >= 2:
            _end_set(st)
        else:
            st.server = 1 - st.server
            if g0 == 6 and g1 == 6:
                st.in_tiebreak = True
                st.tb_first = st.server


def _end_set(st):
    st.sets[0 if st.games[0] > st.games[1] else 1] += 1
    st.set_scores.append(tuple(st.games))
    # ITF: whoever served FIRST in the tiebreak RECEIVES first in the next set.
    # Outside a tiebreak service just alternates across the set boundary.
    # Read in_tiebreak before clearing it.
    st.server = (1 - st.tb_first) if st.in_tiebreak else (1 - st.server)
    st.games, st.points = [0, 0], [0, 0]
    st.in_tiebreak = False


# ------------------------------------------------------------- RUNNER

def run(a: Player, b: Player, p_fn=dynamic_p, n=100_000,
        best_of=3, use_form=True, seed=0):
    """Returns P(a wins), avg points, avg sets."""
    rng = random.Random(seed)
    pa0, pb0 = matchup_p(a, b), matchup_p(b, a)
    wins = pts = sets = 0
    for _ in range(n):
        if use_form:
            pa = pa0 + rng.gauss(0, a.form_sd)
            pb = pb0 + rng.gauss(0, b.form_sd)
        else:
            pa, pb = pa0, pb0
        ctx = Ctx(players=(a, b), base_p=(pa, pb))
        st = sim_match(ctx, p_fn, best_of, rng)
        wins += st.sets[0] > st.sets[1]
        pts += st.points_played
        sets += sum(st.sets)
    return wins / n, pts / n, sets / n


def price(a: Player, b: Player, **kw):
    w, pts, sets = run(a, b, **kw)
    print(f"{a.name} vs {b.name}")
    print(f"  matchup p   {matchup_p(a,b):.4f} / {matchup_p(b,a):.4f}")
    print(f"  P({a.name})  {w:.4f}   fair {1/w:.3f}")
    print(f"  P({b.name})  {1-w:.4f}   fair {1/(1-w):.3f}")
    print(f"  avg {pts:.0f} points, {sets:.2f} sets")
    return w


# --------------------------------------------------------------- MAIN

if __name__ == "__main__":

    # NOTE: every coefficient below is INVENTED for demonstration.
    # Replace with fitted values at M5. Defaults are 0.0 for a reason.

    server_bot = Player(
        "ServeBot", serve_won=0.700, return_won=0.330, form_sd=0.025,
        fat_lin=0.12, fat_quad=0.20, fat_hinge=0.30,     # tires badly
        bp_serving=-0.10,                                 # chokes on BP
        ret_fat_lin=0.10, ret_fat_quad=0.16,              # also tires returning
    )

    grinder = Player(
        "Grinder", serve_won=0.640, return_won=0.410, form_sd=0.015,
        fat_lin=0.02, fat_quad=0.02, fat_hinge=0.03,     # very fit
        bp_serving=-0.02,
        ret_fat_lin=0.02, ret_fat_quad=0.03,
    )

    print("=== unfitted (all coefficients 0) should equal static ===")
    blank_a = Player("A", 0.700, 0.330, form_sd=0.0)
    blank_b = Player("B", 0.640, 0.410, form_sd=0.0)
    w1, _, _ = run(blank_a, blank_b, p_fn=static_p,  best_of=5, use_form=False)
    w2, _, _ = run(blank_a, blank_b, p_fn=dynamic_p, best_of=5, use_form=False)
    print(f"  static {w1:.4f}   dynamic {w2:.4f}   diff {abs(w1-w2):.6f}")

    print("\n=== best of 3 ===")
    price(server_bot, grinder, best_of=3)

    print("\n=== best of 5 ===")
    price(server_bot, grinder, best_of=5)

    print("\n=== effect isolation, best of 5 ===")
    for label, fn, form in [("static, no form ", static_p, False),
                            ("static + form   ", static_p, True),
                            ("dynamic, no form", dynamic_p, False),
                            ("dynamic + form  ", dynamic_p, True)]:
        w, _, _ = run(server_bot, grinder, p_fn=fn, best_of=5, use_form=form)
        print(f"  {label}  P(ServeBot) {w:.4f}   fair {1/w:.3f}")