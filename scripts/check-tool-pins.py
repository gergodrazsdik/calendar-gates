#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""The tool versions Dependabot cannot see: keep the definitions in step, and say what is behind.

Dependabot watches `uses:` SHAs, NuGet, the Dockerfile and uv's lock. It does not watch a version
passed as a `with:` input (grype, syft, helm, kind, kubectl, just), a container image run inside a
`run:` step (actionlint, hadolint, kubeconform, the Kyverno CLI, ijhttp) or a `uvx tool@version`
(zizmor, yamllint, ruff) — eighteen pins in this repository, several of them written in more than
one file (F080).

Each is now defined once per file: a workflow's `env:` block, or a `just` variable. This script is
the thing that keeps those definitions equal to each other, and `--updates` asks the upstreams what
the current version is and reports what we are behind. Default mode is offline and fails on
disagreement; `--updates` needs the network and only reports.

`--updates` reports the newest release that is **at least two weeks old**, not the newest release.
That is the same cooldown the rest of the supply chain uses -- Dependabot's `cooldown: 14` and uv's
`exclude-newer` in `tools/llm-gate/pyproject.toml` -- and a report measuring against the newest
release instead would be asking for a bump the project's own policy says to wait on. A release
younger than that is shown in its own column, so the wait is visible rather than invisible.

Usage: scripts/check-tool-pins.py [--updates] [repo root]
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The supply-chain delay this repository applies everywhere else (Dependabot `cooldown: 14`,
# uv `exclude-newer`): a release has to have been out this long before a gate is pinned to it.
COOLDOWN = timedelta(days=14)

# tool -> (where its current version is defined, how to ask upstream)
# A GitHub repository means "latest release tag"; a PyPI name means "latest version".
GITHUB = "github"
PYPI = "pypi"
MANUAL = "manual"
SOURCES: dict[str, tuple[str, str]] = {
    "just": (GITHUB, "casey/just"),
    "helm": (GITHUB, "helm/helm"),
    "kind": (GITHUB, "kubernetes-sigs/kind"),
    "kubectl": (GITHUB, "kubernetes/kubernetes"),
    "grype": (GITHUB, "anchore/grype"),
    "syft": (GITHUB, "anchore/syft"),
    "actionlint": (GITHUB, "rhysd/actionlint"),
    "hadolint": (GITHUB, "hadolint/hadolint"),
    "kubeconform": (GITHUB, "yannh/kubeconform"),
    "kyverno_cli": (GITHUB, "kyverno/kyverno"),
    "zizmor": (PYPI, "zizmor"),
    "yamllint": (PYPI, "yamllint"),
    "ruff": (PYPI, "ruff"),
    # No release feed worth trusting from CI: JetBrains publishes ijhttp as Docker tags only, and
    # the rest are pinned by digest next to the thing that consumes them.
    "ijhttp": (MANUAL, "hub.docker.com/r/jetbrains/intellij-http-client/tags"),
}

# Where each definition lives. `kubectl` is deliberately different between the two workflows: the
# project cluster runs 1.35 for Kyverno (ADR 0010), so it is excluded from the equality check.
WORKFLOW_PINS = {
    ".github/workflows/ci.yml": (
        "just",
        "helm",
        "kind",
        "kubectl",
        "grype",
        "zizmor",
        "yamllint",
        "ruff",
        "actionlint",
        "hadolint",
        "kubeconform",
        "kyverno_cli",
        "ijhttp",
    ),
    ".github/workflows/release.yml": (
        "helm",
        "kind",
        "kubectl",
        "grype",
        "syft",
        "ijhttp",
    ),
}
JUSTFILE_PINS = ("zizmor", "yamllint", "ruff", "kyverno_cli")
MAY_DIFFER = {"kubectl"}

_VERSION_IN_IMAGE = re.compile(r":(?P<version>[^@\s]+)(@sha256:[0-9a-f]{64})?$")


def workflow_pins(path: Path) -> dict[str, str]:
    """`NAME_VERSION: v1.2.3` and `NAME_IMAGE: repo/name:tag@sha256:…` from a workflow's env."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s{2}([A-Z0-9_]+)_(VERSION|IMAGE): (\S+)$", line)
        if not match:
            continue
        name, kind, value = match.group(1).lower(), match.group(2), match.group(3)
        if kind == "IMAGE":
            tag = _VERSION_IN_IMAGE.search(value)
            if tag is None:
                continue
            value = tag.group("version")
        found[name] = value.removeprefix("v")
    return found


def justfile_pins(path: Path) -> dict[str, str]:
    """`name_version := "1.2.3"` from the justfile's variables."""
    text = path.read_text(encoding="utf-8")
    return {
        name.removesuffix("_version"): value.removeprefix("v")
        for name, value in re.findall(
            r'^([a-z0-9_]+_version) := "([^"]+)"$', text, re.MULTILINE
        )
    }


_PRERELEASE = re.compile(r"-(rc|alpha|beta|pre)", re.IGNORECASE)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)  # 3.11+ parses the trailing Z


def version_key(version: str) -> tuple[int, ...]:
    """`1.58.0` -> `(1, 58, 0)`, for comparing two of these tools' versions.

    Ordering by release *date* instead would be wrong for any project that maintains more than one
    branch: helm's newest release by date is a 3.22.x maintenance build, not 4.3.x. Pre-releases are
    filtered out before this runs, so numeric components are all there is to compare.
    """
    return tuple(int(part) for part in re.findall(r"\d+", version))


