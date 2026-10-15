"""Review prompts live in .claude/commands/llm-<check>.md, shared with interactive Claude Code."""

from pathlib import Path

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
    """The prompt body, without frontmatter (the agent engine reads the file itself)."""
    return strip_frontmatter(path.read_text(encoding="utf-8"))


def render(prompt: str, arguments: str) -> str:
    """Substitute $ARGUMENTS the way Claude Code does for a slash command."""
    return prompt.replace("$ARGUMENTS", arguments)


# What $ARGUMENTS becomes when the gate runs the prompt: both engines pass the diff inline, so the
# prompt text (from the gate's own checkout) is the only instruction the reviewer gets.
DIFF_REFERENCE = "the unified diff inside the <diff> element below"


def diff_block(base: str, text: str) -> str:
    return f'<diff base="{base}">\n{text}\n</diff>'
