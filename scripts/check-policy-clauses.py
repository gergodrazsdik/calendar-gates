#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Fail when an admission rule and its offline test drift apart.

Two admission clauses read a predicate rather than only checking that an attestation
exists: the vuln-scan rule in `base/release.yaml` ("no criticals", F069) and the
llm-review rule in `base/llm-review.yaml` ("every PR was reviewed"). Neither can be
exercised without a registry and a real signed attestation, which only release.yml's
admission-smoke has, so each is also evaluated as a *copy* over mock predicates in
`deploy/policies/tests/<name>-rule/`. A copy is evidence only while it is the same
clause, so this check compares them and says what to do when they differ.

Usage: scripts/check-policy-clauses.py [repo root]
"""

import re
import sys
from pathlib import Path

# The part of the clause that both files share: the real policy reads the predicate through
# extractPayload(image, attestations.vulnscan), the test through `object`.
RULES = {
    "vuln-scan": (
        ".predicate.results.all(r, r.counts.critical == 0)",
        Path("deploy/policies/base/release.yaml"),
        Path("deploy/policies/tests/vulnscan-rule/policy.yaml"),
    ),
    "llm-review": (
        ".predicate.unreviewed.size() == 0",
        Path("deploy/policies/base/llm-review.yaml"),
        Path("deploy/policies/tests/llmreview-rule/policy.yaml"),
    ),
}


def collapsed(path: Path) -> str:
    """The file as one line, so re-wrapping a folded block scalar doesn't matter."""
    return re.sub(r"\s+", " ", path.read_text())


def main(root: Path) -> int:
    failed = False
    for name, (clause, policy, test_policy) in RULES.items():
        problems = [
            f"{path}: expected the clause once, found it {found} time(s)"
            for path in (policy, test_policy)
            if (found := collapsed(root / path).count(clause)) != 1
        ]
        if not problems:
            print(f"{name}: the rule and its offline test carry the same clause")
            continue
        failed = True
        print(f"the {name} rule and its offline test have drifted:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"\nthe clause is: {clause}\n"
            f"If you changed the rule in {policy}, change the copy in {test_policy}\n"
            "the same way, add cases for the new behaviour to that directory's resources.yaml\n"
            "and kyverno-test.yaml, and update RULES in this script. Admission is the last\n"
            "thing between an unreviewed or vulnerable image and the cluster: it stays tested.",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(
        main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent)
    )
