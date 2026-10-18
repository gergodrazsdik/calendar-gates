import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import FakeEngine, Repo, finding, git, result

from llm_gate import evals
from llm_gate.cli import main
from llm_gate.engines import EngineError, ReviewRequest
from llm_gate.models import EngineResult, Severity, Usage

REAL_CASES = Path(__file__).parent.parent / "evals" / "cases"

CHECKS = """\
defaults: {model: claude-test-model}
checks:
  code-review: {mode: blocking, fail_on: high}
  docs-drift: {mode: advisory}
"""


def add_case(
    repo: Repo,
    case_id: str,
    *,
    kind: str = "bug",
    new_text: str = "class A { int x = 2; }\n",
    expect: list[dict[str, Any]] | None = None,
    forbid: list[dict[str, Any]] | None = None,
    checks: tuple[str, ...] = ("code-review",),
) -> Path:
    """A case whose patch changes src/A.cs on the repository's main commit."""
    base = git(repo.root, "rev-parse", "main").strip()
    git(repo.root, "switch", "-q", "--detach", "main")
    (repo.root / "src" / "A.cs").write_text(new_text)
    patch = git(repo.root, "diff")
    git(repo.root, "checkout", "-q", "--", ".")
    git(repo.root, "switch", "-q", "feature")
    directory = repo.root / "tools" / "llm-gate" / "evals" / "cases" / case_id
    directory.mkdir(parents=True)
    (directory / "diff.patch").write_text(patch)
    (directory / "case.yaml").write_text(
        yaml.safe_dump(
            {
                "id": case_id,
                "kind": kind,
                "checks": list(checks),
                "source": "test",
                "description": "test case",
                "base": base,
                "expect": expect or [],
                "forbid": forbid or [],
            }
        )
    )
    return directory


@pytest.fixture
def eval_repo(repo: Repo, monkeypatch: pytest.MonkeyPatch) -> Repo:
    git(repo.root, "switch", "-q", "main")
    repo.write("tools/llm-gate/checks.yaml", CHECKS)
    repo.write("src/A.cs", "class A { int x = 1; }\n")
    repo.commit("config")
    git(repo.root, "switch", "-q", "feature")
    git(repo.root, "merge", "-q", "--ff-only", "main")
    repo.write("tools/llm-gate/evals/thresholds.yaml", "budget_usd: 1\nmax_recall_drop: 0.05\n")
    monkeypatch.chdir(repo.root)
    return repo


BUG = [{"file": "src/A.cs", "lines": [1, 1], "min_severity": "high"}]


def reviewer(*, severity: Severity = Severity.HIGH, line: int = 1) -> FakeEngine:
    """Reports one finding on src/A.cs when the patch touches it, at `severity`."""

    def review(request: ReviewRequest) -> EngineResult:
        hit = "src/A.cs" in request.diff.files
        findings = [finding(severity, file="src/A.cs", line=line)] if hit else []
        out = result(*findings)
        return out.model_copy(update={"usage": Usage(cost_usd=0.01)})

    return FakeEngine("api", review)


# --- cases ---


def test_every_committed_case_is_valid_and_applies_to_its_base() -> None:
    cases = evals.load_cases(REAL_CASES)
    assert len(cases) >= 20
    root = Path(git(REAL_CASES, "rev-parse", "--show-toplevel").strip())
    missing: list[str] = []
    for loaded in cases:
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{loaded.case.base}^{{commit}}"], cwd=root, check=False
        )
        if exists.returncode != 0:
            # In CI this is a failure: the lint job checks out the full history for exactly this
            # test, and one missing base used to skip the whole thing (F017). Locally a shallow
            # clone is a fair reason to skip, but only the cases it affects.
            missing.append(f"{loaded.case.id}: base {loaded.case.base[:12]} not in this clone")
            continue
        evals.case_diff(loaded)
        with evals.workspace(root, loaded) as tree:
            for path in evals.patch_files(loaded.patch):
                assert (tree / path).exists(), f"{loaded.case.id}: {path} missing after apply"
        for expectation in loaded.case.expect:
            assert expectation.file in evals.patch_files(loaded.patch), loaded.case.id
        # A forbid rule naming a file the patch doesn't touch can never match, so the case would
        # pass for the wrong reason for ever (F019).
        for rule in loaded.case.forbid:
            assert rule.file in evals.patch_files(loaded.patch), f"{loaded.case.id}: {rule.file}"
        # Canonical form (what add-from-fp writes), so yamllint and the dumper agree.
        assert (loaded.directory / "case.yaml").read_text() == evals.dump_case(loaded.case)

    if missing and os.environ.get("CI"):
        pytest.fail("; ".join(missing))
    if missing:
        pytest.skip("; ".join(missing))


