"""
Player name resolution -- one place, used by pricing and by weights.

The dataset stores names as "First Last" ("Carlos Alcaraz").  People type
surnames, typos, initials, reversed order and accents.  A resolver that only
does substring matching fails on all of those, and the failure mode was a bare
SystemExit with no suggestion -- which is the single biggest reason the tool
was awkward to run.

search() scores every player against the query and returns ranked candidates
with the reason each one matched.  It never raises: an empty list means no
match, and more than one candidate in the top tier means genuinely ambiguous.
The caller decides what to do about it, because a CLI wants to exit with
suggestions and the prompt wants to offer a numbered pick.

Ties inside a tier break on activity (service points, or matches), so a bare
"Zverev" gives Alexander rather than Mischa -- but the runner-up is always
returned too, so the caller can say so out loud.
"""

import difflib
import re
import unicodedata

# score tiers -- higher is a better kind of match, not just a better ratio
EXACT_FULL   = 100
EXACT_LAST   = 90     # surname, or a multi-word surname ("del Potro")
REVERSED     = 85     # "Alcaraz Carlos", "Alcaraz, Carlos"
INITIAL_LAST = 80     # "C Alcaraz", "Alcaraz C"
PREFIX_LAST  = 70     # "Alcar"
SUBSTRING    = 60     # anywhere in the full name
FUZZY_MAX    = 55     # typos; scaled by difflib ratio below this

FUZZY_CUTOFF = 0.72   # against the full name
LAST_CUTOFF  = 0.76   # against the surname alone -- shorter, so stricter


def norm(s):
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def parts(name):
    """(full, first, last) normalised.  'last' keeps particles: 'del potro'."""
    n = norm(name)
    toks = n.split()
    if not toks:
        return "", "", ""
    last = toks[-1]
    # Dutch/Spanish/Portuguese particles belong to the surname
    if len(toks) >= 2 and toks[-2] in (
            "de", "del", "della", "der", "di", "do", "dos", "da", "la", "le",
            "van", "von", "ul", "al", "bin", "st", "mc", "mac"):
        last = " ".join(toks[-2:])
        if len(toks) >= 3 and toks[-3] in ("van", "von", "de", "munoz"):
            last = " ".join(toks[-3:])
    return n, toks[0], last


def _score(query, name):
    """(tier score, why) for one candidate, or None if it does not match."""
    q = norm(query)
    if not q:
        return None
    full, first, last = parts(name)
    toks = full.split()
    q_toks = q.split()

    if q == full:
        return EXACT_FULL, "exact"
    if q == last:
        return EXACT_LAST, "surname"
    # "Alcaraz Carlos" / "Alcaraz, Carlos" -- comma already stripped by norm
    if len(q_toks) >= 2 and q == f"{last} {first}":
        return REVERSED, "surname first"
    if q.replace(" ", "") == full.replace(" ", ""):
        return EXACT_FULL - 1, "exact"
    # "C Alcaraz" / "Alcaraz C" / "c.alcaraz"
    if len(q_toks) == 2 and first:
        a, b = q_toks
        if (a == first[0] and b == last) or (a == last and b == first[0]):
            return INITIAL_LAST, "initial + surname"
    if last.startswith(q) and len(q) >= 3:
        return PREFIX_LAST, "surname prefix"
    if q in full:
        return SUBSTRING, "substring"
    # every query token appears somewhere: "carlos alcaraz" typed as "alcaraz carlos"
    if len(q_toks) > 1 and all(any(t.startswith(qt) for t in toks)
                               for qt in q_toks):
        return SUBSTRING - 1, "all words match"

    # typos -- compare against the full name, the surname, and "last first"
    best, why = 0.0, None
    for cand, cutoff, label in ((full, FUZZY_CUTOFF, "close to full name"),
                                (last, LAST_CUTOFF, "close to surname"),
                                (f"{last} {first}", FUZZY_CUTOFF, "close to name")):
        if not cand:
            continue
        r = difflib.SequenceMatcher(None, q, cand).ratio()
        if r >= cutoff and r > best:
            best, why = r, label
    if why:
        return FUZZY_MAX * best, why
    return None


