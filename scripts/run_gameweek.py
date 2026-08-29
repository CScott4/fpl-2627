#!/usr/bin/env python
"""Simulate upcoming fixtures and optimise squad selection.

Usage:
    python scripts/run_gameweek.py --simulations 10000 --gameweeks 5
"""
from __future__ import annotations

import argparse

from fpl.simulate import engine
from fpl.squad import optimize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--gameweeks", type=int, default=5)
    args = parser.parse_args()

    print(f"Simulating next {args.gameweeks} gameweek(s) x {args.simulations} runs...")
    engine.run(n_simulations=args.simulations, n_gameweeks=args.gameweeks)

    print("Optimising squad...")
    optimize.run()

    print("Done.")


if __name__ == "__main__":
    main()
