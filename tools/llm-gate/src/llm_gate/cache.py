"""Skip the API call when the same check, engine, model, prompt and diff were reviewed before."""

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from pydantic import ValidationError

from .models import EngineResult

# Bump when something outside the key changes in a way that makes old entries wrong. "2": the
# agent engine's reads are fenced to the checkout (F003), so a cached review from before the fence
# was taken with tools this one doesn't have. "3": `shape` joined the key (F139), so entries from
# before it were taken under settings nothing recorded.
CACHE_VERSION = "3"


def cache_key(
    check: str,
    engine: str,
    model: str,
    prompt: str,
    diff: str,
    shape: Mapping[str, object] = MappingProxyType({}),
) -> str:
    """The inputs a review depends on. `shape` is the engine's own `request_shape`: the limits,
    tool lists and output schema that decide what it asks for.

    Leaving those out made the cache lie about the one thing it is used to measure. `llm-eval`
    scores the PR's gate against a committed baseline, and its keys differ only by case and
    repeat, so a PR that halved `max_turns`, emptied the read-only tool list or changed the
    output schema -- and touched no prompt -- hit every stored entry and reproduced the baseline
    exactly (F012, F139). The gate was weakest for precisely the changes most worth scoring.
    """
    material = json.dumps(
        [CACHE_VERSION, check, engine, model, prompt, diff, dict(sorted(shape.items()))],
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> EngineResult | None:
        path = self._path(key)
        try:
            return EngineResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except OSError, ValidationError:
            return None  # unreadable or stale entry: treat as a miss and overwrite it

    def put(self, key: str, result: EngineResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(result.model_dump_json(indent=2), encoding="utf-8")
