"""Injury and player news as a priced input.   python3 tennis.py news

The measured gap to the market is ORDERING, and it is concentrated in
confident disagreement. Every proxy derivable from the match log has been
tried and every one measured to zero -- retirements, walkovers, layoff
length, comebacks -- despite comeback matches carrying double the market's
deficit. The handoff's conclusion was blunt: *the model is simply wrong
about who is better, and the market knows something the log does not*.

This is the channel for that something. An assistant with a browser reads
what is publicly reported about a player's competitive readiness, returns
strict JSON, and this file turns it into a rating adjustment in the same
units as everything else.

    python3 tennis.py news --prompt "Carlos Alcaraz"    # the prompt to paste
    python3 tennis.py news --add report.json            # or: ... --add -
    python3 tennis.py news                              # what is on file
    python3 tennis.py news --clear "Carlos Alcaraz"

## The honest status of these numbers

**They are a prior, not a fit.** Every other weight in this project was
measured on walk-forward residuals; this one cannot be, because there is no
archive of what the news said on the morning of each historical match.

**How a report moves a price (since 2026-09-11): three levers, each in the
unit that thing has.**

    level        points of serve-points-won and return-points-won the
                 problem costs in the next match -- a shoulder costs serve,
                 an ankle costs court coverage.  Enters where the ratings
                 do, so the best-of, the surface and the opponent still
                 shape the result.  1 point of rate = ~4.4 points of win
                 probability at a coin-flip best-of-3, ~5.2 at best-of-5.
    uncertainty  a multiplier on the player's match-day volatility, because
                 "in doubt" is a wider range of outcomes, not only a lower
                 mean.  Small, but honest.
    retirement   the probability they start and do not finish, folded in
                 last.  A retirement is a loss.

The prompt hands the assistant those sensitivities and asks for the three
directly (`impact`).  A report without an `impact` block falls back to the
severity anchors, solved against a stated reference -- an even best-of-3,
the cost split evenly between serve and return -- so that severity 1, 2 and
3 move the price by 2.0, 6.0 and 13.0 points of win probability.

Sourcing scales everything (confirmed 1.0, reported 0.65, speculative 0.30),
a report decays with a 21-day half-life, and it is halved again once the
player has completed two matches since it was filed.

**Every application is logged** to data/news_applied.jsonl with the price
before and after. That is what makes this fittable later: once a few hundred
matches have been priced with news attached, the log plus results is a
dataset and `news_w` becomes a measured parameter instead of a chosen one.
Until then, treat it as an opinion the model is willing to hold, not a
finding.
"""

import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__)) or "."
STORE = os.path.join(HERE, "data", "news.json")
APPLIED = os.path.join(HERE, "data", "news_applied.jsonl")

# THE MECHANISM, in three levers, each in the unit that thing actually has.
#
#   level       points of serve-points-won and return-points-won the
#               problem costs in the next match.  This is what an injury
#               physically does -- a shoulder takes pace off the serve, an
#               ankle takes steps off the court coverage -- and it enters
#               the model exactly where the ratings do (price.serve_probs),
#               so the recursion turns it into a match probability with the
#               best-of, the surface and the opponent all still in play.
#               The model's own sensitivity: 1.0 point of serve rate off one
#               player moves a coin-flip best-of-three by 4.4 points of win
#               probability and a best-of-five by 5.2; a point of return is
#               worth the same.
#   uncertainty a multiplier on the player's match-day volatility (form_sd),
#               because "fitness genuinely in doubt" is a wider range of
#               outcomes, not only a lower mean.  Worth little on its own
#               (x1.5 on a 57/43 favourite is half a point) but it is the
#               honest representation and it is separate from the level.
#   retirement  the probability the player starts but does not finish,
#               folded in last: P(A) = (1-rA)(1-rB) p + (1-rA) rB + rA rB / 2.
#
# Until 2026-09-11 the level was expressed as multiples of the player's own
# form_sd, so the same report moved a volatile player further than a steady
# one.  That mixed the epistemic lever into the physical one; they are now
# separate, and the physical one is absolute.
#
# A report that carries an `impact` block (the prompt below asks for one)
# supplies all three directly.  A report without one -- the original schema
# -- falls back to the severity anchors here, SOLVED against the stated
# reference (an even best-of-three, the cost split evenly between serve and
# return) so that severity 1, 2 and 3 move the price by 2.0, 6.0 and 13.0
# points of win probability, as they always did.
SEVERITY_PTS = {0: 0.0, 1: 0.501, 2: 1.573, 3: 3.634}    # total, serve + return; SOLVED
SEVERITY_VAR = {0: 1.0, 1: 1.10, 2: 1.30, 3: 1.50}     # form_sd multiplier
SEVERITY = {0: 0.0, 1: 0.101, 2: 0.305, 3: 0.673}      # legacy, kept for validate
IMPACT_CAPS = {"serve_pts": 8.0, "return_pts": 8.0, "retire_risk": 0.25,
               "variance_x": 2.0}

