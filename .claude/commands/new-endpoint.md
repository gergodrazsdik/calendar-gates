---
description: Scaffold a new API endpoint with calculator, unit test, integration test and .http request
argument-hint: <name> [route and behaviour]
---

Add a new endpoint to calendar-gates: $ARGUMENTS

Follow the conventions in AGENTS.md. Create or update, in this order:

1. **Calculator** in `src/CalendarGates.Api/Domain/`: a pure, static class where possible. No
   `DateTime.Now`; if it needs "today", take a `DateOnly` parameter.
2. **Endpoint** in `src/CalendarGates.Api/Endpoints/<Name>Endpoints.cs`: a static class with a
   `Map<Name>Endpoints(this IEndpointRouteBuilder app)` extension, called from `Program.cs`. GET,
   JSON, dates as `yyyy-MM-dd`, "today" is the UTC date from the injected `TimeProvider`.
   Validate input and return `TypedResults.ValidationProblem` / ProblemDetails (400) on bad input.
   Use `TypedResults` so OpenAPI picks up the response types.
3. **Unit tests** in `tests/CalendarGates.UnitTests/`: TUnit, table-driven (`[Arguments]` or
   `[MethodDataSource]`), awaited assertions. Cover edge cases, not just the happy path.
4. **Integration tests** in `tests/CalendarGates.IntegrationTests/`: derive from `ApiTestBase`
   (fixed `FakeTimeProvider`), assert status code, JSON shape and ProblemDetails on bad input.
5. **HTTP request** in `http/calendar.http` with a `> {% client.test(...) %}` handler asserting
   status, content type and invariants (exact values only for fixed inputs).

Then run `just test` (and `just http` if the API is running) and report what you added. If the
name or route is ambiguous, ask before writing code.
