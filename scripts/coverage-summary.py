#!/usr/bin/env python3
"""Merge Cobertura files (one per test project) and print a Markdown line-coverage table.

A line counts as covered if any test run hit it, so unit and integration coverage add up
instead of averaging. Usage: coverage-summary.py <cobertura.xml>... >> "$GITHUB_STEP_SUMMARY"
"""

import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: coverage-summary.py <cobertura.xml>...", file=sys.stderr)
        return 2

    # file -> line number -> covered by any run
    lines: dict[str, dict[int, bool]] = defaultdict(dict)
    for path in paths:
        for cls in ET.parse(path).iter("class"):
            filename = cls.get("filename", "?")
            if "/obj/" in filename.replace("\\", "/"):
                continue  # source-generated code (OpenAPI, validation)
            for line in cls.findall("lines/line"):
                number = int(line.get("number", "0"))
                hit = int(line.get("hits", "0")) > 0
                lines[filename][number] = lines[filename].get(number, False) or hit

    root = Path.cwd()
    rows = []
    for filename in sorted(lines):
        covered = sum(lines[filename].values())
        total = len(lines[filename])
        try:
            name = Path(filename).resolve().relative_to(root).as_posix()
        except ValueError:
            name = filename
        rows.append((name, covered, total))

    covered_all = sum(c for _, c, _ in rows)
    total_all = sum(t for _, _, t in rows)
    print(
        f"### Line coverage: {percent(covered_all, total_all)} ({covered_all}/{total_all})\n"
    )
    print("| File | Covered | Lines | Coverage |")
    print("|---|---:|---:|---:|")
    for name, covered, total in rows:
        print(f"| `{name}` | {covered} | {total} | {percent(covered, total)} |")
    return 0


def percent(covered: int, total: int) -> str:
    return f"{100 * covered / total:.1f}%" if total else "n/a"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
