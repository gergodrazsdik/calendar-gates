import pytest
from conftest import Repo

from llm_gate.diff import DiffError, merge_base_diff, touches


def test_diff_contains_branch_changes_only(repo: Repo) -> None:
    repo.write("src/Api/Endpoints/Week.cs", "class Week { int Number; }\n")
    repo.commit("change")
    repo.write("README.md", "# uncommitted\n")  # not committed: not reviewed

    diff = merge_base_diff(repo.root, "main")

    assert diff.files == ("src/Api/Endpoints/Week.cs",)
    assert "+class Week { int Number; }" in diff.text
    assert "uncommitted" not in diff.text
    assert diff.size_bytes == len(diff.text.encode())


def test_generated_and_lock_files_are_excluded(repo: Repo) -> None:
    repo.write("src/Api/Real.cs", "class Real {}\n")
    repo.write("src/Api/packages.lock.json", "{}\n")
    repo.write("tools/x/uv.lock", "lock\n")
    repo.write("src/Api/Form.Designer.cs", "class Form {}\n")
    repo.write("src/Api/obj/Thing.g.cs", "class Thing {}\n")
    repo.write("tools/llm-gate/evals/cases/cr-9/diff.patch", "+planted bug\n")
    repo.commit("change")

    diff = merge_base_diff(repo.root, "main")

    assert diff.files == ("src/Api/Real.cs",)


def test_changes_on_main_after_branching_are_not_part_of_the_diff(repo: Repo) -> None:
    from conftest import git

    repo.write("feature.txt", "feature\n")
    repo.commit("feature work")
    git(repo.root, "switch", "-q", "main")
    repo.write("main.txt", "main moved on\n")
    repo.commit("main work")
    git(repo.root, "switch", "-q", "feature")

    diff = merge_base_diff(repo.root, "main")

    assert diff.files == ("feature.txt",)


def test_unknown_base_is_an_error(repo: Repo) -> None:
    with pytest.raises(DiffError, match="git diff"):
        merge_base_diff(repo.root, "origin/does-not-exist")


@pytest.mark.parametrize(
    ("files", "patterns", "expected"),
    [
        (["src/CalendarGates.Api/Endpoints/WeekEndpoints.cs"], ["src/**/Endpoints/**"], True),
        (["src/CalendarGates.Api/Domain/Easter.cs"], ["src/**/Endpoints/**"], False),
        (["http/calendar.http"], ["src/**/Endpoints/**", "http/**"], True),
        ([".github/workflows/ci.yml"], [".github/**"], True),
        (["docs/.github/x.md"], [".github/**"], False),
        ([], ["**"], False),
    ],
)
def test_paths_filter(files: list[str], patterns: list[str], expected: bool) -> None:
    assert touches(files, patterns) is expected
