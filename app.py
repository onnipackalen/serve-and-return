#!/usr/bin/env python3
"""
The tool with a face on it.   python3 tennis.py app

Everything here already existed at the command line.  What did not exist was
a way to *look around*: to see who the model rates highly before deciding
whose price to ask for, to check that a name resolved to the player you
meant, or to compare a player's clay rating with their hard-court rating
without running three commands and holding the numbers in your head.

    python3 app.py                  serve on 127.0.0.1:8765 and open a browser
    python3 app.py --port 9000      somewhere else
    python3 app.py --no-open        just serve

Design rules, all of them consequences of what this project has already
learned:

  * **It computes nothing of its own.**  Every number on the page comes from
    price.py, weights.py, features.py, confidence.py or fastgames.py.  A
    second implementation of the pricing arithmetic is a second thing that
    can be wrong, and the two would drift silently -- which is exactly how
    the calibration writeback bug survived two sessions.
  * **The canonical CLI text ships with every answer.**  Each price and each
    simulation carries the *actual* output of `price.report` / `simulate.report`
    in a panel you can open.  If the pretty layout ever disagrees with the
    tool, you can see it disagree.
  * **Standard library only.**  The project depends on numpy and pandas
    because the model needs them.  A web framework would be a dependency the
    model does not need, for a viewer that runs on one machine.
  * **Localhost only.**  The data is CC BY-NC-SA 4.0: personal, non-commercial.
    Binding to 0.0.0.0 would be republishing it.

The state is loaded once into the process, so every request after the first
is instant.  The one slow derivation -- features.build, nine seconds over
64,000 player-match rows -- runs in a background thread, and the endpoints
that need it say "not ready yet" rather than blocking the page.
"""

import argparse
import collections
import datetime as dt
import io
import json
import os
import sys
import threading
import traceback
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__)) or "."
WEB = os.path.join(HERE, "web")
sys.path.insert(0, HERE)

import price as P                                              # noqa: E402
import players as PL                                           # noqa: E402
import features as F                                           # noqa: E402
import venues as V                                             # noqa: E402
from fastmatch import win_prob                                 # noqa: E402


# --------------------------------------------------------------- the state

class State:
    """Everything the pages read, loaded once.

    Threading matters here.  The handler is threaded so a slow simulation
    cannot block someone else's page load, and the model modules cache into
    module globals on first use (fastmatch's grid, fastgames' table,
    features' match log).  Those caches are warmed here, on one thread,
    before the server accepts anything -- lazily racing two threads into
    `_load()` is the kind of bug that shows up once a month and never
    reproduces.
    """

    def __init__(self, verbose=True):
        say = (lambda s: print(s, file=sys.stderr)) if verbose else (lambda s: None)
        from load import require_data
        require_data("the app")
        say("loading weights ...")
        self.book = P.Book()
        if not self.book.names:
            raise SystemExit(
                "the model rates zero players, so the app would serve an empty\n"
                "page that looks like a working one. Run `python3 tennis.py fit`\n"
                "first; if that also fails, the match archive is missing (NOTICE).")
        say(f"  {len(self.book.names):,} players, as of {P.asof_date(self.book)}")
        say("loading match log ...")
        self.matches = F.match_log()
        say(f"  {len(self.matches):,} matches")

        # warm the lazily-built caches on this thread
        win_prob(0.65, 0.65, 3)
        try:
            import fastgames as FG
            FG.distribution(0.65, 0.65, 3)
        except Exception:                                      # noqa: BLE001
            pass

        self.staleness = P.staleness(self.book)
        self.roster = self._roster()
        say(f"  {len(self.roster):,} players with a rating")
        self.venue_hints = self._venue_hints()

        # 9s over 64k rows, and only the player page needs it
        self.feats = None
        self.feats_error = None
        threading.Thread(target=self._build_feats, daemon=True).start()

    def _build_feats(self):
        try:
            self.feats = F.build(self.matches)
        except Exception as e:                                 # noqa: BLE001
            self.feats_error = str(e)
            traceback.print_exc()

    def _venue_hints(self):
        """Surface and format each venue was last played on, from the archive.

        Naming a tournament should set the two controls people forget.  The
        venue table knows where a tournament is, not what it is played on;
        the match log does, so the most recent edition's most common
        (surface, best_of) is offered, keyed the way the page's venue list
        is spelled.
        """
        by_key = {}
        for m in self.matches:
            k = V.lookup_key(m.tname) if m.tname else None
            if not k:
                continue
            by_key.setdefault(k, {}).setdefault(
                m.tourney_date, collections.Counter())[(m.surface, m.best_of)] += 1
        out = {}
        for k, editions in by_key.items():
            last = max(editions)
            (surface, bo), _n = editions[last].most_common(1)[0]
            out[k.title()] = {"surface": (surface or "").lower(),
                              "best_of": bo, "last": last}
        return out

    def _roster(self):
        """Every player with any rating, with one comparable summary number.

        Ranking players needs a scalar, and this model does not have one --
        it has a serve rating and a return rating, which trade off.  The
        honest scalar is the model's own answer to "what would this player do
        against a tour-average opponent": run the same win_prob the pricing
        path runs, with a synthetic opponent sitting exactly at tour average
        on both sides.  It is not a new quantity, it is the model evaluated
        at a fixed reference.
        """
        b = self.book
        ta = P.TOUR_AVG
        out = []
        for pid, name in b.names.items():
            sv, rt, n, _w, _ns = b.rating(pid, None)
            if not n:
                continue
            fm = b.form.get(pid, {})
            # opponent at tour average: their serve is ta, and their return
            # is average, so it takes nothing off this player's serve
            p_vs_avg = win_prob(sv, ta - (rt - (1 - ta)), 3,
                                form_sd=b.form_sd(pid),
                                form_sd_b=b.tour_form_sd)
            surf = b.surface.get(pid, {})
            out.append({
                "id": pid, "name": name,
                "serve": sv, "ret": rt, "pts": n,
                "edge": (sv - ta) + (rt - (1 - ta)),
                "p_vs_avg": p_vs_avg,
                "form_sd": b.form_sd(pid),
                "raw_sd": fm.get("raw_sd"),
                "matches": fm.get("matches", 0),
                "surfaces": sorted(surf, key=lambda s: -surf[s]["n"]),
            })
        out.sort(key=lambda r: -r["p_vs_avg"])
        for i, r in enumerate(out, 1):
            r["rank"] = i
        return out


