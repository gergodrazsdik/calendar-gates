# 1. CSharpier owns C# formatting

- Status: accepted
- Date: 2026-10-15

## Context

Two tools can rewrite C# layout: CSharpier (opinionated, almost no options) and `dotnet format`
(driven by `.editorconfig`). If both run, they disagree on details such as line breaks and wrapping,
and the `format` gate flip-flops depending on which ran last. `dotnet format` also does more than
layout: it applies code-style rules (`IDE*`) and analyzer fixes (`CA*`), which CSharpier doesn't.

## Decision

- **Layout** belongs to CSharpier alone: `dotnet csharpier format .` to fix, `dotnet csharpier check .`
  to verify. It runs on save (VS Code), after every agent edit (`.claude/hooks/format-cs.sh`), in the
  pre-commit hook and in the `format` CI gate. The version is pinned in `.config/dotnet-tools.json`.
- **Rules** belong to `dotnet format style` and `dotnet format analyzers`, only ever with
  `--verify-no-changes` in the gate. `dotnet format whitespace` (and plain `dotnet format`, which
  includes it) is never run.
- `.editorconfig` holds naming and style rules. Its layout settings (`indent_size = 4`,
  `max_line_length = 100`, LF, final newline) only mirror CSharpier's defaults so editors agree with
  it, and must not be changed to anything CSharpier would undo.

## Consequences

- No formatting debates: whatever CSharpier produces is correct.
- A rule finding (`IDE1006` naming, `CA*`) fails `format` with a message that points at a rule, not
  at whitespace.
- Updating CSharpier can reformat files; do it in its own PR (Dependabot `nuget` covers the tool
  manifest), with only the reformat in it.
