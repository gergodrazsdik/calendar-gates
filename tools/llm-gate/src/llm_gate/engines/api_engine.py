"""Claude API engine: one Messages request with the diff inline, structured output into Review."""

import time
from typing import Any

import anthropic
from pydantic import BaseModel

from ..models import EngineResult, Review, Usage
from ..prompts import DIFF_REFERENCE, diff_block, render
from . import EngineError, ReviewRequest

MAX_TOKENS = 16_000

# List prices per million tokens (input, output), for the cost estimate in reports.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Models with server-side refusal fallbacks (`fallbacks: "default"`); Haiku has none.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


def structured_call[T: BaseModel](
    client: Any | None,
    *,
    model: str,
    system: str,
    user: str,
    output_format: type[T],
    what: str,
    max_tokens: int = MAX_TOKENS,
) -> tuple[Any, T]:
    """One Messages request with structured output: the response and its parsed output. Every
    failure (API, refusal, truncation, no output) is an EngineError. Shared by the review engine
    and triage (`triage.assess`)."""
    fallback = model in FALLBACK_MODELS
    try:
        # Creating the client already fails without credentials (no ANTHROPIC_API_KEY).
        client = client or anthropic.Anthropic()
        response = client.beta.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
            betas=[FALLBACK_BETA] if fallback else anthropic.omit,
            fallbacks="default" if fallback else anthropic.omit,
        )
    except anthropic.APIStatusError as error:
        raise EngineError(f"Claude API error {error.status_code}: {error.message}") from error
    except anthropic.APIConnectionError as error:
        raise EngineError(f"cannot reach the Claude API: {error}") from error
    except anthropic.AnthropicError as error:  # e.g. no credentials configured
        raise EngineError(f"Claude API client error: {error}") from error

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise EngineError(f"the model declined the {what} (category: {category})")
    if response.stop_reason == "max_tokens":
        raise EngineError(f"the {what} was cut off at max_tokens={max_tokens}")
    parsed = response.parsed_output
    if not isinstance(parsed, output_format):
        stop = response.stop_reason
        raise EngineError(f"no structured {what} in the response (stop reason: {stop})")
    return response, parsed


class ApiEngine:
    name = "api"

    def __init__(self, client: Any | None = None) -> None:
        # Any: tests pass a stub with the same `beta.messages.parse` shape.
        self._client = client

    def review(self, request: ReviewRequest) -> EngineResult:
        started = time.monotonic()
        response, review = structured_call(
            self._client,
            model=request.check.model,
            system=render(request.prompt, DIFF_REFERENCE),
            user=diff_block(request.diff.base, request.diff.text, request.diff.omitted),
            output_format=Review,
            what="review",
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        usage = response.usage
        return EngineResult(
            engine=self.name,
            model=response.model,
            review=review,
            duration_ms=duration_ms,
            usage=Usage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=estimate_cost(response.model, usage.input_tokens, usage.output_tokens),
                cost_estimated=True,
                num_turns=1,
            ),
        )