STATE = None            # set by main(); one process, one model


# ------------------------------------------------------------------ the API

def _cand(pid):
    """The candidate dict price.report expects, built from an id.

    The CLI reaches these through a typed name; the app already knows which
    player was clicked, so there is nothing to resolve and nothing ambiguous
    to warn about.
    """
    return {"id": pid, "name": STATE.book.names.get(pid, pid),
            "typed": STATE.book.names.get(pid, pid), "alts": [], "why": "picked"}


def _surface(q):
    """The surface key the model actually stores.

    weights.json keys surfaces as "Hard"/"Clay"; the CLI maps a typed "hard"
    through price.SURFACES before it ever reaches Book.rating.  Passing the
    lowercase string straight through does not raise -- it silently finds no
    surface split and prices the match on the overall rating, which is a
    wrong number with no error attached.  Every surface entering this module
    goes through here.
    """
    v = (q.get("surface", [""])[0] or "").strip().lower()
    return P.SURFACES.get(v)


def api_meta(_q):
    b = STATE.book
    end, gap = STATE.staleness or (P.data_asof(), 0)
    return {
        "asof": str(P.asof_date(b)),
        "players": len(b.names),
        "rated": len(STATE.roster),
        "matches": len(STATE.matches),
        "tour_avg": P.TOUR_AVG,
        "tour_form_sd": b.tour_form_sd,
        "data_end": end, "stale_days": gap,
        "surfaces": sorted(P.SURFACES),
        "venues": sorted({k.title() for k in V.VENUES}),
        "calibration": (None if P._FP.get("calibration_b") is None else
                        P._FP.get("calibration_b")),
        "calibration_measured": P._FP.get("calibration_b_measured"),
        "form_scale": P._FP.get("form_scale"),
        "dens_w": P._FP.get("dens_w"),
        "curves": sorted(P._FC.get("curves", {})),
        "feats_ready": STATE.feats is not None,
        "venue_hints": STATE.venue_hints,
        "headline": _headline(),
    }