def test_cases_are_validated(eval_repo: Repo) -> None:
    directory = add_case(eval_repo, "bug-1", expect=BUG)
    cases = eval_repo.root / "tools" / "llm-gate" / "evals" / "cases"
    assert [c.case.id for c in evals.load_cases(cases)] == ["bug-1"]

    data = yaml.safe_load((directory / "case.yaml").read_text())
    (directory / "case.yaml").write_text(yaml.safe_dump({**data, "id": "other"}))
    with pytest.raises(evals.EvalError, match="must match the directory name"):
        evals.load_cases(cases)
    (directory / "case.yaml").write_text(yaml.safe_dump({**data, "base": "main"}))
    with pytest.raises(evals.EvalError, match="full commit SHA"):
        evals.load_cases(cases)
    (directory / "case.yaml").write_text(yaml.safe_dump({**data, "surprise": 1}))
    with pytest.raises(evals.EvalError, match="Extra inputs"):
        evals.load_cases(cases)


def test_a_patch_that_does_not_apply_is_an_error(eval_repo: Repo) -> None:
    directory = add_case(eval_repo, "bug-1", expect=BUG)
    (directory / "diff.patch").write_text(
        (directory / "diff.patch").read_text().replace("int x = 1", "int y = 9")
    )
    (loaded,) = evals.load_cases(directory.parent)
    with (
        pytest.raises(evals.EvalError, match="does not apply"),
        evals.workspace(eval_repo.root, loaded),
    ):
        pass


# --- scoring ---


@pytest.mark.parametrize(
    ("line", "severity", "hit"),
    [
        (10, Severity.HIGH, True),
        (13, Severity.HIGH, True),  # within the slack of 3
        (14, Severity.HIGH, False),
        (6, Severity.CRITICAL, True),
        (10, Severity.MEDIUM, False),  # not severe enough
    ],
)
def test_matching(line: int, severity: Severity, hit: bool) -> None:
    expectation = evals.Expectation(file="src/a.cs", lines=(9, 10), min_severity=Severity.HIGH)
    assert evals.matches(finding(severity, line=line), expectation) is hit
    assert not evals.matches(finding(Severity.HIGH, line=None), expectation)
    assert not evals.matches(finding(Severity.HIGH, file="src/b.cs", line=10), expectation)


def test_a_file_level_expectation_matches_a_finding_with_no_line() -> None:
    """Some right answers have no line: "nothing tests this" is about a file. The models report it
    both ways between repeats, and a case that needs a line scores 0 on the repeats without one."""
    expectation = evals.Expectation(file="src/a.cs", lines=None, min_severity=Severity.MEDIUM)

    assert evals.matches(finding(Severity.MEDIUM, line=None), expectation)
    assert evals.matches(finding(Severity.HIGH, line=999), expectation)
    assert not evals.matches(finding(Severity.LOW, line=None), expectation)  # severity still counts
    assert not evals.matches(finding(Severity.HIGH, file="src/b.cs", line=None), expectation)


def attempt(verdict: str, found: list[bool], below: int = 0, cost: float = 0.01) -> evals.Attempt:
    return evals.Attempt(
        repeat=1,
        verdict=verdict,
        exit_code=1 if verdict == "fail" else 0,
        found=found,
        forbidden_hits=0,
        below_threshold=below,
        findings=len(found),
        cost_usd=cost,
        duration_ms=1000,
        cached=False,
    )


def test_metrics() -> None:
    results = [
        evals.CaseResult(
            case="bug",
            kind="bug",
            expected_verdict="fail",
            attempts=[attempt("fail", [True]), attempt("pass", [False])],
        ),
        evals.CaseResult(
            case="clean",
            kind="clean",
            expected_verdict="pass",
            attempts=[attempt("pass", [], below=2), attempt("fail", [], below=0)],
        ),
        evals.CaseResult(
            case="inj",
            kind="injection",
            expected_verdict="fail",
            attempts=[attempt("fail", [True]), attempt("fail", [True])],
        ),
    ]

    m = evals.metrics(results, repeats=2)

    assert m.recall == pytest.approx(3 / 4)
    assert m.false_block_rate == pytest.approx(1 / 2)
    assert m.noise == pytest.approx(1.0)
    assert m.verdict_accuracy == pytest.approx(4 / 6)
    assert m.flip_rate == pytest.approx(2 / 3)
    assert m.injection_resistance == 1.0
    assert m.cost_usd == pytest.approx(0.06)
    assert m.cost_p50 == pytest.approx(0.01)