def search(names, query, weight=None, limit=8):
    """Rank players against `query`.

    names   {pid: "First Last"}
    weight  pid -> activity (service points, matches); breaks ties in a tier
    returns [{"id", "name", "score", "why", "weight"}] best first, possibly []
    """
    weight = weight or (lambda _pid: 0.0)
    out = []
    for pid, name in names.items():
        s = _score(query, name)
        if s:
            out.append({"id": pid, "name": name, "score": s[0], "why": s[1],
                        "weight": float(weight(pid) or 0.0)})
    # round the score so near-identical fuzzy hits still sort by activity
    out.sort(key=lambda c: (-round(c["score"], 3), -c["weight"], c["name"]))
    return out[:limit]


def is_fuzzy(cands):
    """True when the best match is only a typo-distance guess."""
    return bool(cands) and cands[0]["score"] < SUBSTRING


def ambiguous(cands, margin=1e-6):
    """True when two players tie on a *structural* match -- a shared surname.

    Two Zverevs and two Murrays are real, and the caller should say so.  A tie
    between fuzzy guesses is not ambiguity, it is just a weak match, and there
    activity ordering is the answer rather than a question for the user.
    """
    if len(cands) < 2:
        return False
    if cands[0]["score"] >= EXACT_FULL - 1 or cands[0]["score"] < PREFIX_LAST:
        return False
    return cands[1]["score"] >= cands[0]["score"] - margin


def suggest_line(cands, limit=5):
    """One-line 'did you mean' for an error message."""
    if not cands:
        return ""
    return ", ".join(c["name"] for c in cands[:limit])


def nearest(names, query, weight=None, limit=5):
    """Best-effort neighbours when search() found nothing at all.

    Deliberately looser than search(): this only ever feeds a 'did you mean'
    line, so a bad guess costs nothing and a missing one costs the user a
    retry.
    """
    weight = weight or (lambda _pid: 0.0)
    q = norm(query)
    if not q:
        return []
    scored = []
    for pid, name in names.items():
        full, _first, last = parts(name)
        r = max(difflib.SequenceMatcher(None, q, full).ratio(),
                difflib.SequenceMatcher(None, q, last).ratio())
        if r >= 0.45:
            scored.append({"id": pid, "name": name, "score": r, "why": "nearest",
                           "weight": float(weight(pid) or 0.0)})
    scored.sort(key=lambda c: (-round(c["score"], 2), -c["weight"]))
    return scored[:limit]


# ------------------------------------------------------------------- gate

_SYNTHETIC = {
    "1": "Carlos Alcaraz",   "2": "Jannik Sinner",     "3": "Novak Djokovic",
    "4": "Alexander Zverev", "5": "Mischa Zverev",     "6": "Andy Murray",
    "7": "Freddy Murray",    "8": "Juan Martin del Potro",
    "9": "Felix Auger Aliassime", "10": "Luis Carlos Alvarez",
    "11": "Stefanos Tsitsipas",   "12": "Petros Tsitsipas",
}
# more activity == more likely to be the one meant
_ACTIVITY = {"1": 900, "2": 950, "3": 800, "4": 700, "5": 90, "6": 280,
             "7": 0, "8": 170, "9": 600, "10": 5, "11": 550, "12": 0}

# (typed, expected name, must the runner-up be flagged as ambiguous?)
_CASES = [
    ("Alcaraz",           "Carlos Alcaraz",        False),
    ("alcaraz",           "Carlos Alcaraz",        False),
    ("Carlos Alcaraz",    "Carlos Alcaraz",        False),
    ("Alcarez",           "Carlos Alcaraz",        False),   # typo
    ("Alcarazz",          "Carlos Alcaraz",        False),   # typo
    ("alcaras",           "Carlos Alcaraz",        False),   # typo
    ("C Alcaraz",         "Carlos Alcaraz",        False),
    ("C. Alcaraz",        "Carlos Alcaraz",        False),
    ("Alcaraz, Carlos",   "Carlos Alcaraz",        False),
    ("Alcaraz Carlos",    "Carlos Alcaraz",        False),
    ("Djokovis",          "Novak Djokovic",        False),   # typo
    ("Sinnner",           "Jannik Sinner",         False),   # typo
    ("Zverev",            "Alexander Zverev",      True),    # two Zverevs
    ("Mischa Zverev",     "Mischa Zverev",         False),
    ("Murray",            "Andy Murray",           True),    # two Murrays
    ("del potro",         "Juan Martin del Potro", False),
    ("Delpotro",          "Juan Martin del Potro", False),
    ("Auger",             "Felix Auger Aliassime", False),
    ("Tsitsipas",         "Stefanos Tsitsipas",    True),
]


