"""Review prompts live in .claude/commands/llm-<check>.md, shared with interactive Claude Code."""

import re
from collections.abc import Iterable
from pathlib import Path

from .diff import OmittedFile

_FENCE = "---"


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            return "".join(lines[index + 1 :]).lstrip("\n")
    return text  # unterminated frontmatter: leave the text alone


def load_prompt(path: Path) -> str:
    """The prompt body, without frontmatter; both engines get the diff inline after it."""
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def render(prompt: str, arguments: str) -> str:
    """Substitute $ARGUMENTS the way Claude Code does for a slash command."""
    return prompt.replace("$ARGUMENTS", arguments)


# What $ARGUMENTS becomes when the gate runs the prompt: both engines pass the diff inline, so the
# prompt text (from the gate's own checkout) is the only instruction the reviewer gets.
DIFF_REFERENCE = "the unified diff inside the <diff> element below"


def diff_block(base: str, text: str, omitted: Iterable[OmittedFile] = ()) -> str:
    """Wrap the diff in one <diff> element. A literal `</diff` inside the diff is escaped, so a
    change can't close the element early and put text outside it (where it would read as
    instructions rather than data).

    `omitted` names the generated files left out for size (ADR 0002), so the reviewer knows the
    diff is partial and can say so instead of reading silence as "nothing there".
    """
    escaped = re.sub(r"</(diff)", r"<\\/\1", text, flags=re.IGNORECASE)
    block = f'<diff base="{base}">\n{escaped}\n</diff>'
    files = list(omitted)
    if not files:
        return block
    names = "\n".join(f"- {f.path} ({f.bytes // 1024} KB)" for f in files)
    return (
        f"{block}\n<omitted-for-size>\nThese generated files changed too but are not in the diff "
        f"above, because each one's own diff is over the size cap. You have not reviewed them:\n"
        f"{names}\n</omitted-for-size>"
    )
