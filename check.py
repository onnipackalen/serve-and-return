"""
Gate for tennis_sim.py.  Run:  python3 check.py     Exit 0 = pass.

Three checks, deliberately of different kinds:

  A. EQUIVALENCE  dynamic_p with all-zero coefficients must be bit-identical
                  to static_p.  Keeps invented coefficients out of a price.
  B. STRUCTURAL   serving order must obey the ITF rules.  Deterministic --
                  no Monte Carlo noise, so it catches small rule bugs that
                  a simulation comparison would bury in sampling error.
  C. NUMERIC      the Monte Carlo must agree with an exact recursion written
                  from scratch below, sharing no code with the simulator.

C is a weak gate by construction (it only sees errors larger than the
sampling error) and B is a strong one.  Do not swap their priority.
"""

import sys
from functools import lru_cache

import tennis_sim as ts

TOL_SE = 4.0          # numeric check: |diff| must be < 4 standard errors


# =================================================== EXACT RECURSION
# Independent re-derivation of Barnett-Clarke.  Nothing below imports
# anything from tennis_sim except the constant.

def p_game(p):
    """P(server wins a game) given P(server wins a point) = p."""
    q = 1.0 - p
    deuce = p * p / (p * p + q * q)              # P(win from deuce)

    @lru_cache(None)
    def rec(a, b):
        if a >= 4 and a - b >= 2: return 1.0     # terminal checks first,
        if b >= 4 and b - a >= 2: return 0.0     # so 4-2 resolves before deuce
        if a >= 3 and b >= 3:                    # collapse the deuce tree
            d = a - b
            if d == 0:  return deuce
            if d == 1:  return p + q * deuce     # advantage server
            return p * deuce                     # advantage returner
        return p * rec(a + 1, b) + q * rec(a, b + 1)

    return rec(0, 0)


