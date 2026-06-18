from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from llm.client import (  # noqa: E402
    LLM_REVIEW_SCHEMA_NAME,
    LLM_REVIEW_SEED,
    _read_cached_llm_response,
    _write_cached_llm_response,
    llm_cache_key,
    review_findings_response_format,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = {
            "server": {
                "database_driver": "sqlite",
                "database_path": str(Path(tmp) / "cache.sqlite"),
            },
            "llm": {},
        }
        prompt = "review prompt"
        key = llm_cache_key("provider", "model", prompt, seed=LLM_REVIEW_SEED, schema_name=LLM_REVIEW_SCHEMA_NAME)
        response = {
            "id": "cached-response",
            "choices": [{"message": {"content": "[]"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 2},
        }
        _write_cached_llm_response(
            config,
            cache_key=key,
            provider="provider",
            model="model",
            schema_name=LLM_REVIEW_SCHEMA_NAME,
            seed=LLM_REVIEW_SEED,
            prompt=prompt,
            response=response,
        )
        cached = _read_cached_llm_response(config, key)
        assert cached == response, cached
        response_format = review_findings_response_format()
        assert response_format["type"] == "json_schema", response_format
        assert response_format["json_schema"]["strict"] is True, response_format
        assert response_format["json_schema"]["name"] == LLM_REVIEW_SCHEMA_NAME, response_format
        assert LLM_REVIEW_SEED == 13
    print(json.dumps({"ok": True, "verified": "llm_response_cache"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
