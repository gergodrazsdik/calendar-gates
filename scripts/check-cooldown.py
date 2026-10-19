#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Keep uv's supply-chain cooldown a rolling window of the length this project applies elsewhere.

`exclude-newer` is the cooldown: uv resolves only releases that are old enough. It used to be a
fixed date here, and a fixed date is a ceiling on *every* later resolution -- Dependabot's uv PRs
re-resolve under it and can never bring anything newer than the date, so updates stalled there
silently until someone moved it by hand (F076). uv 0.13 accepts a duration instead
(`exclude-newer = "14 days"`, recorded in the lock as `exclude-newer-span = "P14D"`), which makes
the window move itself.

So what this checks is no longer "has the date gone stale" but "is it still a window, and still the
right length":

- a fixed date anywhere fails, with the F076 reason -- that is the regression worth catching, and it
  is the one a careless `uv lock --exclude-newer <date>` or a copied snippet would reintroduce;
- a window shorter than MIN_DAYS fails: shorter than Dependabot's own `cooldown: default-days: 14`
  means the lock would admit releases the rest of the supply chain is still waiting on;
- a window longer than MAX_DAYS fails: a very long window is a stall of its own, just a less
  visible one, and security fixes would sit behind it;
- every file that should define one must still define one, so a renamed key fails here rather than
  quietly turning the cooldown off.

uv writes `exclude-newer = "0001-01-01T00:00:00Z"` into a lock alongside the span, documented in the
lock itself as having no effect and existing for backwards compatibility. That placeholder is not a
date for our purposes, and reading it as one would call the cooldown two million days stale.

Usage: scripts/check-cooldown.py [repo root]
"""

import re
import sys
from pathlib import Path

MIN_DAYS = 14
MAX_DAYS = 90

# `exclude-newer` in pyproject's [tool.uv] or a PEP 723 script's metadata; `exclude-newer-span` in
# the lock files that record what was resolved under it.
SETTING = re.compile(r"exclude-newer(?P<span>-span)?\s*=\s*\"(?P<value>[^\"]+)\"")
# uv's own placeholder, which the lock labels as having no effect.
PLACEHOLDER = "0001-01-01T00:00:00Z"
FILES = (
    "tools/llm-gate/pyproject.toml",
    "tools/llm-gate/uv.lock",
    "scripts/check-ruleset-consistency.py",
    "scripts/check-ruleset-consistency.py.lock",
)

# "14 days", "1 week", "24 hours", and the ISO 8601 forms uv also accepts (P14D, P2W, PT24H).
# Calendar units are not allowed in either spelling, so days are exact.
FRIENDLY = re.compile(
    r"^(?P<count>\d+)\s*(?P<unit>hours?|days?|weeks?)$", re.IGNORECASE
)
# An RFC 3339 timestamp or a plain date, which is what this check exists to reject.
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ISO = re.compile(
    r"^P(?:(?P<weeks>\d+)W|(?P<days>\d+)D|T(?P<hours>\d+)H)$", re.IGNORECASE
)


def window_days(value: str) -> float | None:
    """The length of a duration in days, or `None` if this is not a duration at all."""
    if friendly := FRIENDLY.match(value.strip()):
        count = int(friendly.group("count"))
        unit = friendly.group("unit").lower().rstrip("s")
        return count * {"hour": 1 / 24, "day": 1, "week": 7}[unit]
    if iso := ISO.match(value.strip()):
        if iso.group("weeks"):
            return int(iso.group("weeks")) * 7
        if iso.group("days"):
            return float(iso.group("days"))
        return int(iso.group("hours")) / 24
    return None


def main(root: Path) -> int:
    problems: list[str] = []
    windows: dict[str, float] = {}
    for name in FILES:
        path = root / name
        if not path.is_file():
            problems.append(f"{name}: missing, so nothing defines a cooldown for it")
            continue
        found = False
        for match in SETTING.finditer(path.read_text(encoding="utf-8")):
            value = match.group("value")
            if not match.group("span") and value == PLACEHOLDER:
                continue  # uv's backwards-compatibility placeholder, not a ceiling
            found = True
            days = window_days(value)
            if days is None and DATE.match(value):
                problems.append(
                    f"{name}: exclude-newer is the fixed date {value}. A date caps every later"
                    ' resolution, Dependabot\'s included (F076): use a duration, `"14 days"`.'
                )
            elif days is None:
                # uv allows hours, days and weeks; calendar units ("1 month", "1 year") it
                # rejects outright, because their length depends on when you ask.
                problems.append(
                    f"{name}: exclude-newer is {value!r}, which is neither a date nor a duration"
                    " uv accepts (hours, days, weeks; not months or years)."
                )
            elif days < MIN_DAYS:
                problems.append(
                    f"{name}: the cooldown is {value} ({days:g} days), under the {MIN_DAYS} days"
                    " Dependabot applies to the other ecosystems."
                )
            elif days > MAX_DAYS:
                problems.append(
                    f"{name}: the cooldown is {value} ({days:g} days), over {MAX_DAYS}. A window"
                    " that long holds back security fixes as surely as a stale date did."
                )
            else:
                windows[name] = days
        if not found:
            problems.append(
                f"{name}: no exclude-newer cooldown found. Did the key move, or was it removed?"
            )

    # The lock records the window it resolved under, so a lock disagreeing with its own
    # configuration means the lock predates a change to the cooldown and needs `uv lock`.
    lengths = set(windows.values())
    if len(lengths) > 1:
        shown = ", ".join(f"{name} {days:g}d" for name, days in sorted(windows.items()))
        problems.append(f"the cooldowns disagree ({shown}): re-lock so they match")

    for line in problems:
        print(f"::error file=tools/llm-gate/pyproject.toml::{line}")
    if problems:
        print(
            '\nThe cooldown is a rolling window: `exclude-newer = "14 days"` in'
            " tools/llm-gate/pyproject.toml and in scripts/check-ruleset-consistency.py's inline"
            " metadata, then `uv lock` there and `uv lock --script` for the script.",
            file=sys.stderr,
        )
        return 1
    print(
        f"{len(windows)} rolling exclude-newer cooldown(s) of"
        f" {next(iter(lengths)):g} days, between {MIN_DAYS} and {MAX_DAYS}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent)
    )
