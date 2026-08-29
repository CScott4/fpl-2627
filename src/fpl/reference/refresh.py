"""Ongoing (in-season) refresh of the FPL <-> Understat reference tables.

Ports `RefreshLiveFPLReferences.py`. Re-runs the matching in
`fpl.reference.build.build_player_reference` against the *live* FPL
bootstrap API, so ids stay correct as the season progresses (new
signings, id churn, etc.), reusing the baseline `teams_reference` written
by the season-start `fpl.reference.build.run()`.

TODO: port `main()`, replacing bootstrap fetch with `requests.get` against
`fpl.config.FPL_BOOTSTRAP_URL` and DB I/O with `fpl.db` helpers.
"""
from __future__ import annotations


def run() -> None:
    """Entry point used by scripts/update_data.py."""
    raise NotImplementedError("Port from RefreshLiveFPLReferences.py")


if __name__ == "__main__":
    run()
