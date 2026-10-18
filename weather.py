"""
Tier 1 -- historical weather from Open-Meteo (free, no key, ERA5 reanalysis).

    python3 weather.py fetch          pull and cache every venue in the table
    python3 weather.py Madrid 2024    show a venue-year

One request per venue covering the whole date range, cached to
weather_cache.json.

FULLY RESUMABLE.  Re-running skips venues that already hold data, and empty
entries count as unfetched (Open-Meteo returns rate-limit errors as valid
JSON with HTTP 200, which silently cached 92 blank venues once).  Open-Meteo
caps requests hourly; on hitting it this waits 10 minutes and retries rather
than burning its retry budget, so a full run can take a couple of hours of
wall clock.  Killing it loses nothing -- just run it again.

What comes back is temperature, humidity and wind.  Temperature and humidity
are NOT used as separate features -- they combine with venue elevation into
a single air-density index (venues.density_index).  Wind is separate, since
it acts through a different mechanism: it disrupts ball toss and precision
rather than changing drag, so it raises double faults and lowers first-serve
percentage instead of speeding the ball up.

Indoor venues are fetched but must be IGNORED at model time: a closed roof
means no weather effect at all, and feeding outdoor weather to an indoor
match is pure noise injection.
"""

import datetime as dt
import json
import os
import sys
import time
import subprocess
import urllib.parse

from venues import VENUES, lookup, norm, density_index

CACHE = os.path.join(os.path.dirname(__file__) or ".", "weather_cache.json")
API = "https://archive-api.open-meteo.com/v1/archive"
# Open-Meteo weights a request by days x variables, so asking for less is
# the difference between finishing and hitting the hourly cap.  temp_max
# was dropped: the density index uses the mean.
DAILY = "temperature_2m_mean,relative_humidity_2m_mean,wind_speed_10m_max"


def _load():
    if os.path.exists(CACHE):
        with open(CACHE) as fh:
            return json.load(fh)
    return {}


def _save(d):
    """Write atomically.

    The cache is ~18 MB and fetch_all saves after every venue, so a plain
    write leaves a many-second window in which the file on disk is truncated
    JSON.  Anything reading it in that window -- pricing, a backtest --
    crashes.  Write to a temp file and rename, which is atomic on POSIX, so
    a reader sees either the old cache or the new one and never a half of
    either.
    """
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh)
    os.replace(tmp, CACHE)


