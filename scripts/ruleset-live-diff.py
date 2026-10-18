#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Diff a ruleset file against the live ruleset, ignoring what GitHub fills in itself.

`check-ruleset-consistency.py` validates the *file* against the workflows; nothing checked the file
against what is actually enforced, so a ruleset edited in the web UI drifted in silence (F074).
A literal comparison is useless here: the API adds defaults the file never set
(`required_reviewers: []`, `require_extra_approval_for_unattributed_changes`) and returns rule lists
in its own order. So this compares only the keys the file sets, recursively, with rule lists sorted
by type — anything the file says must be true of the live ruleset, and anything else is GitHub's
business.

Usage: scripts/ruleset-live-diff.py <ruleset.json> <live.json>
"""

import difflib
import json
import sys
from pathlib import Path
from typing import Any


def sort_rules(value: Any) -> Any:
    """Rule and bypass lists are sets in effect; order carries no meaning."""
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        key = "type" if all("type" in item for item in value) else None
        items = [sort_rules(item) for item in value]
        return (
            sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
            if key is None
            else sorted(items, key=lambda item: str(item.get("type")))
        )
    if isinstance(value, list):
        return [sort_rules(item) for item in value]
    if isinstance(value, dict):
        return {k: sort_rules(v) for k, v in value.items()}
    return value


def subset(wanted: Any, live: Any) -> Any:
    """`live`, reduced to the shape of `wanted`: the keys the file sets and nothing else."""
    if isinstance(wanted, dict) and isinstance(live, dict):
        return {k: subset(v, live.get(k)) for k, v in wanted.items()}
    if isinstance(wanted, list) and isinstance(live, list):
        return [
            subset(w, live[i] if i < len(live) else None) for i, w in enumerate(wanted)
        ]
    return live


def main(file_path: Path, live_path: Path) -> int:
    wanted = sort_rules(json.loads(file_path.read_text(encoding="utf-8")))
    live = sort_rules(json.loads(live_path.read_text(encoding="utf-8")))
    reduced = subset(wanted, live)
    if wanted == reduced:
        print(f"{wanted.get('name')}: the live ruleset matches {file_path}")
        return 0
    diff = difflib.unified_diff(
        json.dumps(wanted, indent=2, sort_keys=True).splitlines(),
        json.dumps(reduced, indent=2, sort_keys=True).splitlines(),
        fromfile=str(file_path),
        tofile="live",
        lineterm="",
    )
    print("\n".join(diff))
    print(
        f"::error::{wanted.get('name')} differs from {file_path}: "
        "apply the file with `just gh-rulesets`, or bring the file in line with the change"
    )
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
