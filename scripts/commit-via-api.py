#!/usr/bin/env python3
"""Commit working-tree files to a branch through the GitHub contents API.

For gate drills that must reach CI unchanged although a local hook would fix or block them
(drill 1: badly formatted C#; drills with failing tests and the pre-push hook). The commit is
made by GitHub, so local hooks never run; `--no-verify` is not needed and not allowed here.
Writing files under .github/workflows/ needs a gh token with the `workflow` scope.

Usage: scripts/commit-via-api.py <branch> <commit message> <path>...
The branch is created from origin's main if it does not exist; each path is uploaded as it is on
disk now, one commit per file.
"""

import base64
import json
import os
import subprocess
import sys
from typing import Any

REPO = os.environ.get("GITHUB_REPOSITORY", "gergodrazsdik/calendar-gates")


def gh(*args: str, data: dict[str, Any] | None = None, ok404: bool = False) -> Any:
    cmd = ["gh", "api", *args]
    if data is not None:
        cmd += ["--input", "-"]
    result = subprocess.run(
        cmd,
        input=json.dumps(data) if data is not None else None,
        capture_output=True,
        text=True,
        check=False,  # the return code is handled below
    )
    if result.returncode != 0:
        if ok404 and "404" in result.stderr + result.stdout:
            return None
        sys.exit(f"gh api {' '.join(args)} failed: {result.stderr or result.stdout}")
    return json.loads(result.stdout) if result.stdout.strip() else {}


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    branch, message, *paths = sys.argv[1:]
    if gh(f"repos/{REPO}/git/ref/heads/{branch}", ok404=True) is None:
        main_sha = gh(f"repos/{REPO}/git/ref/heads/main")["object"]["sha"]
        gh(
            f"repos/{REPO}/git/refs",
            "-X",
            "POST",
            data={"ref": f"refs/heads/{branch}", "sha": main_sha},
        )
    for path in paths:
        existing = gh(f"repos/{REPO}/contents/{path}?ref={branch}", ok404=True)
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        body = {"message": message, "content": content, "branch": branch}
        if existing:
            body["sha"] = existing["sha"]
        gh(f"repos/{REPO}/contents/{path}", "-X", "PUT", data=body)
        print(f"{branch}: committed {path}")


if __name__ == "__main__":
    main()
