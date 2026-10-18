"""
Refresh the dataset and re-verify it.   python3 update.py [options]

  --check       verify only, pull nothing
  --no-results  skip the Tennis Abstract results refresh
  --no-weather  skip extending the weather cache

Five jobs, in the order they have to happen:
  1. pull the archive mirror forward (refuses if you have local edits).
     NOTE: the mirror has been dead since 2026-06-25 and Sackmann's own
     repos are deleted, so this step is now expected to be a no-op.  It is
     kept because the day it starts moving again it should be preferred.
  2. refresh results past the mirror's cutoff from tennisabstract.com into
     data/manual_matches.csv (tools/ta/refresh.py; see that file for what
     the reconstruction costs in fidelity and how it is checked)
  3. extend the weather cache to today, so the newly-added tournaments have
     the conditions the density feature needs
  4. RE-VERIFY provenance -- both sources are third party, so the arithmetic
     and sanity checks from M1 run again on every update.  A shift in these
     numbers is a provenance failure, not a rounding difference.
  5. invalidate the ratings cache, which is now stale by construction

After this, re-derive:  python3 tennis.py fit
"""

import glob
import os
import subprocess
import sys
from collections import defaultdict

REPO = "data/sackmann"
CACHE = "cache"


def sh(*args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def verify():
    """Re-run the M1 integrity checks. Returns (ok, summary dict)."""
    from load import load, tour_average, require_data
    require_data("update.py --check")          # the natural "did setup work?"
    matches, bad = load(2000, 2026)
    modern = [m for m in matches if m.tourney_date >= "20000101"]
    if not modern:
        raise SystemExit(
            "the archive is present but holds no matches after 2000 -- "
            "it looks truncated. Re-fetch it; see README.md Setup.")
    avg, pts = tour_average(modern)
    good = sum(1 for m in modern if m.has_stats)

    surf = defaultdict(lambda: [0, 0])
    for m in modern:
        if m.has_stats:
            e = surf[m.surface]
            e[0] += m.w_won + m.l_won
            e[1] += m.w_svpt + m.l_svpt
    sv = {k: v[0] / v[1] for k, v in surf.items() if v[1] > 100_000}

    ordered = sv.get("Grass", 0) > sv.get("Hard", 0) > sv.get("Clay", 1)
    in_band = 0.620 <= avg <= 0.650
    ok = ordered and in_band and bad == 0

    print(f"  matches 2000-2026      {len(modern):,}  ({bad} unparseable)")
    print(f"  passing arithmetic     {good:,}  ({100*good/len(modern):.1f}%)")
    print(f"  tour average serve     {avg:.4f}   "
          f"{'ok' if in_band else 'OUT OF BAND -- investigate'}")
    for k in sorted(sv, key=lambda k: -sv[k]):
        print(f"    {k:<8} {sv[k]:.4f}")
    print(f"  surface ordering       {'Grass>Hard>Clay ok' if ordered else 'WRONG'}")
    return ok, {"avg": avg, "n": len(modern)}


if __name__ == "__main__":
    check_only = "--check" in sys.argv

    if not check_only:
        if not os.path.isdir(os.path.join(REPO, ".git")):
            sys.exit(f"{REPO} is not a git clone -- re-clone the mirror first")

        code, dirty = sh("git", "status", "--porcelain", cwd=REPO)
        if dirty:
            print("local edits inside the data mirror -- refusing to overwrite:")
            print(dirty[:600])
            sys.exit("move your changes out, or use --check")

        code, before = sh("git", "rev-parse", "HEAD", cwd=REPO)
        print(f"current snapshot {before[:10]}")
        print("fetching ...")
        code, out = sh("git", "fetch", "--depth", "1", "origin", "main", cwd=REPO)
        if code:
            sys.exit(f"fetch failed:\n{out}")
        code, after = sh("git", "rev-parse", "origin/main", cwd=REPO)
        if before == after:
            print("already up to date -- nothing new upstream\n")
        else:
            sh("git", "reset", "--hard", "origin/main", cwd=REPO)
            print(f"updated {before[:10]} -> {after[:10]}\n")

    if not check_only and "--no-results" not in sys.argv:
        print("\nrefreshing results from tennisabstract.com "
              "(the mirror is dead; this is where new matches come from):")
        code, out = sh(sys.executable, "tools/ta/refresh.py")
        print("\n".join(out.splitlines()[-24:]) if out else "(no output)")
        if code:
            print("  results refresh FAILED -- continuing with what is on disk")

    if not check_only and "--no-weather" not in sys.argv:
        print("\nextending the weather cache to today:")
        code, out = sh(sys.executable, "weather.py", "fetch")
        tail = out.splitlines()
        print("\n".join(tail[:1] + tail[-3:]) if tail else "(no output)")
        if code:
            print("  weather extend FAILED -- density will fall back to None")

    if os.path.exists("data/manual_matches.csv"):
        n = sum(1 for _ in open("data/manual_matches.csv")) - 1
        print(f"\nmanual_matches.csv: {n} extra rows will be merged\n")

    print("re-verifying provenance (the mirror is third party):")
    ok, _ = verify()

    if not check_only:
        # historical-date books are cached as weights_<day>.json (book_*.json
        # is the pre-2026-09 name); both are derived from the data and go
        # stale with it
        stale = (glob.glob(os.path.join(CACHE, "book_*.json"))
                 + glob.glob(os.path.join(CACHE, "weights_*.json")))
        for f in stale:
            os.remove(f)
        print(f"\ninvalidated {len(stale)} cached rating book(s)")
        print("matchgrid.npz kept -- it depends on the rules, not the data")

    print("\n" + ("VERIFY PASS" if ok else "VERIFY FAIL -- do not trust these ratings"))
    sys.exit(0 if ok else 1)
