# calendar-gates

A GitHub Actions playground: a tiny ASP.NET Core API about dates (ISO weeks, Friday the 13th,
Easter, workdays) wrapped in merge gates for formatting, tests, HTTP contract tests,
vulnerability scanning and an LLM reviewer built on the Claude SDKs.

It's a learning project, not production software. See [`docs/PLAN.md`](docs/PLAN.md) for the
plan and `docs/gates.md` for what each gate checks.

## Quick start

```bash
just setup   # restore local tools (and git hooks once they exist)
just         # list everything else
```

Requires the .NET 10 SDK (pinned in `global.json`) and [just](https://just.systems).

## License

[MIT](LICENSE)
