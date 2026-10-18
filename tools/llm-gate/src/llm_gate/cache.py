"""Skip the API call when the same check, engine, model, prompt and diff were reviewed before."""

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from .models import EngineResult

# Bump when the Review schema or the engines' requests change in a way that makes old entries
# wrong. "2": the agent engine's reads are fenced to the checkout (F003), so a cached review from
# before the fence was taken with tools this one doesn't have.
CACHE_VERSION = "2"


def cache_key(check: str, engine: str, model: str, prompt: str, diff: str) -> str:
    material = json.dumps([CACHE_VERSION, check, engine, model, prompt, diff])
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