def _headline():
    """The measured numbers the 'the model' tab shows -- read from the files
    the refit writes, never typed into the page (they went stale within a
    day when they were)."""
    fp = P._FP
    h = {k: fp.get(k) for k in ("test_log_loss", "elo_log_loss", "test_matches",
                                "scorable_matches", "refit_days", "carry_cap",
                                "fitted_on")}
    try:
        with open(os.path.join(HERE, "data", "market_check.json")) as fh:
            h["market"] = json.load(fh)
    except (OSError, ValueError):
        h["market"] = None
    return h


def api_players(q):
    """The roster, filtered and sorted.  All of it is already in memory."""
    query = (q.get("q", [""])[0] or "").strip()
    surface = _surface(q)
    min_pts = float(q.get("min_pts", ["0"])[0] or 0)
    sort = q.get("sort", ["p_vs_avg"])[0]
    limit = int(q.get("limit", ["300"])[0])

    if query:
        # a typed name searches EVERYONE: a filter that hides the player you
        # asked for by name is a bug, not a feature.  Players under the data
        # threshold are marked thin instead of dropped.  The same resolver
        # the CLI uses, so a typo finds the same player.
        hits = PL.search(STATE.book.names, query, STATE.book.prominence,
                         limit=limit)
        order = {h["id"]: i for i, h in enumerate(hits)}
        why = {h["id"]: h["why"] for h in hits}
        rows = [dict(r, why=why.get(r["id"]), thin=r["pts"] < min_pts)
                for r in STATE.roster if r["id"] in order]
        rows.sort(key=lambda r: order[r["id"]])
        return {"n": len(rows), "rows": rows[:limit]}

    rows = [r for r in STATE.roster if r["pts"] >= min_pts]
    if surface:
        rows = [r for r in rows if surface in r["surfaces"]]
    key = {"name": lambda r: r["name"],
           "serve": lambda r: -r["serve"],
           "ret": lambda r: -r["ret"],
           "pts": lambda r: -r["pts"],
           "matches": lambda r: -r["matches"],
           "form_sd": lambda r: -r["form_sd"],
           "p_vs_avg": lambda r: -r["p_vs_avg"]}.get(sort)
    if key:
        rows = sorted(rows, key=key)
    return {"n": len(rows), "rows": rows[:limit]}


def api_player(q):
    """One player in full: ratings, surface splits, current run, last matches."""
    pid = q.get("id", [""])[0]
    if pid not in STATE.book.names:
        return {"error": f"unknown player id {pid!r}"}
    b = STATE.book
    base = next((r for r in STATE.roster if r["id"] == pid), None)
    tournament = (q.get("at", [""])[0] or "").strip() or None

    surfaces = []
    for surf, e in sorted(b.surface.get(pid, {}).items(),
                          key=lambda kv: -kv[1]["n"]):
        sv, rt, _n, w, ns = b.rating(pid, surf)
        surfaces.append({
            "surface": surf, "n": e["n"], "serve": sv, "ret": rt,
            "d_serve": e["d_serve"], "d_ret": e["d_ret"],
            "w_serve": e["w_serve"], "w_ret": e["w_ret"],
            # the same reference number the roster ranks on, on this surface
            "p_vs_avg": win_prob(sv, P.tour_avg(surf) - (rt - (1 - P.tour_avg(surf))),
                                 3, form_sd=b.form_sd(pid),
                                 form_sd_b=b.tour_form_sd),
            "tour_avg": P.tour_avg(surf),
        })

    work = F.live_workload(pid, b.asof, tournament)
    work["curve_adj"] = P.player_curve_adj(work)

    out = dict(base or {}, surface_splits=surfaces, workload=work,
               tournament=tournament, recent=None,
               recent_ready=STATE.feats is not None)
    if STATE.feats is not None:
        out["recent"] = _recent(pid, int(q.get("recent", ["12"])[0]))
    return out


