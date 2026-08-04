from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mr-backend" / "worker"))

from llm.client import build_chat_payload, chat_completions_url, http_json, invoke_with_parameter_fallback, llm_stream_enabled  # noqa: E402
from llm.retry import call_with_retry  # noqa: E402


def main() -> None:
    config_path = Path(os.environ.get("COMMON_CONFIG_PATH") or ROOT / "common-backend" / "config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    llm = config.get("llm") or {}
    api_key = llm.get("default_api_key") or os.environ.get(str(llm.get("default_api_key_env") or ""))
    if not api_key:
        raise RuntimeError("LLM API key is not configured")
    provider = str(llm.get("default_provider") or "")
    model = str(llm.get("default_model") or "")
    messages = [
        {"role": "system", "content": '你是代码检视专家，只输出 JSON 对象 {"findings": [...]}。'},
        {"role": "user", "content": '这是一次协议烟测，没有代码缺陷。返回 {"findings": []}。'},
    ]
    payload, metadata = build_chat_payload(
        provider=provider,
        model=model,
        llm=llm,
        messages=messages,
        temperature=0.0,
        seed=13,
        structured=True,
        max_tokens=min(4096, int(llm.get("max_output_tokens") or 8192)),
    )
    downgraded: list[str] = []
    response = invoke_with_parameter_fallback(
        payload,
        lambda active: call_with_retry(
            lambda: http_json(
                chat_completions_url(str(llm.get("default_base_url") or "")),
                {"Authorization": f"Bearer {api_key}"},
                method="POST",
                body=active,
                timeout_seconds=int(llm.get("request_timeout_seconds") or 120),
                stream=llm_stream_enabled(llm),
            )
        ),
        on_downgrade=downgraded.append,
    )
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = str(message.get("content") or "")
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        raise RuntimeError("adapted model response does not contain findings array")
    print(json.dumps({
        "ok": True,
        "provider": provider,
        "model": model,
        "model_capabilities": metadata,
        "finish_reason": choice.get("finish_reason"),
        "reasoning_content_chars": len(str(message.get("reasoning_content") or "")),
        "usage": response.get("usage") or {},
        "downgraded_parameters": downgraded,
        "finding_count": len(parsed["findings"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