def p_tiebreak(pa, pb, first=0, target=7):
    """P(A wins the tiebreak).  `first` = who serves point 1."""
    # From any tied score at >= 6-6 the next two points are always split
    # between the two servers, so the extended phase has a closed form.
    tied = pa * (1 - pb) / (pa * (1 - pb) + pb * (1 - pa))

    @lru_cache(None)
    def rec(a, b):
        if a >= target and a - b >= 2: return 1.0
        if b >= target and b - a >= 2: return 0.0
        if a == b and a >= target - 1: return tied
        n = a + b                                            # points played
        server = first if ((n + 1) // 2) % 2 == 0 else 1 - first
        pA = pa if server == 0 else 1 - pb                   # P(A wins point)
        return pA * rec(a + 1, b) + (1 - pA) * rec(a, b + 1)

    return rec(0, 0)


def set_joint(pa, pb, first):
    """(P(A wins, even games), P(A wins, odd), P(B wins, even), P(B wins, odd)).

    Parity of total games decides who serves first in the NEXT set, because
    service alternates continuously across the set boundary.  A tiebreak
    counts as one game, i.e. 13 total -> odd.
    """
    ga_, gb_ = p_game(pa), p_game(pb)

    @lru_cache(None)
    def rec(ga, gb, server):
        if ga >= 6 and ga - gb >= 2:
            return (1., 0., 0., 0.) if (ga + gb) % 2 == 0 else (0., 1., 0., 0.)
        if gb >= 6 and gb - ga >= 2:
            return (0., 0., 1., 0.) if (ga + gb) % 2 == 0 else (0., 0., 0., 1.)
        if ga == 6 and gb == 6:
            w = p_tiebreak(pa, pb, first=server)             # 13 games -> odd
            return (0., w, 0., 1. - w)
        pA = ga_ if server == 0 else 1 - gb_                 # P(A wins game)
        x = rec(ga + 1, gb, 1 - server)
        y = rec(ga, gb + 1, 1 - server)
        return tuple(pA * x[i] + (1 - pA) * y[i] for i in range(4))

    return rec(0, 0, first)


def p_match(pa, pb, best_of=3):
    """P(A wins the match).  A serves the first game."""
    need = best_of // 2 + 1
    joint = {s: set_joint(pa, pb, s) for s in (0, 1)}

    @lru_cache(None)
    def rec(sa, sb, first):
        if sa == need: return 1.0
        if sb == need: return 0.0
        Ae, Ao, Be, Bo = joint[first]
        return (Ae * rec(sa + 1, sb, first) + Ao * rec(sa + 1, sb, 1 - first) +
                Be * rec(sa, sb + 1, first) + Bo * rec(sa, sb + 1, 1 - first))

    return rec(0, 0, 0)


# ============================================================ CHECK A

def check_equivalence():
    """Unfitted Player must reduce dynamic_p exactly to static_p."""
    a = ts.Player("A", 0.700, 0.330, form_sd=0.0)
    b = ts.Player("B", 0.640, 0.410, form_sd=0.0)
    out = []
    for bo in (3, 5):
        w1, _, _ = ts.run(a, b, p_fn=ts.static_p,  n=20_000, best_of=bo, use_form=False)
        w2, _, _ = ts.run(a, b, p_fn=ts.dynamic_p, n=20_000, best_of=bo, use_form=False)
        out.append((bo, w1, w2, abs(w1 - w2)))
    return out


# ============================================================ CHECK B

def check_serve_order():
    """ITF: whoever serves FIRST in the tiebreak RECEIVES first in the next set.

    Drives tennis_sim._resolve directly at every legal tiebreak-ending score,
    so the result is exact rather than sampled.
    """
    scores = [(7, 0), (7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (8, 6), (9, 7),
              (0, 7), (1, 7), (2, 7), (3, 7), (4, 7), (5, 7), (6, 8), (7, 9)]
    fails = []
    for a, b in scores:
        for tb_first in (0, 1):
            st = ts.State()
            st.games, st.points = [6, 6], [a, b]
            st.in_tiebreak, st.tb_first = True, tb_first
            n = a + b - 1                               # points before the last
            st.server = tb_first if ((n + 1) // 2) % 2 == 0 else 1 - tb_first
            ts._resolve(st)
            if st.server != 1 - tb_first:
                fails.append((f"{a}-{b}", tb_first, st.server, 1 - tb_first))
    return fails


# ============================================================ CHECK C

def check_numeric(n=60_000):
    """Monte Carlo vs exact recursion, reported in standard errors."""
    ret = 1 - ts.TOUR_AVG_SERVE          # makes matchup_p(A,B) == serve_won
    cases = [(0.645, 0.645, 3), (0.700, 0.645, 3), (0.750, 0.750, 3),
             (0.695, 0.615, 5), (0.780, 0.620, 5)]
    rows = []
    for pa, pb, bo in cases:
        A = ts.Player("A", pa, ret, form_sd=0.0)
        B = ts.Player("B", pb, ret, form_sd=0.0)
        sim, _, _ = ts.run(A, B, p_fn=ts.static_p, n=n, best_of=bo, use_form=False)
        exact = p_match(pa, pb, bo)
        se = max((exact * (1 - exact) / n) ** 0.5, 1e-9)
        rows.append((pa, pb, bo, sim, exact, sim - exact, (sim - exact) / se))
    return rows


# =============================================================== MAIN

if __name__ == "__main__":
    ok = True

    print("A. zero-coefficient equivalence  (dynamic_p == static_p)")
    for bo, w1, w2, d in check_equivalence():
        good = d == 0.0                                  # exact, not approximate
        ok &= good
        print(f"   Bo{bo}   static {w1:.5f}   dynamic {w2:.5f}   "
              f"diff {d:.6f}   {'ok' if good else 'FAIL'}")

    print("\nB. serving order after a tiebreak  (ITF rule, exact)")
    fails = check_serve_order()
    ok &= not fails
    if fails:
        print(f"   {len(fails)}/32 cases wrong -- next set served by the wrong player:")
        for score, tbf, got, want in fails:
            print(f"     TB {score:>4}  first served by {tbf}   "
                  f"-> next set server {got}, should be {want}")
    else:
        print("   all 32 tiebreak-ending scores ok")

    print("\nC. simulation vs exact recursion  (60k sims, tol 4 SE)")
    print("     pa      pb   bo       sim     exact       diff      z")
    for pa, pb, bo, sim, exact, diff, z in check_numeric():
        good = abs(z) < TOL_SE
        ok &= good
        print(f"   {pa:.3f}  {pb:.3f}   {bo}   {sim:.5f}   {exact:.5f}   "
              f"{diff:+.5f}  {z:+5.2f}  {'ok' if good else 'FAIL'}")

    print("\n" + ("GATE PASS" if ok else "GATE FAIL"))
    sys.exit(0 if ok else 1)