def _recent(pid, limit=12):
    """Last matches with the workload each was played under.

    features.recent() rebuilds the whole 64k-row feature table on every
    call, which is nine seconds -- fine once in a script, not fine per
    request.  This reads the table the background thread already built.
    """
    feats = STATE.feats
    seq = sorted((m for m in STATE.matches if pid in (m.w_id, m.l_id)),
                 key=lambda m: (m.tourney_date, F.ROUND_ORDER.get(m.rnd, 9)))
    rows = []
    for m in seq[-limit:][::-1]:
        f = feats.get((m.tid, m.rnd, pid), {})
        won = m.w_id == pid
        opp = m.l_id if won else m.w_id
        ret, wo = F.injury_marks(m, pid)
        svpt, swon = ((m.w_svpt, m.w_won) if won else (m.l_svpt, m.l_won))
        rows.append({
            "date": m.tourney_date, "event": m.tname, "round": m.rnd,
            "surface": m.surface, "best_of": m.best_of, "score": m.score,
            "won": won, "opponent": STATE.book.names.get(opp, opp),
            "minutes": m.minutes, "has_stats": m.has_stats,
            "serve_pct": (swon / svpt) if (m.has_stats and svpt) else None,
            "days_rest": f.get("days_rest"), "matches_28d": f.get("matches_28d"),
            "retired": ret, "walkover": wo,
        })
    return rows


def _conditions(q, day):
    """Air density for this request, from a tournament or from raw numbers."""
    tournament = (q.get("at", [""])[0] or "").strip() or None
    def num(k):
        v = (q.get(k, [""])[0] or "").strip()
        return float(v) if v else None
    return tournament, P.resolve_conditions(
        tournament, day, temp_c=num("temp_c"), elevation_m=num("elevation_m"),
        humidity=num("humidity"), indoor=P._truthy(q.get("indoor", [None])[0]))


def _pair(q):
    a, b = q.get("a", [""])[0], q.get("b", [""])[0]
    if a not in STATE.book.names or b not in STATE.book.names:
        raise ValueError("pick two players")
    if a == b:
        raise ValueError("a player cannot play themselves")
    return a, b


def api_price(q):
    a_id, b_id = _pair(q)
    surface = _surface(q)
    best_of = int(q.get("best_of", ["3"])[0])
    curves = q.get("curves", ["1"])[0] != "0"
    book = STATE.book
    tournament, (dens, dens_why) = _conditions(q, book.asof)

    a, b = _cand(a_id), _cand(b_id)
    # how each player got into the draw -- the results feed cannot say, so
    # the page asks; "" means unknown, never "main draw"
    entry = tuple((q.get(k, [""])[0].strip() or None)
                  for k in ("entry_a", "entry_b"))
    cadj, detail = (P.curve_adjustment(a_id, b_id, book.asof, tournament,
                                       entry=entry, surface=surface)
                    if curves else (0.0, None))
    ev = P.event_update(book, a_id, b_id, book.asof, tournament)
    try:
        nws, ndet = P.news_adjust(book, a_id, b_id, book.asof)
    except P.Unavailable as e:
        raise ValueError(f"the news on file says {e} is not playing. "
                         f"Clear it on the Player tab if that is stale.")
    r = P.price(book, a_id, b_id, surface, best_of, dens=dens, curve_adj=cadj,
                ev=ev, nws=nws)

    # the canonical rendering, produced by the same function the CLI calls --
    # if the panels above it ever drift, this is where you see it
    buf = io.StringIO()
    P.report(book, a, b, surface, best_of, out=buf, dens=dens,
             dens_why=dens_why, tournament=tournament, use_curves=curves,
             entry=entry)

    def side(cand, tup, form):
        sv, rt, n, w, ns = tup
        return {"id": cand["id"], "name": cand["name"], "serve": sv, "ret": rt,
                "pts": n, "surf_w": w, "surf_n": ns, "form_sd": form}

    out = {
        "a": side(a, r["a"], r["form"][0]),
        "b": side(b, r["b"], r["form"][1]),
        "p_a": r["p_a"], "p_b": 1 - r["p_a"], "p_raw": r["p_raw"],
        "fair_a": 1 / max(r["p_a"], 1e-9), "fair_b": 1 / max(1 - r["p_a"], 1e-9),
        "pa_serve": r["pa_serve"], "pb_serve": r["pb_serve"],
        "tour_avg": r["tour_avg"],
        "dens": r["dens"], "dens_shift": r["dens_shift"], "dens_why": dens_why,
        "curve_adj": r["curve_adj"], "curve_dp": r["curve_dp"],
        "curves_on": curves,
        "surface": surface, "best_of": best_of, "tournament": tournament,
        "asof": str(P.asof_date(book)),
        "calibration": r["cal_b"],
        "calibration_measured": P._FP.get("calibration_b_measured"),
        "text": buf.getvalue(),
    }
    if detail:
        wa, wb, adj_a, adj_b = detail
        out["curve_detail"] = [
            dict(wa, name=a["name"], adj=adj_a),
            dict(wb, name=b["name"], adj=adj_b),
        ]
    if ndet:
        out["news"] = [dict(v, id=k, d_serve=nws[k]["d_serve"],
                            d_ret=nws[k]["d_ret"],
                            var_x=nws[k].get("var_x", 1.0),
                            retire=nws[k].get("retire", 0.0))
                       for k, v in ndet.items()]
    if ev:
        out["event_update"] = [dict(v, id=k, name=book.names.get(k, k))
                               for k, v in ev.items()]
    if r.get("stage_serve") and r["stage_serve"][0] is not None:
        out["stage_serve"] = list(r["stage_serve"])
    out["confidence"] = _confidence(r, detail)
    # a bookmaker's odds, if typed: compared with the call, never used in it
    mk = P.market_view(r["p_a"], q.get("odds_a", [""])[0], q.get("odds_b", [""])[0])
    if mk:
        out["market"] = mk
    st = STATE.staleness
    if st:
        out["stale"] = {"end": st[0], "days": st[1]}
    return out


