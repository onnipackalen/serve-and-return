"""Fetch Tennis Abstract player fragments, politely and resumably.

The cache has to expire.  A page cached last week still parses fine and
still looks like a success, so a fetcher that skips everything already on
disk will happily report "up to date" while missing an entire tournament.
Pages older than MAX_AGE_H are re-downloaded; everything newer is skipped,
which is what keeps a re-run cheap.
"""
import json
import os
import re
import subprocess
import sys
import time

S = os.path.dirname(os.path.abspath(__file__))
FRAGS = os.path.join(S, "frags")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
DELAY = 0.7
MIN_BYTES = 2000        # smaller than this is a 404 or a challenge page
MAX_AGE_H = 12          # the site regenerates these roughly hourly


def key_of(name):
    return re.sub(r"[^A-Za-z0-9]", "", name)


def is_fresh(path, max_age_h=MAX_AGE_H):
    if not os.path.exists(path) or os.path.getsize(path) < MIN_BYTES:
        return False
    if max_age_h is None:
        return True
    return (time.time() - os.path.getmtime(path)) < max_age_h * 3600


def fetch(key, max_age_h=MAX_AGE_H):
    """True if a usable page is on disk afterwards."""
    path = os.path.join(FRAGS, f"{key}.js")
    if is_fresh(path, max_age_h):
        return True
    os.makedirs(FRAGS, exist_ok=True)
    tmp = path + ".part"
    subprocess.run(
        ["curl", "-sL", "-m", "45", "-A", UA, "-e",
         "https://www.tennisabstract.com/",
         f"https://www.tennisabstract.com/jsfrags/{key}.js", "-o", tmp],
        capture_output=True)
    time.sleep(DELAY)
    # write through a temp file: a half-written page that still exceeds
    # MIN_BYTES would otherwise be indistinguishable from a good one
    if os.path.exists(tmp) and os.path.getsize(tmp) >= MIN_BYTES:
        os.replace(tmp, path)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    return os.path.exists(path) and os.path.getsize(path) >= MIN_BYTES


def ranked(limit):
    txt = open(os.path.join(S, "rank.js"), encoding="utf-8").read()
    m = re.search(r"var currRank = (\{.*?\});", txt, re.S)
    d = json.loads(m.group(1))
    pairs = sorted(((int(v), k) for k, v in d.items() if v.isdigit()))
    return [name for _r, name in pairs[:limit]]


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    names = ranked(limit)
    ok = bad = 0
    for i, name in enumerate(names, 1):
        if fetch(key_of(name)):
            ok += 1
        else:
            bad += 1
        if i % 25 == 0:
            print(f"  {i}/{len(names)}  ok={ok} missing={bad}", flush=True)
    print(f"DONE seeds ok={ok} missing={bad}", flush=True)
