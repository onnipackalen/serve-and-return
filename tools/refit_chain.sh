#!/bin/sh
# The full refit after a model change, in the order the artefacts depend on
# each other.  Run from anywhere; logs to $1 (default /tmp/refit_chain.log).
#
#   sh tools/refit_chain.sh /tmp/chain.log
#
# About 25 minutes at the 7-day cadence when nothing else is running (the
# path sweep prices six configs in one walk and is the slow step: 383 s
# alone, 3,711 s with two other walks alongside -- ~1.5 hours for the chain
# when contended); ~15 minutes at 91 days.  Every step writes the file the
# next one reads, so do not reorder them.
set -e
LOG=${1:-/tmp/refit_chain.log}
cd "$(dirname "$0")/.."
{
  echo "== weights";        python3 weights.py --rebuild
  echo "== gate";           python3 backtest.py --gate
  echo "== backtest";       python3 backtest.py
  echo "== pathsweep";      python3 tools/pathsweep.py all
  echo "== curves build";   python3 tools/curves.py build
  echo "== curves loo";     python3 tools/curves.py loo
  echo "== curves antisym"; python3 tools/curves.py antisym --logit matches_28d event_gwp event_sets_lost home age form_spw resid_prior entry
  echo "== curves fit";     python3 tools/curves.py fit matches_28d event_gwp event_sets_lost home age form_spw resid_prior entry
  echo "== curves write";   python3 tools/curves.py write
  echo "== confidence";     python3 confidence.py fit
  echo "== disagree";       python3 tools/odds/disagree.py build && python3 tools/odds/disagree.py bands
  echo "== m4 2025";        python3 tools/odds/m4.py 2025
  echo "== m4 2024";        python3 tools/odds/m4.py 2024
  echo "== gates";          python3 tennis.py gates
  echo "== DONE"
} > "$LOG" 2>&1