def _confidence(r, detail):
    """How much to trust this one price -- confidence.py, unchanged."""
    try:
        import confidence as C
    except Exception:                                          # noqa: BLE001
        return None
    min_pts = min(r["a"][2], r["b"][2])
    m28, cb = 99, 0
    if detail:
        wa, wb, _aa, _ab = detail
        m28 = min(wa["matches_28d"], wb["matches_28d"])
        cb = (wa.get("comeback") or 0) + (wb.get("comeback") or 0)
    f = C.features(min_pts, m28, cb)
    bnd = C.band(f)
    # the deficit against the market no longer sorts by band (see
    # confidence.py); the realised log loss does, and confidence.py fit
    # refreshes it on every chain, so the page shows both and says which
    realised = None
    try:
        with open(C.MODEL) as fh:
            realised = json.load(fh).get("measured", {}).get(bnd)
    except (OSError, ValueError):
        pass
    return {"band": bnd, "deficit": C.MEASURED_DEFICIT.get(bnd),
            "realised": realised,
            "tightness": C.tightness(r["p_a"]), "min_pts": min_pts,
            "matches_28d": None if m28 == 99 else m28, "comeback": cb,
            "parts": f}


def api_sim(q):
    """Totals and set scores.  Two views, and they are not the same view.

    The simulator plays the model out point by point; fastgames is the
    tabulated distribution with the fitted bias correction applied.  The
    correction is the validated one (84% of the bias removed out of sample),
    so the corrected mean is the number to read -- but the raw simulation is
    shown beside it because the gap between them IS the correction, and
    hiding it would make a fitted adjustment look like a fact.
    """
    import simulate as S
    import fastgames as FG

    a_id, b_id = _pair(q)
    surface = _surface(q)
    best_of = int(q.get("best_of", ["3"])[0])
    n = max(2000, min(60000, int(q.get("n", ["20000"])[0])))
    book = STATE.book
    _tournament, (dens, dens_why) = _conditions(q, book.asof)

    a, b = _cand(a_id), _cand(b_id)
    r = P.price(book, a_id, b_id, surface, best_of, dens=dens)
    fa, fb = r["form"]
    s = S.simulate(r["pa_serve"], r["pb_serve"], best_of, n, form=(fa, fb))

    buf = io.StringIO()
    S.report(book, a, b, surface, best_of, n=n, dens=dens, dens_why=dens_why,
             out=buf)

    corrected = FG.expected_form(r["pa_serve"], r["pb_serve"], best_of, fa, fb)
    dist = FG.dist_form(r["pa_serve"], r["pb_serve"], best_of, fa, fb)
    lo = max(0, int(corrected) - 6)
    ladder = []
    for line in range(lo, lo + 13):
        half = line + 0.5
        ladder.append({
            "line": half,
            "over": sum(p for g, p in enumerate(dist) if g > half),
            "over_sim": S.over_under(s["games"], half)[0],
        })
    return {
        "a": a["name"], "b": b["name"], "n": n,
        "p_a": s["p_a"], "p_exact": r["p_raw"],
        "pa_serve": r["pa_serve"], "pb_serve": r["pb_serve"],
        "form": [fa, fb], "best_of": best_of, "surface": surface,
        "mean_games": s["mean_games"], "median_games": s["median_games"],
        "corrected_mean": corrected, "bias": FG.BIAS.get(best_of, 0.0),
        "mean_sets": s["mean_sets"], "mean_points": s["mean_points"],
        "dist": [{"games": g, "p": p} for g, p in enumerate(dist)
                 if p > 1e-4],
        "ladder": ladder,
        "scorelines": [{"a": x, "b": y, "p": c / s["n"],
                        "who": a["name"] if x > y else b["name"]}
                       for (x, y), c in s["scorelines"].most_common(8)],
        "curves_note": bool(P._FC.get("curves")),
        "text": buf.getvalue(),
    }