def latest(kind: str, source: str) -> tuple[str | None, str | None]:
    """`(newest eligible, newest overall)` upstream *stable* versions.

    Eligible means released at least `COOLDOWN` ago. The two differ exactly when upstream has
    published something inside the cooldown window, which is the case worth seeing. `releases/latest`
    can be a release candidate -- Kyverno tags them as full releases -- and a candidate is not
    something to bump a gate to.
    """
    url = (
        f"https://api.github.com/repos/{source}/releases?per_page=30"
        if kind == GITHUB
        else f"https://pypi.org/pypi/{source}/json"
    )
    headers = {"User-Agent": "calendar-gates-tool-pins"}
    # Unauthenticated GitHub is 60 requests an hour per IP, shared with every other job on the
    # runner, and a rate-limited table reports "could not be reached" for half the tools. The
    # token is only ever used to read public release lists.
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if kind == GITHUB and token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        print(
            f"  {source}: could not ask upstream ({type(error).__name__})",
            file=sys.stderr,
        )
        return None, None

    # (published_at, version), newest first. PyPI dates a version by its earliest file upload;
    # ordering by that date rather than by parsing versions keeps this dependency-free, and a
    # yanked-then-reuploaded version is not something to bump to anyway.
    released: list[tuple[datetime, str]] = []
    if kind == PYPI:
        for version, files in data["releases"].items():
            uploads = [
                _parse_time(f["upload_time_iso_8601"])
                for f in files
                if not f.get("yanked")
            ]
            if uploads and not _PRERELEASE.search(version):
                released.append((min(uploads), version.removeprefix("v")))
    else:
        for release in data:
            tag = str(release.get("tag_name", ""))
            when = release.get("published_at")
            if (
                release.get("prerelease")
                or release.get("draft")
                or _PRERELEASE.search(tag)
            ):
                continue
            if when:
                released.append((_parse_time(str(when)), tag.removeprefix("v")))
    if not released:
        return None, None
    cutoff = datetime.now(UTC) - COOLDOWN
    out = [version for when, version in released if when <= cutoff]
    eligible = max(out, key=version_key) if out else None
    return eligible, max((v for _, v in released), key=version_key)


def main(root: Path, *, updates: bool) -> int:
    sources: dict[str, dict[str, str]] = {}
    for name, tools in WORKFLOW_PINS.items():
        pins = workflow_pins(root / name)
        missing = sorted(set(tools) - set(pins))
        if missing:
            print(
                f"::error file={name}::no pin found for {missing} (renamed, or no longer there?)"
            )
            return 1
        sources[name] = {tool: pins[tool] for tool in tools}
    pins = justfile_pins(root / "justfile")
    missing = sorted(set(JUSTFILE_PINS) - set(pins))
    if missing:
        print(f"::error file=justfile::no pin found for {missing}")
        return 1
    sources["justfile"] = {tool: pins[tool] for tool in JUSTFILE_PINS}

    errors = 0
    everywhere: dict[str, str] = {}
    for where, pinned in sources.items():
        for tool, version in pinned.items():
            if tool in MAY_DIFFER:
                continue
            first = everywhere.setdefault(tool, version)
            if version != first:
                print(
                    f"::error file={where}::{tool} is {version} here but {first} elsewhere: "
                    "the definitions must agree"
                )
                errors += 1
    if errors:
        return 1

    print(
        f"{len(everywhere)} tool pin(s) outside Dependabot's reach, all definitions agreeing"
    )
    if not updates:
        return 0

    print("\n### Tool versions outside Dependabot's reach\n")
    print(f"Upstream = newest release at least {COOLDOWN.days} days old.\n")
    print("| Tool | Pinned | Upstream | In cooldown | |")
    print("|---|---|---|---|---|")
    for tool in sorted(everywhere | {t: "" for t in ("kubectl", "syft")}):
        version = (
            everywhere.get(tool) or sources[".github/workflows/ci.yml"].get(tool) or ""
        )
        if tool == "syft":
            version = sources[".github/workflows/release.yml"]["syft"]
        if tool == "kubectl":
            ci = sources[".github/workflows/ci.yml"]["kubectl"]
            release = sources[".github/workflows/release.yml"]["kubectl"]
            version = f"{ci} (ci), {release} (release)"
        kind, source = SOURCES[tool]
        if kind == MANUAL:
            print(f"| {tool} | {version} | — | — | check by hand: {source} |")
            continue
        upstream, newest = latest(kind, source)
        waiting = newest if newest and newest != upstream else "—"
        if upstream is None:
            print(
                f"| {tool} | {version} | ? | {waiting} | upstream could not be reached |"
            )
        elif tool == "kubectl":
            print(
                f"| {tool} | {version} | {upstream} | {waiting} "
                "| pinned to the cluster, not to latest |"
            )
        elif version_key(version) < version_key(upstream):
            print(f"| {tool} | {version} | {upstream} | {waiting} | **behind** |")
        elif version_key(version) > version_key(upstream):
            print(
                f"| {tool} | {version} | {upstream} | {waiting} "
                f"| ahead: pinned inside the {COOLDOWN.days}-day cooldown |"
            )
        else:
            print(f"| {tool} | {version} | {upstream} | {waiting} | current |")
    print(
        "\nBumping one means editing the definition in each file the table's tool appears in; "
        "`scripts/check-tool-pins.py` fails the lint gate if they then disagree."
    )
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--updates"]
    sys.exit(
        main(
            Path(args[0]) if args else Path(__file__).parent.parent,
            updates="--updates" in sys.argv,
        )
    )
