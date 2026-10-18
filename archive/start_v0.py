from dataclasses import dataclass, field
import random

@dataclass
class State:
    sets: list = field(default_factory=lambda: [0, 0])
    games: list = field(default_factory=lambda: [0, 0])
    points: list = field(default_factory=lambda: [0, 0])
    server: int = 0            # 0 = A, 1 = B
    points_played: int = 0
    in_tiebreak: bool = False
    tb_first: int = 0
    set_scores: list = field(default_factory=list)

# Simulate a match between two players with given point-winning probabilities.
def sim_match(pa, pb, p_fn, best_of=3, rng=None):
    rng = rng or random.Random()
    st, base, need = State(), (pa, pb), best_of // 2 + 1
    while max(st.sets) < need:
        p = p_fn(st.server, st, base)
        w = st.server if rng.random() < p else 1 - st.server
        st.points[w] += 1
        st.points_played += 1
        _resolve(st)
    return st


# rules for resolving points, games, and sets
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
# rules for resolving points, games, and sets
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
    st.games, st.points = [0, 0], [0, 0]
    st.in_tiebreak = False
    st.server = 1 - st.server
#probabilty functions for simulating matches
def static_p(server, st, base):
    return base[server]

def dynamic_p(server, st, base, fatigue=0.012, momentum=0.006, pressure=-0.015):
    p = base[server]
    p -= fatigue * (st.points_played / 250)              # tires over the match
    p += momentum * (st.sets[server] - st.sets[1 - server])
    if not st.in_tiebreak:                                # facing break point
        mine, theirs = st.points[server], st.points[1 - server]
        if theirs >= 3 and theirs > mine:
            p += pressure
    return min(max(p, 0.01), 0.99)

# Run a simulation of n matches between two players with given point-winning probabilities.
def run(pa, pb, p_fn, n=50_000, best_of=3, form_sd=0.0, seed=0):
    rng, wins, pts = random.Random(seed), 0, 0
    for _ in range(n):
        a = pa + (rng.gauss(0, form_sd) if form_sd else 0)
        b = pb + (rng.gauss(0, form_sd) if form_sd else 0)
        st = sim_match(a, b, p_fn, best_of, rng)
        wins += st.sets[0] > st.sets[1]
        pts += st.points_played
    return wins / n, pts / n