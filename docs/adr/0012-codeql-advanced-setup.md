# 12. CodeQL advanced setup, so C# is scanned from a real build

- Status: accepted
- Date: 2026-10-31

## Context

CodeQL default setup scanned C# with `build-mode: none` and reported "Low C# analysis quality":
calls with a call target 76% (threshold 85%), expressions with a known type 86% (85%). Its own
`dotnet restore` failed with NU1102, though the fallback still resolved every reference. So the
likely cause is code CodeQL never sees without a build (TUnit source generators, ASP.NET minimal
APIs, System.Text.Json). That is an inference, not a measurement. Default setup can't change the
build mode of one language.

## Decision

**`.github/workflows/codeql.yml` replaces default setup**, with the same three languages, query
suite and `/language:<lang>` categories.

- **C# uses `build-mode: manual`** with the same restore and build commands as `_dotnet.yml`.
  `autobuild` would guess at what `_dotnet.yml` already states.
- **Python and Actions stay on `build-mode: none`.** They have nothing to compile.
- **Not a required check**, as before.
- **`ubuntu-26.04`, this workflow only.** No released actionlint knows the label, so
  `.github/actionlint.yaml` lists it until one does.

## Result

Both setups scanned the same PR commit (`20abd8c`). Default setup logged the warning again, at 76%
and 86%. The manual build ran the same quality query and logged no warning. The log prints the
percentages only when the warning fires, so this shows the improvement without giving the new
figures. It also doesn't confirm the generated-code explanation above.

## Consequences

- Every PR pays for one more C# build, and the workflow is ours to maintain. Dependabot keeps its
  actions current.
- Default setup must stay off, because GitHub rejects this workflow's uploads while it is on. The
  `just gh-codeql` recipe that turned it on is gone.
- Better coverage can surface C# alerts the old scan missed.
