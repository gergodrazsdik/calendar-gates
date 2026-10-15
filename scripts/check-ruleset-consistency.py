#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml>=6.0.3"]
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///
"""Fail when .github/rulesets/main.json and the workflows or checks.yaml disagree.

A required check that no job produces never reports, so it blocks every PR; a renamed job silently
stops being required; a blocking LLM check that is not required can be ignored. This catches all
three before the ruleset is applied. Usage: scripts/check-ruleset-consistency.py [repo root]
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

GITHUB_ACTIONS_APP_ID = 15368
WORKFLOWS = ("ci.yml", "llm-review.yml")
MATRIX_CHECK = "${{ matrix.check }}"


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def job_check_names(
    workflows_dir: Path, workflow: str, llm_checks: list[str]
) -> set[str]:
    """Check names a workflow's jobs report, as GitHub renders them."""
    names: set[str] = set()
    for job_id, job in load_yaml(workflows_dir / workflow)["jobs"].items():
        name = str(job.get("name", job_id))
        uses = job.get("uses", "")
        if uses.startswith("./.github/workflows/"):
            # A job calling a reusable workflow reports `<caller> / <called job>`.
            called = load_yaml(workflows_dir / Path(uses).name)["jobs"]
            names |= {f"{name} / {c.get('name', cid)}" for cid, c in called.items()}
        elif MATRIX_CHECK in name:
            names |= {name.replace(MATRIX_CHECK, check) for check in llm_checks}
        else:
            names.add(name)
    return names


def main(root: Path) -> int:
    ruleset = json.loads(
        (root / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8")
    )
    required = [
        check
        for rule in ruleset["rules"]
        if rule["type"] == "required_status_checks"
        for check in rule["parameters"]["required_status_checks"]
    ]
    checks = load_yaml(root / "tools" / "llm-gate" / "checks.yaml")["checks"]
    blocking = {name for name, spec in checks.items() if spec.get("mode") == "blocking"}
    produced: set[str] = set()
    for workflow in WORKFLOWS:
        produced |= job_check_names(
            root / ".github" / "workflows", workflow, list(checks)
        )

    errors: list[str] = []
    contexts = {check["context"] for check in required}
    for check in required:
        context = check["context"]
        if context not in produced:
            errors.append(
                f"required check {context!r} is not produced by any job in {WORKFLOWS}"
            )
        if check.get("integration_id") != GITHUB_ACTIONS_APP_ID:
            errors.append(
                f"required check {context!r} is not pinned to GitHub Actions (15368)"
            )
    required_llm = {
        c.removeprefix("llm / ") for c in contexts if c.startswith("llm / ")
    }
    for name in sorted(blocking - required_llm):
        errors.append(
            f"blocking LLM check {name!r} is not required: add 'llm / {name}'"
        )
    for name in sorted(required_llm - blocking):
        errors.append(
            f"'llm / {name}' is required but {name!r} is not a blocking check"
        )

    for error in errors:
        print(f"::error file=.github/rulesets/main.json::{error}")
    if not errors:
        print(
            f"ruleset consistent: {len(required)} required checks, blocking LLM {sorted(blocking)}"
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
