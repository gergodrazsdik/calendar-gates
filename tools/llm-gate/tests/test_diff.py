import pytest
from conftest import Repo

from llm_gate.diff import DiffError, merge_base_diff, touches, trim_large_files


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
    with pytest.raises(DiffError, match="bad revision"):
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


def test_the_diff_is_one_chunk_per_file_whatever_the_path(repo: Repo) -> None:
    """Chunks come from git, one call per file, so a quoted or awkward path can't merge two files
    into one chunk and hide the second behind the first."""
    repo.write("src/Api/A.cs", "class A {}\n")
    repo.write("src/Api/with a space.cs", "class B {}\n")
    repo.write("src/Api/Programé.cs", "class Accented {}\n")
    repo.commit("three awkward paths")

    diff = merge_base_diff(repo.root, "main")

    assert [path for path, _ in diff.chunks] == list(diff.files)
    assert sorted(diff.files) == [
        "src/Api/A.cs",
        "src/Api/Programé.cs",
        "src/Api/with a space.cs",
    ]
    assert all(chunk.startswith("diff --git ") for _, chunk in diff.chunks)
    for path, chunk in diff.chunks:
        assert path in chunk
    assert diff.text == "".join(chunk for _, chunk in diff.chunks)


def test_a_file_after_a_trimmed_one_is_still_reviewed(repo: Repo) -> None:
    """The swallowing bypass: a quoted path sorting after a trimmed generated file must not be
    dropped with it."""
    repo.write("src/Api/Migrations/Big.cs", "// generated\n" + "x = 1;\n" * 4000)
    repo.write("src/Api/Programé.cs", "// backdoor\n")
    repo.commit("generated, then an accented hand-written file")

    trimmed = trim_large_files(merge_base_diff(repo.root, "main"), max_file_kb=4)

    assert [o.path for o in trimmed.omitted] == ["src/Api/Migrations/Big.cs"]
    assert "// backdoor" in trimmed.text


def test_trim_large_files_drops_only_the_files_over_the_cap(repo: Repo) -> None:
    repo.write("src/Api/Small.cs", "class Small {}\n")
    repo.write("src/Api/Generated.pb.cs", "// generated\n" + "x = 1;\n" * 4000)  # TRIMMABLE
    repo.commit("hand-written next to generated")
    diff = merge_base_diff(repo.root, "main")

    trimmed = trim_large_files(diff, max_file_kb=4)

    assert [o.path for o in trimmed.omitted] == ["src/Api/Generated.pb.cs"]
    assert trimmed.omitted[0].bytes > 4 * 1024
    assert "class Small {}" in trimmed.text
    assert "Generated.pb.cs" not in trimmed.text
    # The file still counts as changed, so `paths:` filters and triage's size rule see it.
    assert trimmed.files == diff.files


def test_trim_large_files_keeps_a_file_under_the_cap(repo: Repo) -> None:
    repo.write("src/Api/Grpc/Edge.pb.cs", "y\n")
    repo.commit("small generated change")
    diff = merge_base_diff(repo.root, "main")

    assert len(diff.chunks[0][1].encode()) <= 1024
    assert trim_large_files(diff, max_file_kb=1).omitted == ()


def test_trim_large_files_returns_the_diff_unchanged_when_nothing_is_over(repo: Repo) -> None:
    repo.write("src/Api/A.cs", "class A {}\n")
    repo.commit("change")
    diff = merge_base_diff(repo.root, "main")

    assert trim_large_files(diff, max_file_kb=64) is diff


def test_a_hand_written_file_over_the_cap_is_never_trimmed(repo: Repo) -> None:
    """The bypass this closes: padding a file past the cap must not hide it from a review."""
    repo.write("src/Api/Program.cs", "// backdoor\n" + "// pad\n" * 4000)
    repo.commit("a big hand-written change")
    diff = merge_base_diff(repo.root, "main")

    trimmed = trim_large_files(diff, max_file_kb=4)

    assert trimmed is diff  # nothing dropped
    assert "// backdoor" in trimmed.text
    assert trimmed.omitted == ()


