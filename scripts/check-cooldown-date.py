#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Fail when a uv `exclude-newer` cooldown date has gone stale.

`exclude-newer` is the supply-chain cooldown: uv resolves only releases that existed at that
instant, which is what the project wants when it locks. But it is a *fixed* date, so it also caps
everything that re-resolves later — Dependabot's uv PRs re-resolve under the same ceiling and can
never bring anything newer than the date, however many times they run (F076). Nothing said when the
date was last moved, so the stall was invisible.

This makes it visible: a date older than MAX_AGE_DAYS fails the lint gate, and the fix is to move it
(`uv lock --upgrade` in that directory, or `uv lock --script <file>` for a PEP 723 script).

The other end is checked too. The point of the ceiling is to *be* the 14-day delay the rest of the
supply chain applies (Dependabot's `cooldown: 14`, scripts/check-tool-pins.py), so a date moved to
today or yesterday is not a fresher cooldown -- it is no cooldown, admitting releases that have been
public for a day. Moving it means moving it to two weeks ago, not to now.

Usage: scripts/check-cooldown-date.py [repo root]
"""

import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

MAX_AGE_DAYS = 90
MIN_AGE_DAYS = 14
# Where a cooldown date lives: pyproject's [tool.uv], a script's inline metadata, and the lock files
# that record what it resolved under.
PATTERN = re.compile(r'exclude-newer\s*=\s*"(\d{4}-\d{2}-\d{2})')
FILES = (
    "tools/llm-gate/pyproject.toml",
    "tools/llm-gate/uv.lock",
    "scripts/check-ruleset-consistency.py",
    "scripts/check-ruleset-consistency.py.lock",
)


def main(root: Path) -> int:
    today = datetime.now(UTC).date()
    stale: list[str] = []
    too_new: list[str] = []
    found = 0
    for name in FILES:
        path = root / name
        if not path.is_file():
            continue
        for match in PATTERN.finditer(path.read_text(encoding="utf-8")):
            found += 1
            age = (today - date.fromisoformat(match.group(1))).days
            if age > MAX_AGE_DAYS:
                stale.append(
                    f"{name}: exclude-newer {match.group(1)} is {age} days old"
                )
            elif age < MIN_AGE_DAYS:
                too_new.append(
                    f"{name}: exclude-newer {match.group(1)} is only {age} days back, inside the"
                    f" {MIN_AGE_DAYS}-day cooldown"
                )
    if not found:
        print("no exclude-newer cooldown found: did the files move?", file=sys.stderr)
        return 1
    for line in stale + too_new:
        print(f"::error file=tools/llm-gate/pyproject.toml::{line}")
    if too_new:
        print(
            f"\nThe ceiling is the cooldown: it has to sit at least {MIN_AGE_DAYS} days in the"
            " past, or the lock admits releases that have been public for a day.",
            file=sys.stderr,
        )
        return 1
    if stale:
        print(
            f"\nA cooldown older than {MAX_AGE_DAYS} days caps every later resolution, Dependabot's"
            " included. Move it: `uv lock --upgrade` in tools/llm-gate (and `uv lock --script` for"
            " the scripts), then commit the lock files.",
            file=sys.stderr,
        )
        return 1
    print(
        f"{found} exclude-newer cooldown(s), each between {MIN_AGE_DAYS} and {MAX_AGE_DAYS} days back"
    )
    return 0


if __name__ == "__main__":
    sys.exit(
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent)
    )
