"""The shell scripts in the gate's trusted path (`scripts/`), with `gh` stubbed out.

`override-writers.sh` decides who may honour a bot-added `llm-override` label (ADR 0007) and whose
`/llm-risk` the collector accepts (ADR 0008). Nothing tested it, and a filter that looked only at
`/llm-override` comments made the collector reject a legitimate `/llm-risk`, turning a whole run
into tamper events in v0.3.2's release attestation (#68).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "override-writers.sh"

# What the stub `gh` answers for `collaborators/<login>/permission`.
ROLES = {"alice": "admin", "bob": "write", "carol": "read", "dave": "none"}


@pytest.fixture
def gh_stub(tmp_path: Path) -> Path:
    """A `gh` on PATH that answers the one API call the script makes."""
    stub = tmp_path / "bin"
    stub.mkdir()
    roles = json.dumps(ROLES)
    (stub / "gh").write_text(
        "#!/usr/bin/env bash\n"
        'login=$(printf "%s\\n" "$@" | sed -n "s|.*collaborators/\\(.*\\)/permission|\\1|p")\n'
        f"role=$(printf '%s' '{roles}' | jq -r --arg l \"$login\" '.[$l] // \"none\"')\n"
        'if [ "$role" = none ]; then exit 1; fi\n'
        'printf "%s\\n" "$role"\n',
        encoding="utf-8",
    )
    (stub / "gh").chmod(0o755)
    return stub


def writers(comments: list[dict[str, object]], tmp_path: Path, gh_stub: Path) -> list[str]:
    path = tmp_path / "comments.json"
    path.write_text(json.dumps(comments), encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{gh_stub}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "owner/repo",
    }
    out = subprocess.run(
        ["bash", str(SCRIPT), str(path)], check=True, capture_output=True, text=True, env=env
    ).stdout
    result: list[str] = json.loads(out)
    return sorted(result)


def comment(login: str, body: str) -> dict[str, object]:
    return {"user": {"login": login}, "body": body}


def test_every_command_counts_not_only_override(tmp_path: Path, gh_stub: Path) -> None:
    """The bug behind #68's tamper events: a PR with a `/llm-risk` and no `/llm-override` gave an
    empty list, so the collector refused the risk record it had just been handed."""
    found = writers(
        [comment("alice", "/llm-risk high the chart change deserves it")], tmp_path, gh_stub
    )

    assert found == ["alice"]


def test_only_logins_that_may_write_are_listed(tmp_path: Path, gh_stub: Path) -> None:
    found = writers(
        [
            comment("alice", "/llm-override reviewed by hand"),  # admin
            comment("bob", "/llm-fp cr-1234 a false positive"),  # write
            comment("carol", "/llm-risk low docs only"),  # read: not a writer
            comment("dave", "/llm-ack cr-1234"),  # not a collaborator at all
            comment("alice", "a plain comment, not a command"),
        ],
        tmp_path,
        gh_stub,
    )

    assert found == ["alice", "bob"]


def test_a_bot_login_is_never_a_writer(tmp_path: Path, gh_stub: Path) -> None:
    """`github-actions[bot]` adds the label on a command's behalf; it must not also be the author
    that makes it count (ADR 0007)."""
    found = writers(
        [comment("github-actions[bot]", "/llm-override not mine to give")], tmp_path, gh_stub
    )

    assert found == []


def test_no_commands_at_all_is_an_empty_list(tmp_path: Path, gh_stub: Path) -> None:
    assert writers([comment("alice", "looks good to me")], tmp_path, gh_stub) == []