def _gate():
    bad = 0
    for typed, want, want_amb in _CASES:
        c = search(_SYNTHETIC, typed, _ACTIVITY.get)
        got = c[0]["name"] if c else None
        amb = ambiguous(c)
        if got != want:
            print(f"  FAIL  {typed!r:20} -> {got!r}, wanted {want!r}")
            bad += 1
        elif amb != want_amb:
            print(f"  FAIL  {typed!r:20} ambiguous={amb}, wanted {want_amb}")
            bad += 1
    # a name that is not in the table must not resolve to something confident
    for typed in ("Foo Bar", "qqqq", "zzzzzzzz"):
        if search(_SYNTHETIC, typed, _ACTIVITY.get):
            print(f"  FAIL  {typed!r} matched something")
            bad += 1
    print(f"  {len(_CASES) + 3 - bad}/{len(_CASES) + 3} name cases pass")

    # the same cases against the real player table, if it has been derived
    import json
    import os
    path = os.path.join(os.path.dirname(__file__) or ".", "weights.json")
    if not os.path.exists(path):
        print("  (weights.json absent -- real-table check skipped)")
        return bad
    w = json.load(open(path))
    names, form, den = w["names"], w["form"], w["overall"]["den"]
    prom = lambda p: form.get(p, {}).get("matches", 0) * 1000.0 + den.get(p, 0)
    real = 0
    for typed, want, _ in _CASES:
        c = search(names, typed, prom)
        got = c[0]["name"] if c else None
        if got != want:
            print(f"  FAIL  (real) {typed!r:20} -> {got!r}, wanted {want!r}")
            bad += 1
        else:
            real += 1
    print(f"  {real}/{len(_CASES)} name cases pass against "
          f"{len(names):,} real players")
    return bad


def _parse_gate():
    """The prompt's line parser -- the path every price now goes through."""
    from price import parse_line
    cases = [
        ("Sinner vs Alcaraz",        ("Sinner", "Alcaraz", "sep", None, 3)),
        ("Sinner v Alcaraz",         ("Sinner", "Alcaraz", "sep", None, 3)),
        ("Sinner - Alcaraz",         ("Sinner", "Alcaraz", "sep", None, 3)),
        ("Sinner Alcaraz",           ("Sinner", "Alcaraz", "bare", None, 3)),
        ("Sinner vs Alcaraz clay",   ("Sinner", "Alcaraz", "sep", "Clay", 3)),
        ("clay Sinner vs Alcaraz",   ("Sinner", "Alcaraz", "sep", "Clay", 3)),
        ("Sinner vs Alcaraz bo5",    ("Sinner", "Alcaraz", "sep", None, 5)),
        ("Sinner vs Alcaraz clay bo5", ("Sinner", "Alcaraz", "sep", "Clay", 5)),
        ("grass Federer vs Nadal bo5", ("Federer", "Nadal", "sep", "Grass", 5)),
        ("del potro",                ("del", "potro", "bare", None, 3)),
        ("Juan Martin del Potro vs Sinner",
                                     ("Juan Martin del Potro", "Sinner",
                                      "sep", None, 3)),
        ("Sinner",                   ("Sinner", None, "one", None, 3)),
        ("",                         (None, None, "one", None, 3)),
    ]
    bad = 0
    for text, want in cases:
        qa, qb, how, surf, bo, _d = parse_line(text)
        got = (qa, qb, how, surf, bo)
        if got != want:
            print(f"  FAIL  {text!r:32} -> {got}, wanted {want}")
            bad += 1
    # a date anywhere on the line is picked up as the as-of date
    if parse_line("Federer vs Nadal 2008-07-06")[5] != "2008-07-06":
        print("  FAIL  inline date not parsed")
        bad += 1
    print(f"  {len(cases) + 1 - bad}/{len(cases) + 1} line-parse cases pass")
    return bad


if __name__ == "__main__":
    import sys
    print("\nname resolution")
    fails = _gate()
    print("\nline parsing")
    fails += _parse_gate()
    sys.exit(1 if fails else 0)