def _get(url, timeout=90):
    """Fetch via curl.

    Python's urllib has no CA bundle in this environment and fails SSL
    verification; curl carries the system trust store and works.  Shelling
    out is the pragmatic fix and keeps the dependency list empty.
    """
    r = subprocess.run(["curl", "-sS", "--max-time", str(timeout), url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or f"curl exit {r.returncode}")
    return json.loads(r.stdout)


START = "2010-01-01"


def default_end():
    """Open-Meteo's archive runs to today, so ask for everything up to it."""
    return dt.date.today().isoformat()


def gap(cached, end):
    """(start, end) still missing for a venue, or None if it is current.

    A venue already holding history only needs the tail.  Re-requesting the
    whole range would work but costs ~6,000 days against an hourly quota that
    a refresh has no reason to spend.
    """
    if not cached:
        return START, end
    newest = max(cached)
    nxt = (dt.date(int(newest[:4]), int(newest[4:6]), int(newest[6:]))
           + dt.timedelta(days=1))
    return (nxt.isoformat(), end) if nxt.isoformat() <= end else None


def fetch_venue(lat, lon, start=START, end=None, timeout=90):
    end = end or default_end()
    q = urllib.parse.urlencode({
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "start_date": start, "end_date": end,
        "daily": DAILY, "timezone": "auto"})
    d = _get(f"{API}?{q}", timeout)
    # Open-Meteo signals rate limits as valid JSON with HTTP 200, so a
    # silent d.get("daily", {}) stores an EMPTY venue and the log still
    # prints a success line.  92 of 110 venues were blank before this check.
    if d.get("error"):
        raise RuntimeError(str(d.get("reason"))[:160])
    day = d.get("daily", {})
    if not day.get("time"):
        raise RuntimeError("no daily data returned")
    out = {}
    for i, date in enumerate(day.get("time", [])):
        def g(k):
            v = day.get(k, [])
            return v[i] if i < len(v) and v[i] is not None else None
        out[date.replace("-", "")] = [
            g("temperature_2m_mean"), None,
            g("relative_humidity_2m_mean"), g("wind_speed_10m_max")]
    return out


def fetch_all(limit=None, pause=2.0, verbose=True, retries=12, end=None):
    """Bring every venue up to `end` (default today).

    Does double duty: a venue with no history gets the full range, a venue
    that already has history gets only the days since its newest one.  That
    is what makes this runnable after every tournament rather than once.
    """
    end = end or default_end()
    cache = _load()
    # empty entries count as not fetched -- see the rate-limit note above
    cache = {k: v for k, v in cache.items() if v}
    todo = []
    for k, v in VENUES.items():
        g = gap(cache.get(k), end)
        if g:
            todo.append((k, v, g))
    if limit:
        todo = todo[:limit]
    if verbose:
        fresh = sum(1 for k in VENUES if k in cache)
        print(f"{fresh}/{len(VENUES)} venues cached, {len(todo)} need data "
              f"up to {end}")
    for i, (name, (lat, lon, el, ind), (g0, g1)) in enumerate(todo, 1):
        for attempt in range(retries):
            try:
                got = fetch_venue(lat, lon, start=g0, end=g1)
                # merge, never replace -- an extend must not drop the history
                cache.setdefault(name, {}).update(got)
                if verbose:
                    print(f"  [{i}/{len(todo)}] {name:<24} +{len(got):,} days "
                          f"({g0}..{g1}) -> {len(cache[name]):,} total")
                break
            except Exception as e:
                # The hourly cap is a wall-clock problem, not a transient
                # one -- retrying fast just burns the retry budget.  Wait
                # for the window to roll over instead.
                if "limit" in str(e).lower():
                    if verbose:
                        print(f"  [{i}/{len(todo)}] {name:<24} rate limited, "
                              f"waiting 10 min (attempt {attempt+1}/{retries})",
                              flush=True)
                    _save(cache)
                    time.sleep(600)
                    continue
                if attempt == retries - 1:
                    if verbose:
                        print(f"  [{i}/{len(todo)}] {name:<24} FAILED: {e}")
                else:
                    time.sleep(pause * (2 ** attempt))
        # Save after EVERY venue.  The file is ~16 MB and the write is
        # negligible next to a 2s pause, but a batched save loses up to nine
        # venues of work if the process is killed -- and this run gets
        # interrupted routinely, by rate limits and by session end.
        _save(cache)
        time.sleep(pause)
    _save(cache)
    return cache


_C = None


def conditions(tourney_name, yyyymmdd):
    """(temp_c, humidity, wind_kph, elevation_m, indoor, density_index).

    Returns None if the venue or the date is unknown.  density_index is the
    single feature the model should use; temp and elevation are reported
    separately for inspection only.
    """
    global _C
    if _C is None:
        _C = _load()
    v = lookup(tourney_name)
    if not v:
        return None
    lat, lon, el, indoor = v
    rows = _C.get(norm(tourney_name))
    if rows is None:
        for k in VENUES:
            if VENUES[k] == v and k in _C:
                rows = _C[k]
                break
    if not rows:
        return None
    r = rows.get(str(yyyymmdd))
    if not r or r[0] is None:
        return None
    temp, tmax, rh, wind = r
    rh = (rh / 100.0) if rh is not None else 0.5
    return {"temp_c": temp, "temp_max": tmax, "humidity": rh,
            "wind_kph": wind, "elevation_m": el, "indoor": indoor,
            "density_index": density_index(temp, el, rh)}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else None
        fetch_all(limit=n)
        raise SystemExit(0)
    if len(sys.argv) > 2:
        name, year = sys.argv[1], sys.argv[2]
        c = _load().get(norm(name))
        if not c:
            sys.exit(f"{name!r} not cached -- run: python3 weather.py fetch")
        v = lookup(name)
        days = sorted(d for d in c if d.startswith(year))
        print(f"{name}  ({v[2]} m, {'indoor' if v[3] else 'outdoor'})  {year}")
        print(f"  {len(days)} days cached")
        for d in days[::60]:
            t, tx, rh, w = c[d]
            if t is None: continue
            print(f"  {d}   {t:5.1f}C  max {tx:5.1f}  rh {rh:3.0f}%  "
                  f"wind {w:4.1f} km/h   density {density_index(t, v[2], rh/100):+.4f}")
        raise SystemExit(0)
    c = _load()
    print(f"{len(c)} venues cached in weather_cache.json")
    print("run: python3 weather.py fetch")