def test_only_generated_paths_are_trimmable(repo: Repo) -> None:
    repo.write("src/Api/Grpc/Service.pb.cs", "// generated\n" + "x = 1;\n" * 4000)
    repo.write("src/Api/Migrations/20261018_Init.cs", "// migration\n" + "y = 2;\n" * 4000)
    repo.write("src/Api/Big.cs", "// hand-written\n" + "z = 3;\n" * 4000)
    repo.commit("generated and hand-written, all over the cap")

    trimmed = trim_large_files(merge_base_diff(repo.root, "main"), max_file_kb=4)

    assert [o.path for o in trimmed.omitted] == [
        "src/Api/Grpc/Service.pb.cs",
        "src/Api/Migrations/20261018_Init.cs",
    ]
    assert "// hand-written" in trimmed.text


def test_the_trimmable_list_can_be_narrowed(repo: Repo) -> None:
    repo.write("src/Api/Grpc/Service.pb.cs", "// generated\n" + "x = 1;\n" * 4000)
    repo.commit("generated")
    diff = merge_base_diff(repo.root, "main")

    assert trim_large_files(diff, 4, trimmable=["**/Migrations/**"]) is diff


def test_only_a_marked_generated_file_is_trimmable(repo: Repo) -> None:
    repo.write("src/Api/Grpc/Marked.pb.cs", "// <auto-generated />\n" + "x = 1;\n" * 4000)
    repo.write("src/Api/Grpc/Unmarked.pb.cs", "// hand-written\n" + "y = 2;\n" * 4000)
    repo.commit("one generated, one only named like it")

    trimmed = trim_large_files(merge_base_diff(repo.root, "main"), max_file_kb=4, root=repo.root)

    assert [o.path for o in trimmed.omitted] == ["src/Api/Grpc/Marked.pb.cs"]
    assert "// hand-written" in trimmed.text


def test_a_deleted_generated_file_stays_in_the_diff(repo: Repo) -> None:
    """Its content is gone, so the marker can't be checked: it is reviewed rather than dropped."""
    from conftest import git

    git(repo.root, "switch", "-q", "main")
    repo.write("src/Api/Grpc/Gone.pb.cs", "// <auto-generated />\n" + "x = 1;\n" * 4000)
    repo.commit("add the generated file")
    git(repo.root, "switch", "-q", "feature")
    git(repo.root, "merge", "-q", "--ff-only", "main")
    (repo.root / "src/Api/Grpc/Gone.pb.cs").unlink()
    repo.commit("delete it")

    trimmed = trim_large_files(merge_base_diff(repo.root, "main"), max_file_kb=4, root=repo.root)

    assert trimmed.omitted == ()


def test_the_prs_own_gitattributes_cannot_hide_its_changes(repo: Repo) -> None:
    """F001: one `-diff` line used to turn every file into "Binary files ... differ" for both
    blocking reviews, with 0 changed lines for the size rule. Attributes come from the base now."""
    repo.write(".gitattributes", "* text=auto eol=lf\nsrc/** -diff\n.gitattributes -diff\n")
    repo.write("src/Api/Endpoints/Week.cs", "class Week { int Backdoor = 1; }\n")
    repo.commit("hide the change")

    diff = merge_base_diff(repo.root, "main")

    assert "Binary files" not in diff.text
    assert "+class Week { int Backdoor = 1; }" in diff.text
    assert "src/** -diff" in diff.text  # the attributes file itself is reviewed too


def test_a_nul_byte_cannot_hide_a_change_either(repo: Repo) -> None:
    """Git's binary heuristic needs no attributes at all; `--text` answers it."""
    (repo.root / "src/Api/Endpoints/Week.cs").write_bytes(
        b"class Week { int Backdoor = 1; }\n\x00\n"
    )
    repo.commit("hide the change with a NUL byte")

    diff = merge_base_diff(repo.root, "main")

    assert "Binary files" not in diff.text
    assert "+class Week { int Backdoor = 1; }" in diff.text


def test_vendored_fixtures_are_excluded_by_code_not_by_attributes(repo: Repo) -> None:
    repo.write("tools/llm-gate/tests/fixtures/schema.json", '{"big": true}\n')
    repo.write("src/Api/Endpoints/Week.cs", "class Week { int X = 2; }\n")
    repo.commit("a fixture and a real change")

    diff = merge_base_diff(repo.root, "main")

    assert diff.files == ("src/Api/Endpoints/Week.cs",)
    assert "schema.json" not in diff.text