# how much of a report to believe
SOURCING = {"confirmed": 1.0, "reported": 0.65, "speculative": 0.30}

# where the problem is decides what it costs.  A shoulder wrecks a serve; an
# ankle wrecks court coverage, which shows up in return points.
AREA = {
    "serving_arm": (0.80, 0.20),
    "lower_body":  (0.35, 0.65),
    "back_core":   (0.60, 0.40),
    "illness":     (0.40, 0.60),
    "other":       (0.50, 0.50),
}

HALF_LIFE = 21.0          # a fitness report goes stale fast
PLAYED_SINCE_DISCOUNT = 0.5   # completed matches since are evidence against

PROMPT = """You are gathering PUBLICLY REPORTED information about one tennis
player's competitive readiness, for a match-pricing model, and turning it
into an estimate the model can use directly.

PLAYER: {player}
AS OF DATE: {date}

Search recent, credible tennis coverage (ATP Tour, Tennis Channel, major
newspapers, established tennis journalists, official player or tournament
statements). Then return ONE JSON object and nothing else -- no preamble, no
explanation, no markdown fence.

SCOPE. Only facts bearing on whether this player can compete at their normal
level: fitness, injury, illness, withdrawals, schedule, and professional
circumstances that are openly reported (a coaching split, an equipment
change). Do NOT include private-life speculation, medical detail beyond what
has been publicly stated, or anything sourced only to anonymous social media.
If you cannot source something to a named outlet or an official statement,
either omit it or mark it "speculative".

Return this shape exactly:

{{
  "player": "{player}",
  "as_of": "{date}",
  "available": true,
  "fitness": {{
    "severity": 0,
    "area": "other",
    "sourcing": "confirmed",
    "issue": "",
    "since": null
  }},
  "impact": {{
    "serve_pts": 0.0,
    "return_pts": 0.0,
    "retire_risk": 0.0,
    "variance_x": 1.0,
    "reasoning": ""
  }},
  "context": {{
    "direction": 0,
    "note": ""
  }},
  "sources": [
    {{"outlet": "", "date": "", "url": "", "says": ""}}
  ]
}}

HOW THE MODEL USES THIS. The model prices a match from two numbers: the
share of points each player wins on their own serve. Your job is to say how
much this report should move those numbers for the player's NEXT match. The
scale, from the model itself:

  * 1.0 point of serve-points-won taken off one player (say 64% -> 63%)
    moves a coin-flip best-of-three by about 4.4 points of win probability,
    and a best-of-five by about 5.2.  A point of RETURN-points-won is worth
    the same.
  * The gap between a top-10 server and a top-100 server is about 5 points.
  * So a niggle is a fraction of a point; a genuine doubt is 1 to 2 points
    in total; a player just back from months out, or playing visibly
    hampered, is 3 points or more.

FIELD RULES.

available      false ONLY if they have withdrawn, retired from the event, or
               are confirmed not playing. false means do not price them.

severity       0  no fitness issue reported
               1  carrying a niggle, strapping, managing something, but
                  playing and expected to play
               2  fitness genuinely in doubt -- a late fitness test, a
                  retirement or mid-match treatment in the last two weeks,
                  a reported problem with no clear resolution
               3  serious -- a long layoff just ended, surgery within the
                  season, or reporting that clearly describes a player well
                  below normal capacity
               Use 0 when nothing is reported. An absence of news is news.

area           serving_arm | lower_body | back_core | illness | other
               shoulder, elbow, wrist, hand -> serving_arm
               hip, thigh, knee, ankle, foot, calf -> lower_body
               back, abdomen, oblique, ribs -> back_core
               virus, stomach, heat, fatigue -> illness

sourcing       confirmed   official statement, player/team quote, visible
                           and widely reported on court
               reported    a named credible journalist or outlet, no
                           official confirmation
               speculative rumour, unconfirmed, or a single weak source

since          ISO date the issue was first reported, or null.

impact.serve_pts    expected cost to the player's serve-points-won, in
               percentage points, 0.0 to 8.0, for the next match, if they
               play.  Where the problem is decides the split: a shoulder,
               elbow or wrist costs mostly serve; a hip, knee, ankle or
               foot costs mostly return (court coverage) and a little
               serve; back and core cost both; illness costs both evenly.
               Typical: severity 1 -> 0.2 to 0.6 total across serve and
               return; severity 2 -> 1.0 to 2.0 total; severity 3 -> 3.0
               or more.  0.0 when severity is 0.

impact.return_pts   the same, for return-points-won, 0.0 to 8.0.

impact.retire_risk  probability, 0.0 to 0.25, that the player starts the
               match but does not finish it.  Use it ONLY when the
               reporting explicitly describes a late fitness test, a
               retirement or medical timeout in the last two weeks, or a
               player saying they will "see how it feels".  0.0 otherwise.
               A retirement counts as a loss.

impact.variance_x   how much wider than usual the player's range of
               outcomes is, 1.0 (normal) to 2.0 (could play fine or could be
               at half capacity).  1.0 when severity is 0; a firm, stable
               problem (a known strapped knee they have played on for a
               month) stays near 1.0; an unresolved one is 1.3 to 1.6.

impact.reasoning    one or two sentences: which reports drove the numbers
               and why that size.  Keep the numbers consistent with the
               severity and the sources; the model rejects impact above 0
               with no sources.

context.direction  -2 to +2, for NON-fitness circumstances that are openly
               reported and plausibly affect competitiveness: a coaching
               change, a bereavement the player has spoken about publicly,
               a visa or travel disruption, an unusually long celebration
               or media week. 0 if nothing. Use this sparingly; 0 is the
               correct answer almost always.

sources        every claim above must be traceable to one of these. Empty
               list is fine and means "nothing found", which is a real and
               common answer -- return severity 0, impact all zero and
               variance_x 1.0, and say so.

If you find nothing at all, return the object with available true, severity
0, impact zero, direction 0 and an empty sources list. Do not invent.
"""


