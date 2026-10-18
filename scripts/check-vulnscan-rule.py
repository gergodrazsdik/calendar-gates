#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Fail when the vuln-scan rule in the admission policy and its offline test drift apart.

`deploy/policies/base/release.yaml` decides admission with a CEL clause over the
vulnerability-scan attestation, and that clause can only be exercised against a real
signed attestation (release.yml's admission-smoke). The offline test in
`deploy/policies/tests/vulnscan-rule/` therefore evaluates a *copy* of the clause over
mock predicates. A copy is only evidence while it is the same clause, so this check
compares the two and says what to do when they differ (F069).

Usage: scripts/check-vulnscan-rule.py [repo root]
"""

import re
import sys
from pathlib import Path

# The part of the clause that both files share: the real policy reads the predicate through
# extractPayload(image, attestations.vulnscan), the test through `object`.
CLAUSE = ".predicate.results.all(r, r.counts.critical == 0)"

POLICY = Path("deploy/policies/base/release.yaml")
TEST_POLICY = Path("deploy/policies/tests/vulnscan-rule/policy.yaml")


def collapsed(path: Path) -> str:
    """The file as one line, so re-wrapping a folded block scalar doesn't matter."""
    return re.sub(r"\s+", " ", path.read_text())


def main(root: Path) -> int:
    problems = []
    for path in (POLICY, TEST_POLICY):
        found = collapsed(root / path).count(CLAUSE)
        if found != 1:
            problems.append(
                f"{path}: expected the clause once, found it {found} time(s)"
            )
    if problems:
        print("the vuln-scan rule and its offline test have drifted:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"\nthe clause is: {CLAUSE}\n"
            f"If you changed the rule in {POLICY}, change the copy in {TEST_POLICY} the\n"
            "same way, add cases for the new behaviour to that directory's resources.yaml\n"
            "and kyverno-test.yaml, and update CLAUSE in this script. Admission is the only\n"
            "thing standing between a critical finding and the cluster: it stays tested.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent)
    )