def api_news(q):
    """The prompt to paste into an assistant, plus whatever is on file."""
    import news as N
    pid = q.get("id", [""])[0]
    if pid not in STATE.book.names:
        return {"error": f"unknown player id {pid!r}"}
    name = STATE.book.names[pid]
    rec = N.get(pid)
    detail = None
    if rec:
        ds, dr, det = N.weight(rec, STATE.book.form_sd(pid), STATE.book.asof)
        detail = dict(det or {}, d_serve=ds, d_ret=dr)
    return {"id": pid, "name": name,
            "prompt": N.prompt_for(name, str(P.asof_date(STATE.book))),
            "report": rec, "effect": detail,
            "severity_scale": N.SEVERITY, "sourcing": N.SOURCING}


def post_news(body):
    """Store a report the assistant produced.  Validated before it can move
    a price -- this is the one input not derived from the archive."""
    import news as N
    raw = (body or {}).get("report")
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            raw = raw[raw.find("{"):]
        try:
            raw = json.loads(raw)
        except ValueError as e:
            raise ValueError(f"not valid JSON: {e}")
    pid = (body or {}).get("id")
    if pid not in STATE.book.names:
        raise ValueError("pick a player first")
    if (body or {}).get("clear"):
        N.clear(pid)
        return {"ok": True, "cleared": True}
    try:
        stored = N.add(raw, pid, STATE.book.names[pid])
    except N.Invalid as e:
        raise ValueError(str(e))
    return {"ok": True, "stored": stored}


def api_variables(_q):
    """What the model accepts, and what it actually does with it."""
    return {"rows": [{"name": k, "status": v[0], "note": v[1]}
                     for k, v in P.VARIABLES.items()]}


ROUTES = {
    "/api/meta": api_meta,
    "/api/players": api_players,
    "/api/player": api_player,
    "/api/price": api_price,
    "/api/sim": api_sim,
    "/api/variables": api_variables,
    "/api/news": api_news,
}

POST_ROUTES = {"/api/news": post_news}

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
        ".css": "text/css", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "tennis"

    def log_message(self, fmt, *args):      # one line per request, not three
        if "--verbose" in sys.argv:
            sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # a local viewer that caches its own HTML is a viewer that shows you
        # yesterday's page after you edit it
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        fn = POST_ROUTES.get(unquote(u.path))
        if fn is None:
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, json.dumps(fn(body), default=float))
        except ValueError as e:
            self._send(400, json.dumps({"error": str(e)}))
        except Exception as e:                                 # noqa: BLE001
            traceback.print_exc()
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))

    def do_GET(self):
        u = urlparse(self.path)
        path = unquote(u.path)
        if path in ROUTES:
            try:
                body = json.dumps(ROUTES[path](parse_qs(u.query)),
                                  default=float)
                self._send(200, body)
            except ValueError as e:
                self._send(400, json.dumps({"error": str(e)}))
            except Exception as e:                             # noqa: BLE001
                traceback.print_exc()
                self._send(500, json.dumps(
                    {"error": f"{type(e).__name__}: {e}",
                     "trace": traceback.format_exc()}))
            return

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.abspath(WEB)) or not os.path.isfile(full):
            self._send(404, "not found", "text/plain")
            return
        with open(full, "rb") as fh:
            self._send(200, fh.read(),
                       MIME.get(os.path.splitext(full)[1], "text/plain"))


def main():
    global STATE
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true",
                    help="do not launch a browser")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    STATE = State()
    url = f"http://127.0.0.1:{args.port}/"
    # 127.0.0.1, never 0.0.0.0 -- the data licence is non-commercial personal
    # use, and serving it on the LAN is redistribution
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\n  tennis  ->  {url}\n  ctrl-c to stop\n", file=sys.stderr)
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
