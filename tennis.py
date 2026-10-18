#!/usr/bin/env python3
"""
Single front door.   python3 tennis.py [command] [args]

Run it with no arguments for an interactive prompt -- type two players and
get a price, no flags to remember:

    $ python3 tennis.py
    [bo3] > Sinner vs Alcaraz clay bo5

Or price one matchup and exit:

    app       browse it in a browser     tennis.py app
    news      injury / player news       tennis.py news --prompt "Alcaraz"
    price     price a matchup            tennis.py price Sinner Alcaraz clay bo5
    sim       simulate it point by point tennis.py sim Sinner Alcaraz clay bo5
    find      search for a player        tennis.py find murray
    weights   inspect derived weights    tennis.py weights Ruud
    workload  rest days + match load     tennis.py workload Alcaraz
    vars      list every input accepted  tennis.py vars
    update    refresh data + re-verify   tennis.py update
    fit       re-derive player weights   tennis.py fit
    backtest  re-fit form/calibration    tennis.py backtest
    gates     run every correctness gate tennis.py gates

Names are forgiving: surname, full name, "C Alcaraz", "Alcaraz, Carlos" and
typos all resolve, and an unmatched name suggests the nearest ones.

Everything is also runnable directly (price.py, weights.py, ...); this just
saves remembering which file does what.
"""

import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CMDS = {
    "app":      ("app.py", []),
    "news":     ("news.py", []),
    "price":    ("price.py", []),
    "sim":      ("simulate.py", []),
    "find":     ("price.py", ["--list"]),
    "weights":  ("weights.py", []),
    "workload": ("features.py", []),
    "vars":     ("price.py", ["--variables"]),
    "update":   ("update.py", []),
    "fit":      ("weights.py", ["--rebuild"]),
    "backtest": ("backtest.py", []),
}


def run(script, args):
    return subprocess.call([sys.executable, os.path.join(HERE, script)] + args)


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    # no command at all -> the interactive prompt, which is the point of entry
    # most people want and the one that needs no documentation
    if not argv:
        return run("price.py", [])

    cmd, rest = argv[0], argv[1:]

    if cmd == "gates":
        bad = 0
        for script, args, label in (
                ("check.py", [], "simulator vs exact recursion"),
                ("ratings.py", [], "estimator recovery + no leakage"),
                ("load.py", [], "data integrity + tour average"),
                ("players.py", [], "name resolution + line parsing"),
                ("features.py", [], "workload derivation"),
                ("backtest.py", ["--gate"],
                 "harness derivation == shipped weights.json")):
            print(f"\n{'='*60}\n{label}  ({script} {' '.join(args)})\n{'='*60}")
            bad += run(script, args) != 0
        print(f"\n{'ALL GATES PASS' if not bad else f'{bad} GATE(S) FAILED'}")
        return 1 if bad else 0

    if cmd not in CMDS:
        # `tennis.py Sinner Alcaraz` is what people type; treat it as a price
        # rather than an error, since no command name is a player name.
        return run("price.py", argv)

    script, pre = CMDS[cmd]
    return run(script, pre + rest)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