def prompt_for(player, date=None):
    return PROMPT.format(player=player,
                         date=date or dt.date.today().isoformat())


# ------------------------------------------------------------------ store

def _load():
    if not os.path.exists(STORE):
        return {}
    try:
        with open(STORE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
    os.replace(tmp, STORE)


class Invalid(ValueError):
    pass


def validate(rec):
    """Check a report before it can move a price. Raises Invalid.

    Deliberately strict. This is the one input to the model that is not
    derived from the archive, so it is the one place a typo or a
    hallucinated field could move a number without anything noticing.
    """
    if not isinstance(rec, dict):
        raise Invalid("not a JSON object")
    for k in ("player", "as_of", "fitness"):
        if k not in rec:
            raise Invalid(f"missing {k!r}")
    f = rec["fitness"]
    if not isinstance(f, dict):
        raise Invalid("fitness is not an object")
    sev = f.get("severity")
    if sev not in SEVERITY:
        raise Invalid(f"severity {sev!r} is not one of {sorted(SEVERITY)}")
    if f.get("area", "other") not in AREA:
        raise Invalid(f"area {f.get('area')!r} is not one of {sorted(AREA)}")
    if f.get("sourcing", "reported") not in SOURCING:
        raise Invalid(f"sourcing {f.get('sourcing')!r} is not one of "
                      f"{sorted(SOURCING)}")
    d = rec.get("context", {}).get("direction", 0)
    if not isinstance(d, (int, float)) or not -2 <= d <= 2:
        raise Invalid(f"context.direction {d!r} is outside -2..2")
    try:
        dt.date.fromisoformat(rec["as_of"])
    except (TypeError, ValueError):
        raise Invalid(f"as_of {rec.get('as_of')!r} is not an ISO date")
    if sev and not rec.get("sources"):
        raise Invalid("severity above 0 with no sources -- every claim that "
                      "moves a price has to be traceable")
    imp = rec.get("impact")
    if imp is not None:
        if not isinstance(imp, dict):
            raise Invalid("impact is not an object")
        for k, cap in IMPACT_CAPS.items():
            v = imp.get(k, 1.0 if k == "variance_x" else 0.0)
            lo = 1.0 if k == "variance_x" else 0.0
            if not isinstance(v, (int, float)) or not lo <= v <= cap:
                raise Invalid(f"impact.{k} {v!r} is outside {lo}..{cap}")
        moves = (imp.get("serve_pts", 0) or imp.get("return_pts", 0)
                 or imp.get("retire_risk", 0)
                 or (imp.get("variance_x", 1.0) or 1.0) > 1.0)
        if moves and not rec.get("sources"):
            raise Invalid("impact above zero with no sources")
        if moves and not sev:
            raise Invalid("impact above zero with severity 0 -- say what the "
                          "problem is")
    return True


def add(rec, pid, name):
    validate(rec)
    d = _load()
    d[pid] = dict(rec, player=name, _stored=dt.date.today().isoformat())
    _save(d)
    return d[pid]


def clear(pid):
    d = _load()
    out = d.pop(pid, None)
    _save(d)
    return out


def get(pid):
    return _load().get(pid)


def all_reports():
    return _load()


# ----------------------------------------------------------------- weights

def _day(iso):
    y, m, dd = (int(x) for x in iso.split("-"))
    return (dt.date(y, m, dd) - dt.date(2000, 1, 1)).days


def weight(rec, form_sd, asof_day, played_since=0, scale=1.0):
    """(d_serve, d_ret, detail) -- what this report does to a rating.

    d_serve / d_ret are shifts to the player's serve and return rates, in
    rate units (0.01 = one point); negative for a problem.  detail carries
    the two other levers -- `var_x`, the multiplier on the player's form_sd,
    and `retire`, the probability they do not finish -- which price.price
    applies at the stages where each belongs.

    A report with an `impact` block is used as given: the assistant that
    wrote it was handed the model's own sensitivities and asked for points
    of serve and return.  A report without one falls back to the severity
    anchors (SEVERITY_PTS, SEVERITY_VAR), split by area.  `form_sd` is
    accepted for the caller's sake and no longer scales the level.

    Sourcing scales everything; staleness matters more here than anywhere
    else in the model.  A fitness report has a 21-day half-life, and
    completed matches since it was filed are evidence against it -- a
    player who has since won two matches is not the player the report
    described.
    """
    if rec is None:
        return 0.0, 0.0, None
    fit = rec.get("fitness", {}) or {}
    sev = fit.get("severity", 0) or 0
    direction = rec.get("context", {}).get("direction", 0) or 0
    imp = rec.get("impact") or {}
    has_impact = any(imp.get(k) for k in ("serve_pts", "return_pts",
                                          "retire_risk")) \
        or (imp.get("variance_x") or 1.0) > 1.0
    if not sev and not direction and not has_impact:
        return 0.0, 0.0, None

    src = SOURCING.get(fit.get("sourcing", "reported"), 0.65)
    area = fit.get("area", "other")
    s_share, r_share = AREA.get(area, AREA["other"])

    try:
        age_days = max(0, asof_day - _day(rec["as_of"]))
    except Exception:                                          # noqa: BLE001
        age_days = 0
    decay = 0.5 ** (age_days / HALF_LIFE)
    if played_since >= 2:
        decay *= PLAYED_SINCE_DISCOUNT

    if has_impact:
        s_pts = min(max(float(imp.get("serve_pts", 0.0) or 0.0), 0.0), 8.0)
        r_pts = min(max(float(imp.get("return_pts", 0.0) or 0.0), 0.0), 8.0)
        var_x = min(max(float(imp.get("variance_x", 1.0) or 1.0), 1.0), 2.0)
        retire = min(max(float(imp.get("retire_risk", 0.0) or 0.0), 0.0), .25)
        how = "impact"
    else:
        tot = SEVERITY_PTS.get(sev, 0.0)
        s_pts, r_pts = tot * s_share, tot * r_share
        var_x, retire = SEVERITY_VAR.get(sev, 1.0), 0.0
        how = "severity"
    k = src * decay * scale
    d_s, d_r = -s_pts / 100.0 * k, -r_pts / 100.0 * k
    var_x = 1.0 + (var_x - 1.0) * k
    retire = retire * src * decay

    # non-fitness circumstances move both sides evenly and much less: they
    # are softer evidence about a smaller effect -- a tenth of a point of
    # rate per step of direction
    if direction:
        ctx = 0.001 * direction * k
        d_s += ctx * 0.5
        d_r += ctx * 0.5

    return d_s, d_r, {
        "severity": sev, "area": area, "sourcing": fit.get(
            "sourcing", "reported"), "issue": fit.get("issue", ""),
        "direction": direction, "age_days": age_days, "decay": decay,
        "played_since": played_since,
        "sources": len(rec.get("sources") or []),
        "available": rec.get("available", True),
        "how": how, "serve_pts": s_pts, "return_pts": r_pts,
        "var_x": var_x, "retire": retire,
        "reasoning": imp.get("reasoning", ""),
    }


def log_applied(row):
    """Append what was actually applied, so this can be fitted one day.

    The whole reason these weights are a prior and not a measurement is that
    no archive exists of what the news said on the morning of a match. This
    file is that archive, starting now.
    """
    try:
        os.makedirs(os.path.dirname(APPLIED), exist_ok=True)
        with open(APPLIED, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------- CLI

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    import price as P

    if "--prompt" in argv:
        i = argv.index("--prompt")
        who = " ".join(a for a in argv[i + 1:] if not a.startswith("-"))
        if not who:
            sys.exit("usage: tennis.py news --prompt \"Player Name\"")
        book = P.Book()
        try:
            _pid, name, _alts = book.resolve(who)
        except P.Unknown as e:
            sys.exit(str(e))
        print(prompt_for(name))
        return 0

    if "--add" in argv:
        i = argv.index("--add")
        src = argv[i + 1] if len(argv) > i + 1 else "-"
        raw = sys.stdin.read() if src == "-" else open(src).read()
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            raw = raw[raw.find("{"):]
        try:
            rec = json.loads(raw)
        except ValueError as e:
            sys.exit(f"not valid JSON: {e}")
        book = P.Book()
        try:
            pid, name, _ = book.resolve(rec.get("player", ""))
        except P.Unknown as e:
            sys.exit(str(e))
        try:
            stored = add(rec, pid, name)
        except Invalid as e:
            sys.exit(f"rejected: {e}")
        f = stored["fitness"]
        print(f"stored for {name}  severity {f['severity']} "
              f"({f.get('area', 'other')}, {f.get('sourcing', 'reported')}), "
              f"{len(stored.get('sources') or [])} source(s)")
        if not stored.get("available", True):
            print("  marked UNAVAILABLE -- price.py will refuse to price them")
        return 0

    if "--clear" in argv:
        i = argv.index("--clear")
        who = " ".join(a for a in argv[i + 1:] if not a.startswith("-"))
        book = P.Book()
        pid, name, _ = book.resolve(who)
        print(f"cleared {name}" if clear(pid) else f"nothing on file for {name}")
        return 0

    d = all_reports()
    if not d:
        print("no player news on file.\n"
              "  python3 tennis.py news --prompt \"Carlos Alcaraz\"   "
              "# get the prompt\n"
              "  python3 tennis.py news --add report.json           "
              "# store the answer")
        return 0
    today = (dt.date.today() - dt.date(2000, 1, 1)).days
    print(f"{len(d)} player report(s) on file\n")
    print(f"  {'player':<24} {'sev':>4} {'area':>12} {'sourcing':>12} "
          f"{'age':>5} {'decay':>6}  issue")
    for _pid, r in sorted(d.items(), key=lambda kv: kv[1].get("player", "")):
        f = r.get("fitness", {})
        try:
            age = max(0, today - _day(r["as_of"]))
        except Exception:                                      # noqa: BLE001
            age = 0
        print(f"  {r.get('player', '?')[:24]:<24} {f.get('severity', 0):>4} "
              f"{f.get('area', 'other'):>12} {f.get('sourcing', ''):>12} "
              f"{age:>4}d {0.5 ** (age / HALF_LIFE):>6.2f}  "
              f"{f.get('issue', '')[:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
