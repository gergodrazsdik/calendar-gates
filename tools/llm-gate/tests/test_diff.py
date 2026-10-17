import pytest
from conftest import Repo

from llm_gate.diff import (
    DiffError,
    merge_base_diff,
    split_file_diffs,
    touches,
    trim_large_files,
)


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


def test_split_file_diffs_cuts_one_chunk_per_file(repo: Repo) -> None:
    repo.write("src/Api/A.cs", "class A {}\n")
    repo.write("src/Api/with a space.cs", "class B {}\n")
    repo.commit("two files")

    chunks = split_file_diffs(merge_base_diff(repo.root, "main").text)

    assert [path for path, _ in chunks] == ["src/Api/A.cs", "src/Api/with a space.cs"]
    assert all(chunk.startswith("diff --git ") for _, chunk in chunks)
    assert "class A {}" in chunks[0][1] and "class A {}" not in chunks[1][1]


def test_trim_large_files_drops_only_the_files_over_the_cap(repo: Repo) -> None:
    repo.write("src/Api/Small.cs", "class Small {}\n")
    repo.write("src/Api/Generated.pb.cs", "// generated\n" + "x = 1;\n" * 4000)
    repo.commit("hand-written next to generated")
    diff = merge_base_diff(repo.root, "main")

    trimmed = trim_large_files(diff, max_file_kb=4)

    assert [o.path for o in trimmed.omitted] == ["src/Api/Generated.pb.cs"]
    assert trimmed.omitted[0].bytes > 4 * 1024
    assert "class Small {}" in trimmed.text
    assert "Generated.pb.cs" not in trimmed.text
    # The file still counts as changed, so `paths:` filters and triage's size rule see it.
    assert trimmed.files == diff.files


def test_trim_large_files_keeps_a_file_exactly_at_the_cap(repo: Repo) -> None:
    repo.write("src/Api/Edge.cs", "y\n")
    repo.commit("small change")
    diff = merge_base_diff(repo.root, "main")
    size = len(split_file_diffs(diff.text)[0][1].encode())

    assert trim_large_files(diff, max_file_kb=1).omitted == ()  # the chunk is under 1 KB
    assert size <= 1024


def test_trim_large_files_returns_the_diff_unchanged_when_nothing_is_over(repo: Repo) -> None:
    repo.write("src/Api/A.cs", "class A {}\n")
    repo.commit("change")
    diff = merge_base_diff(repo.root, "main")

    assert trim_large_files(diff, max_file_kb=64) is diff
