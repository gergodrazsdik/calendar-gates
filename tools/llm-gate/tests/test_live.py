"""Opt-in smoke test against the real Claude API: `uv run pytest -m live` (costs a little)."""

import os
from pathlib import Path

import pytest
from conftest import make_check

from llm_gate.diff import Diff
from llm_gate.engines import ReviewRequest
from llm_gate.engines.api_engine import ApiEngine
from llm_gate.models import Severity

BUGGY_DIFF = """\
diff --git a/src/Workdays.cs b/src/Workdays.cs
--- a/src/Workdays.cs
+++ b/src/Workdays.cs
@@ -1,3 +1,3 @@
 public static int Count(DateOnly from, DateOnly to)
 {
-    var days = to.DayNumber - from.DayNumber + 1; // both ends inclusive
+    var days = to.DayNumber - from.DayNumber; // both ends inclusive
"""


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_api_engine_finds_a_planted_off_by_one(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[3]
    check = make_check(
        tmp_path,
        model="claude-haiku-5-5",
        prompt_path=repo / ".claude" / "commands" / "llm-code-review.md",
    )
    prompt = check.prompt_path.read_text(encoding="utf-8").split("---\n", 2)[2]
    diff = Diff(base="main", text=BUGGY_DIFF, files=("src/Workdays.cs",))

    out = ApiEngine().review(ReviewRequest(check, prompt, diff, tmp_path / "d.patch", repo))

    assert any(f.severity.at_least(Severity.MEDIUM) for f in out.review.findings)
