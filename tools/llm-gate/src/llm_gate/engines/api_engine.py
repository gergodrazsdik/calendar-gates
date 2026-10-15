"""Claude API engine: one Messages request with the diff inline, structured output into Review."""

import time
from typing import Any

import anthropic

from ..models import EngineResult, Review, Usage
from ..prompts import render
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

DIFF_REFERENCE = "the unified diff inside the <diff> element of the user message"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000


class ApiEngine:
    name = "api"

    def __init__(self, client: Any | None = None) -> None:
        # Any: tests pass a stub with the same `beta.messages.parse` shape.
        self._client = client

    def review(self, request: ReviewRequest) -> EngineResult:
        model = request.check.model
        fallback = model in FALLBACK_MODELS
        started = time.monotonic()
        try:
            # Creating the client already fails without credentials (no ANTHROPIC_API_KEY).
            client = self._client or anthropic.Anthropic()
            response = client.beta.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                system=render(request.prompt, DIFF_REFERENCE),
                messages=[
                    {
                        "role": "user",
                        "content": f'<diff base="{request.diff.base}">\n'
                        f"{request.diff.text}\n</diff>",
                    }
                ],
                output_format=Review,
                betas=[FALLBACK_BETA] if fallback else anthropic.omit,
                fallbacks="default" if fallback else anthropic.omit,
            )
        except anthropic.APIStatusError as error:
            raise EngineError(f"Claude API error {error.status_code}: {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise EngineError(f"cannot reach the Claude API: {error}") from error
        except anthropic.AnthropicError as error:  # e.g. no credentials configured
            raise EngineError(f"Claude API client error: {error}") from error
        duration_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise EngineError(f"the model declined to review (category: {category})")
        if response.stop_reason == "max_tokens":
            raise EngineError(f"the review was cut off at max_tokens={MAX_TOKENS}")
        review = response.parsed_output
        if not isinstance(review, Review):
            stop = response.stop_reason
            raise EngineError(f"no structured review in the response (stop reason: {stop})")

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