# --- running ---


def run(eval_repo: Repo, engine: FakeEngine, *args: str) -> int:
    return main(["eval", "run", *args], engines={"api": engine, "agent": engine})


def last_runs(eval_repo: Repo) -> list[dict[str, Any]]:
    out = eval_repo.root / "reports" / "eval"
    (name,) = json.loads((out / "last.json").read_text())
    runs: list[dict[str, Any]] = json.loads((out / name).read_text())
    return runs


def test_a_bug_case_is_found_and_a_clean_case_not_blocked(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    add_case(eval_repo, "clean-1", kind="clean", new_text="class A { int x = 1; } // c\n")
    engine = reviewer()

    assert run(eval_repo, engine, "--check", "code-review", "--repeats", "2") == 0

    (report,) = last_runs(eval_repo)
    m = report["metrics"]
    assert m["recall"] == 1.0
    assert m["false_block_rate"] == 1.0  # the fake reviewer flags every change to A.cs
    assert m["verdict_accuracy"] == 0.5
    assert m["cases"] == 2
    assert len(engine.requests) == 4  # two cases, two repeats each
    out = capsys.readouterr().out
    assert "| code-review | `api` / `claude-test-model` | 2 x 2 |" in out
    assert "**clean-1** (clean): verdict wrong 2/2" in out


def test_repeats_are_separate_and_reruns_are_cached(eval_repo: Repo) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    engine = reviewer()

    run(eval_repo, engine, "--repeats", "3")
    run(eval_repo, engine, "--repeats", "3")

    assert len(engine.requests) == 3
    (report,) = last_runs(eval_repo)
    assert all(a["cached"] for a in report["results"][0]["attempts"])


def test_the_agent_reads_the_case_tree_not_the_repository(eval_repo: Repo) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    seen: list[str] = []

    def review(request: ReviewRequest) -> EngineResult:
        seen.append((request.repo_root / "src" / "A.cs").read_text())
        return result()

    run(eval_repo, FakeEngine("api", review), "--repeats", "1")

    assert seen == ["class A { int x = 2; }\n"]  # the patched file in the case's workspace
    assert (eval_repo.root / "src" / "A.cs").read_text() == "class A { int x = 1; }\n"


def test_the_budget_stops_the_run(eval_repo: Repo, caplog: pytest.LogCaptureFixture) -> None:
    for n in range(3):
        add_case(eval_repo, f"bug-{n}", expect=BUG)
    engine = reviewer()

    assert run(eval_repo, engine, "--repeats", "1", "--budget-usd", "0.015", "--jobs", "1") == 2

    assert len(engine.requests) == 2  # stops once the spend reaches the budget
    assert "budget" in caplog.text
    (report,) = last_runs(eval_repo)
    assert report["complete"] is False


def test_engine_errors_are_counted(eval_repo: Repo) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    run(eval_repo, FakeEngine("api", EngineError("down")), "--repeats", "1")
    (report,) = last_runs(eval_repo)
    assert report["metrics"]["errors"] == 1
    assert report["metrics"]["recall"] == 0.0


def test_fp_regression_cases_count_forbidden_findings(eval_repo: Repo) -> None:
    add_case(
        eval_repo,
        "fp-1",
        kind="fp-regression",
        forbid=[{"file": "src/A.cs", "lines": [1, 1]}],
    )
    run(eval_repo, reviewer(severity=Severity.LOW), "--repeats", "1")
    (report,) = last_runs(eval_repo)
    assert report["metrics"]["fp_regressions"] == 1


def test_each_run_writes_an_eval_run_audit_record(eval_repo: Repo) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    run(eval_repo, reviewer(), "--repeats", "1")
    (line,) = (eval_repo.root / ".llm-gate" / "audit.jsonl").read_text().splitlines()
    record = json.loads(line)
    assert record["type"] == "eval_run"
    assert record["scores"]["code-review.recall"] == 1.0


# --- baseline and comparison ---


def test_baseline_then_a_recall_drop_fails_the_comparison(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    run(eval_repo, reviewer(), "--repeats", "1")
    assert main(["eval", "baseline"]) == 0
    baseline = json.loads(
        (eval_repo.root / "tools" / "llm-gate" / "evals" / "baseline.json").read_text()
    )
    assert baseline["code-review"]["api/claude-test-model"]["metrics"]["recall"] == 1.0
    capsys.readouterr()

    # A reviewer that only reports medium: the bug is no longer found (recall 1.0 -> 0.0).
    weaker = reviewer(severity=Severity.MEDIUM)
    assert run(eval_repo, weaker, "--repeats", "1", "--compare", "--no-cache") == 1

    out = capsys.readouterr().out
    assert "| recall | 1.00 | 0.00 | drop ≤ 0.05 | ❌ |" in out


def test_an_incomplete_run_is_not_a_baseline(eval_repo: Repo) -> None:
    for n in range(2):
        add_case(eval_repo, f"bug-{n}", expect=BUG)
    run(eval_repo, reviewer(), "--repeats", "1", "--budget-usd", "0.005", "--jobs", "1")
    assert main(["eval", "baseline"]) == 2


def test_without_a_baseline_the_comparison_fails_instead_of_passing_vacuously(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """F008: a check whose engine or model has no baseline entry used to skip recall, false blocks
    and verdict accuracy, which made the gate vacuous for exactly the change worth checking."""
    add_case(eval_repo, "bug-1", expect=BUG)

    assert run(eval_repo, reviewer(), "--repeats", "1", "--compare") == 1

    # The row itself, not just the words somewhere in the report (tr-4185 on #72).
    rows = [line for line in capsys.readouterr().out.splitlines() if "an entry for" in line]
    assert len(rows) == 1
    assert rows[0].startswith("| baseline ")
    assert "api/claude-test-model" in rows[0]


# --- fp-regression cases from the audit log ---


def test_add_from_fp_builds_a_case_from_the_audit_log(eval_repo: Repo) -> None:
    git(eval_repo.root, "switch", "-q", "feature")
    eval_repo.write("src/A.cs", "class A { int x = 3; }\n")
    eval_repo.commit("change")
    base = git(eval_repo.root, "rev-parse", "main").strip()
    head = git(eval_repo.root, "rev-parse", "HEAD").strip()
    events = eval_repo.root / ".audit-log" / "events" / "2026" / "10" / "16"
    events.mkdir(parents=True)
    record = {
        "type": "gate_run",
        "check": "code-review",
        "pr": 7,
        "base_sha": base,
        "head_sha": head,
        "workflow_modified": False,
        "findings": [
            {
                "id": "cr-abcd",
                "file": "src/A.cs",
                "line": 1,
                "category": "style",
                "title": "Uses $IMAGE (undefined?)",
            }
        ],
    }
    (events / "1-1-code-review.jsonl").write_text(json.dumps(record) + "\n")

    assert main(["eval", "add-from-fp", "cr-abcd"]) == 0

    cases = eval_repo.root / "tools" / "llm-gate" / "evals" / "cases"
    (loaded,) = evals.load_cases(cases)
    assert loaded.case.kind == "fp-regression"
    forbid = loaded.case.forbid[0]
    assert (forbid.file, forbid.category) == ("src/A.cs", None)  # categories vary run to run
    assert forbid.title == r"^Uses\ \$IMAGE\ \(undefined\?\)$"  # exact, escaped
    assert loaded.case.base == base
    assert "int x = 3" in loaded.patch

    assert main(["eval", "add-from-fp", "cr-ffff"]) == 2  # not in the log


def test_parallel_jobs_keep_the_case_order(eval_repo: Repo) -> None:
    for n in range(6):
        add_case(eval_repo, f"bug-{n}", expect=BUG)
    engine = reviewer()

    assert run(eval_repo, engine, "--repeats", "2", "--jobs", "4") == 0

    (report,) = last_runs(eval_repo)
    assert [r["case"] for r in report["results"]] == [f"bug-{n}" for n in range(6)]
    assert len(engine.requests) == 12
    assert report["metrics"]["recall"] == 1.0


def test_dumped_cases_load_back() -> None:
    case = evals.Case(
        id="x",
        kind="fp-regression",
        checks=["code-review"],
        source="s",
        description="d",
        base="a" * 40,
        forbid=[evals.Forbidden(file="f", lines=(1, 2))],
    )
    text = evals.dump_case(case)
    assert evals.Case.model_validate(yaml.safe_load(text)) == case
    assert "\n  - file: f\n" in text  # list items indented, as yamllint wants


def test_not_applicable_is_a_pass_and_is_explained(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    eval_repo.write(
        "tools/llm-gate/checks.yaml",
        CHECKS + "  api-contract: {mode: advisory, paths: ['src/**/Endpoints/**']}\n",
    )
    eval_repo.commit("api-contract with a paths filter")  # add_case resets the working tree
    add_case(eval_repo, "ac-1", expect=BUG, checks=("api-contract",))

    run(eval_repo, reviewer(), "--repeats", "1")

    (report,) = last_runs(eval_repo)
    assert report["metrics"]["verdict_accuracy"] == 1.0  # the gate passes it
    assert report["metrics"]["recall"] == 0.0
    out = capsys.readouterr().out
    assert "not applicable (the check's `paths:` skipped it)" in out


def test_misses_show_where_the_findings_pointed(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    run(eval_repo, reviewer(line=40), "--repeats", "1")
    assert "found instead: `high src/A.cs:40`" in capsys.readouterr().out


def test_cached_reviews_keep_their_cost_but_cost_nothing_now(eval_repo: Repo) -> None:
    add_case(eval_repo, "bug-1", expect=BUG)
    run(eval_repo, reviewer(), "--repeats", "2")
    run(eval_repo, reviewer(), "--repeats", "2")

    (report,) = last_runs(eval_repo)
    assert report["metrics"]["cost_usd"] == pytest.approx(0.02)  # comparable with the baseline
    assert report["metrics"]["spent_usd"] == 0.0


def test_found_and_blocking_are_scored_separately(eval_repo: Repo) -> None:
    # Found at medium (recall), but the gate should still fail on it (verdict).
    expect = [{"file": "src/A.cs", "lines": [1, 1], "min_severity": "medium", "blocking": True}]
    add_case(eval_repo, "bug-1", expect=expect)

    run(eval_repo, reviewer(severity=Severity.MEDIUM), "--repeats", "1")

    (report,) = last_runs(eval_repo)
    assert report["metrics"]["recall"] == 1.0
    assert report["metrics"]["verdict_accuracy"] == 0.0
    assert report["results"][0]["expected_verdict"] == "fail"


def test_forbid_by_title_regex_ignores_the_category() -> None:
    rule = evals.Forbidden(file="a.yml", title=r"\$IMAGE")
    same = finding(Severity.MEDIUM, file="a.yml", line=None)
    assert not evals.forbidden_hit(same, rule)  # title "medium problem"
    reworded = same.model_copy(
        update={"title": "Checks use $image, never defined", "category": "x"}
    )
    assert evals.forbidden_hit(reworded, rule)
    assert not evals.forbidden_hit(reworded.model_copy(update={"file": "b.yml"}), rule)
    with pytest.raises(ValueError):
        evals.Forbidden(file="a.yml", title="(unclosed")


def test_a_baseline_for_another_engine_does_not_count(
    eval_repo: Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    """The entry has to be for this check's engine and model: a baseline recorded for the api
    engine says nothing about the same prompt on the agent engine."""
    add_case(eval_repo, "bug-1", expect=BUG)
    baseline = eval_repo.root / "tools" / "llm-gate" / "evals" / "baseline.json"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(
        json.dumps(
            {
                "code-review": {
                    "agent/claude-test-model": {
                        "prompt_sha256": "0" * 64,
                        "cases": 1,
                        "repeats": 1,
                        "metrics": {"recall": 1.0, "flip_rate": 0.0, "cost_usd": 0.01},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert run(eval_repo, reviewer(), "--repeats", "1", "--compare") == 1

    assert "an entry for api/claude-test-model" in capsys.readouterr().out


def test_the_eval_scores_the_engine_a_risk_level_switches_a_check_to() -> None:
    """security-review is configured `api` but reviews on `agent` at high risk, which is most PRs
    here; the eval only ever scored the configured engine, so the agent prompt went unscored
    although its baseline entry existed (F009)."""
    from pathlib import Path

    from llm_gate.cli import _engines_to_score
    from llm_gate.config import load_gate_config

    gate = load_gate_config(Path("checks.yaml"), Path(__file__).resolve().parents[3])
    assert gate.triage is not None

    assert _engines_to_score(gate.checks["security-review"], gate.triage) == ["api", "agent"]
    assert _engines_to_score(gate.checks["code-review"], gate.triage) == ["agent"]
    # An advisory check is never moved, so there is nothing extra to score for it.
    assert _engines_to_score(gate.checks["docs-drift"], gate.triage) == ["api"]
    assert _engines_to_score(gate.checks["docs-drift"], None) == ["api"]
