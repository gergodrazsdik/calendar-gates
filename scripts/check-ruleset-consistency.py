#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["pyyaml>=6.0.3"]
# [tool.uv]
# exclude-newer = "2026-10-05T00:00:00Z"
# ///
"""Fail when .github/rulesets/main.json and the workflows or checks.yaml disagree.

A required check that no job produces never reports, so it blocks every PR; a renamed job silently
stops being required; a blocking LLM check (at any triage risk level) that is not required can be
ignored. This catches all three before the ruleset is applied.

It also pins `llm-review.yml`'s matrix list to `checks.yaml`. That list is spelled out in the
workflow on purpose — a matrix built from a job's output can't expand until that job finishes, and a
run cancelled before that leaves a check named `${{ matrix.check }}` behind for ever — so the
duplication is deliberate and this is what keeps it true.

Usage: scripts/check-ruleset-consistency.py [repo root]
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

GITHUB_ACTIONS_APP_ID = 15368
WORKFLOWS = ("ci.yml", "pr-title.yml", "llm-review.yml", "llm-eval.yml")
MATRIX_CHECK = "${{ matrix.check }}"
# The workflow and job whose matrix must list exactly the checks in checks.yaml.
MATRIX_JOB = ("llm-review.yml", "llm")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def job_check_names(
    workflows_dir: Path, workflow: str, llm_checks: list[str]
) -> tuple[set[str], set[str]]:
    """Check names a workflow's jobs report, as GitHub renders them, and those whose job carries an
    `if:` that can skip them. A required check that never reports blocks every PR, and one that
    reports "skipped" satisfies the ruleset without having run, so both are worth knowing (F074).
    `always()` is fine: the job runs and decides for itself."""
    names: set[str] = set()
    conditional: set[str] = set()
    for job_id, job in load_yaml(workflows_dir / workflow)["jobs"].items():
        name = str(job.get("name", job_id))
        uses = job.get("uses", "")
        mine: set[str] = set()
        if uses.startswith("./.github/workflows/"):
            # A job calling a reusable workflow reports `<caller> / <called job>`.
            called = load_yaml(workflows_dir / Path(uses).name)["jobs"]
            mine = {f"{name} / {c.get('name', cid)}" for cid, c in called.items()}
        elif MATRIX_CHECK in name:
            mine = {name.replace(MATRIX_CHECK, check) for check in llm_checks}
        else:
            mine = {name}
        names |= mine
        condition = str(job.get("if", "")).strip()
        if condition and "always()" not in condition:
            conditional |= mine
    return names, conditional


def matrix_checks(workflow: Path, job_id: str) -> list[str] | None:
    """The job's literal `strategy.matrix.check` list, sorted, or None when it isn't one."""
    job = load_yaml(workflow)["jobs"].get(job_id, {})
    values = ((job.get("strategy") or {}).get("matrix") or {}).get("check")
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        return None
    return sorted(values)


def blocking_checks(config: dict[str, Any]) -> set[str]:
    """Checks that can fail a PR. With triage (ADR 0008), those that block at *any* risk level:
    a check that blocks only at high risk must still be required, or a high-risk PR could merge
    past it."""
    checks = config["checks"]
    triage = config.get("triage")
    if not triage:
        return {name for name, spec in checks.items() if spec.get("mode") == "blocking"}
    return {
        name
        for level in triage["levels"].values()
        for name in level.get("blocking", [])
    }


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
    config = load_yaml(root / "tools" / "llm-gate" / "checks.yaml")
    checks = config["checks"]
    blocking = blocking_checks(config)
    produced: set[str] = set()
    conditional: set[str] = set()
    for workflow in WORKFLOWS:
        names, skippable = job_check_names(
            root / ".github" / "workflows", workflow, list(checks)
        )
        produced |= names
        conditional |= skippable

    errors: list[str] = []
    matrix = matrix_checks(
        root / ".github" / "workflows" / MATRIX_JOB[0], MATRIX_JOB[1]
    )
    if matrix is None:
        errors.append(
            f"{MATRIX_JOB[0]}: job {MATRIX_JOB[1]!r} has no literal matrix of checks"
        )
    elif matrix != sorted(checks):
        missing = sorted(set(checks) - set(matrix))
        extra = sorted(set(matrix) - set(checks))
        errors.append(
            f"{MATRIX_JOB[0]}'s matrix does not match checks.yaml"
            + (f"; missing {missing}" if missing else "")
            + (f"; unknown {extra}" if extra else "")
        )
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
        if context in conditional:
            # GitHub treats a skipped required check as satisfied, so a job-level `if:` on a
            # required check is a way past the ruleset without running anything (F074).
            errors.append(
                f"required check {context!r} comes from a job with an `if:` that can skip it"
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
