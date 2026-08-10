from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from llm.client import build_chat_payload, estimate_tokens, http_json, invoke_with_parameter_fallback, llm_request_timeout_seconds, llm_stream_enabled, request_options_for_payload
from llm.retry import call_with_retry
from llm.exchange import execute_chat_exchange, invoke_openai_chat, replay_mode_from_config
from context.semantic_graph import SemanticGraph
from context.source_tools import FrozenSourceTools


def deepagent_request_payload(
    *,
    provider: str,
    model: str,
    llm_config: dict[str, Any],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    seed: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, metadata = build_chat_payload(
        provider=provider,
        model=model,
        llm=llm_config,
        messages=messages,
        temperature=0.1,
        seed=seed,
        structured=False,
    )
    if (
        metadata["model_family"] == "glm"
        and isinstance(payload.get("thinking"), dict)
        and payload["thinking"].get("type") == "enabled"
    ):
        payload["thinking"] = {**payload["thinking"], "clear_thinking": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload, metadata


class OpenAICompatibleToolChatModel(BaseChatModel):
    provider: str
    model_name: str
    base_url: str
    api_key: str
    request_timeout_seconds: int = 120
    enable_stream: bool = True
    bound_tools: list[dict[str, Any]] = []
    trace_callback: Callable[[dict[str, Any]], None] | None = None
    exchange_recorder: Any = None
    head_sha: str = ""
    agent_id: str = "deepagent"
    replay_mode: str = "record"
    exchange_span_id: str = "deepagent"
    llm_config: dict[str, Any] = {}

    @property
    def _llm_type(self) -> str:
        return f"jolt_openai_compatible_tool_chat:{self.provider}"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"provider": self.provider, "model_name": self.model_name, "base_url": self.base_url}

    def bind_tools(self, tools: Any, **kwargs: Any) -> "OpenAICompatibleToolChatModel":
        schemas = [convert_to_openai_tool(tool) for tool in (tools or [])]
        return self.model_copy(update={"bound_tools": schemas})

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        openai_messages = [_message_to_openai(message) for message in messages]
        payload, _metadata = deepagent_request_payload(
            provider=self.provider,
            model=self.model_name,
            llm_config=self.llm_config,
            messages=openai_messages,
            tools=self.bound_tools,
            seed=None,
        )
        started = time.time()
        prompt_text = json.dumps(openai_messages, ensure_ascii=False)
        prompt_tokens = estimate_tokens(prompt_text)
        try:
            def execute_request(seed: int) -> dict[str, Any]:
                request_payload, _request_metadata = deepagent_request_payload(
                    provider=self.provider,
                    model=self.model_name,
                    llm_config=self.llm_config,
                    messages=openai_messages,
                    tools=self.bound_tools,
                    seed=seed,
                )
                return invoke_with_parameter_fallback(
                    request_payload,
                    lambda active: invoke_openai_chat(
                        base_url=self.base_url,
                        api_key=self.api_key,
                        payload=active,
                        timeout_seconds=self.request_timeout_seconds,
                        stream=self.enable_stream,
                        transport=http_json,
                        retry=call_with_retry,
                    ),
                )

            if self.exchange_recorder is None:
                raise RuntimeError("DeepAgent model calls require an LLM Exchange recorder")
            exchange = execute_chat_exchange(
                recorder=self.exchange_recorder,
                span_id=self.exchange_span_id,
                operation="deepagent_turn",
                agent_id=self.agent_id,
                context_unit_id="",
                checkpoint_id="",
                head_sha=self.head_sha,
                provider=self.provider,
                model=self.model_name,
                prompt=prompt_text,
                messages=payload["messages"],
                temperature=0.1,
                replay_mode=self.replay_mode,
                invoke=execute_request,
                request_options=request_options_for_payload(payload),
            )
            data = exchange.response
        except Exception as exc:
            self._trace_llm_call(
                {
                    "prompt": prompt_text,
                    "request_messages": payload["messages"],
                    "status": f"failed:{type(exc).__name__}",
                    "duration_ms": int((time.time() - started) * 1000),
                    "input_tokens": prompt_tokens,
                    "output_tokens": 0,
                    "request_id": None,
                    "response_text": json.dumps({"error": str(exc), "timeout_seconds": self.request_timeout_seconds, "stream": self.enable_stream}, ensure_ascii=False),
                }
            )
            raise
        raw_message = (data.get("choices") or [{}])[0].get("message") or {}
        usage = data.get("usage") or {}
        response_text = json.dumps(
            {
                "message": raw_message,
                "usage": usage,
                "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
                "stream": data.get("_jolt_stream") or {"enabled": False},
            },
            ensure_ascii=False,
        )
        tool_calls = []
        for call in raw_message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": function.get("name"), "args": args, "id": call.get("id")})
        additional_kwargs = {}
        if raw_message.get("reasoning_content"):
            additional_kwargs["reasoning_content"] = raw_message.get("reasoning_content")
        message = AIMessage(content=raw_message.get("content") or "", tool_calls=tool_calls, additional_kwargs=additional_kwargs)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _trace_llm_call(self, fields: dict[str, Any]) -> None:
        if not self.trace_callback:
            return
        try:
            self.trace_callback(
                {
                    "provider": self.provider,
                    "model": self.model_name,
                    **fields,
                }
            )
        except Exception:
            return


def run_bounded_deepagent(
    *,
    agent: dict[str, Any],
    files: list[Any],
    skill_summary: str,
    tool_observations: list[dict[str, Any]],
    llm_config: dict[str, Any],
    max_tool_calls: int = 12,
    llm_trace: Callable[[dict[str, Any]], None] | None = None,
    source_worktree_path: str | None = None,
    head_sha: str = "",
    semantic_graph: SemanticGraph | None = None,
    exchange_recorder: Any = None,
    exchange_span_id: str = "deepagent",
) -> dict[str, Any]:
    agent_id = str(agent.get("agent_id") or "unknown_agent")
    applies_to = agent.get("applies_to") or {}
    bounded_max = max(1, min(max_tool_calls, 24))
    provider = str(llm_config.get("default_provider") or "dashscope-openai-compatible")
    model_name = str(llm_config.get("default_model") or "MiniMax-M2.7")
    base_url = str(llm_config.get("default_base_url") or "").rstrip("/")
    api_key = str(llm_config.get("default_api_key") or "").strip()
    key_env = llm_config.get("default_api_key_env")
    if not api_key and key_env:
        api_key = os.environ.get(str(key_env)) or ""
    if not base_url or not api_key:
        raise RuntimeError("DeepAgents requires a real OpenAI-compatible base_url and api_key")
    request_timeout_seconds = llm_request_timeout_seconds(llm_config, "deepagents")
    enable_stream = llm_stream_enabled(llm_config)

    def inspect_agent_rules() -> str:
        """Read the actual markdown/code-rule summary bound to this expert agent."""
        return skill_summary or "no bound markdown rules"

    def inspect_static_observations() -> str:
        """Read actual static-analysis observations produced earlier in this review run."""
        related = [
            item for item in tool_observations
            if str(item.get("adopted_by_agent") or item.get("agent_id") or agent_id) in {agent_id, "unknown_agent", ""}
        ]
        return json.dumps(related[:30], ensure_ascii=False)

    def inspect_diff_summary() -> str:
        """Read actual changed-file statistics from this MR."""
        compact = []
        for changed in files[:30]:
            compact.append(
                {
                    "file": getattr(changed, "filename", ""),
                    "status": getattr(changed, "status", ""),
                    "additions": getattr(changed, "additions", 0),
                    "deletions": getattr(changed, "deletions", 0),
                }
            )
        return json.dumps(compact, ensure_ascii=False)

    def _normalize_review_path(path: str) -> str:
        return str(path or "").strip().replace("\\", "/").lstrip("/")

    def _changed_file_by_path(path: str) -> Any | None:
        normalized = _normalize_review_path(path)
        if not normalized or ".." in normalized.split("/"):
            return None
        candidates = {_normalize_review_path(getattr(changed, "filename", "")): changed for changed in files}
        if normalized in candidates:
            return candidates[normalized]
        basename_matches = [changed for name, changed in candidates.items() if name.endswith(f"/{normalized}") or name.rsplit("/", 1)[-1] == normalized]
        return basename_matches[0] if len(basename_matches) == 1 else None

    frozen_source_tools: FrozenSourceTools | None = None
    if source_worktree_path and head_sha:
        try:
            frozen_source_tools = FrozenSourceTools(
                Path(source_worktree_path),
                head_sha=head_sha,
                semantic_graph=semantic_graph or SemanticGraph.empty(),
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            frozen_source_tools = None

    def read_file(path: str) -> str:
        """Read frozen head-SHA source when available, otherwise return the changed-file patch."""
        if frozen_source_tools is not None:
            try:
                return frozen_source_tools.read_source_range(_normalize_review_path(path), 1, 400)
            except ValueError:
                pass
        changed = _changed_file_by_path(path)
        if changed is None:
            return f"changed file not found: {_normalize_review_path(path)}"
        return json.dumps(
            {
                "file": getattr(changed, "filename", ""),
                "status": getattr(changed, "status", ""),
                "additions": getattr(changed, "additions", 0),
                "deletions": getattr(changed, "deletions", 0),
                "patch": str(getattr(changed, "patch", "") or "")[:12000],
            },
            ensure_ascii=False,
        )

    def read_diff_patch(path: str) -> str:
        """Read only the unified diff patch for a real MR changed file."""
        changed = _changed_file_by_path(path)
        if changed is None:
            return f"changed file not found: {_normalize_review_path(path)}"
        return str(getattr(changed, "patch", "") or "")[:12000]

    def read_source_range(path: str, line_start: int, line_end: int) -> str:
        """Read an audited line range from the immutable head-SHA worktree."""
        if frozen_source_tools is None:
            return "full source unavailable: review is running in patch-only mode"
        try:
            return frozen_source_tools.read_source_range(_normalize_review_path(path), line_start, line_end)
        except ValueError as exc:
            return str(exc)

    def find_symbol(name: str) -> str:
        """Find semantic symbol definitions in the frozen repository graph."""
        return json.dumps(frozen_source_tools.find_symbol(name) if frozen_source_tools else [], ensure_ascii=False)

    def find_callers(name: str) -> str:
        """Find audited callers and their typed/syntax/heuristic confidence."""
        return json.dumps(frozen_source_tools.find_callers(name) if frozen_source_tools else [], ensure_ascii=False)

    def find_implementations(name: str) -> str:
        """Find explicit implementations of an interface or class."""
        return json.dumps(frozen_source_tools.find_implementations(name) if frozen_source_tools else [], ensure_ascii=False)

    def find_tests(name: str) -> str:
        """Find repository test nodes associated with a symbol name."""
        return json.dumps(frozen_source_tools.find_tests(name) if frozen_source_tools else [], ensure_ascii=False)

    def find_config_refs(name: str) -> str:
        """Find semantic configuration references associated with a symbol or key."""
        return json.dumps(frozen_source_tools.find_config_refs(name) if frozen_source_tools else [], ensure_ascii=False)

    skill_assets = [
        {
            "skill_key": str(item.get("skill_key") or ""),
            "asset_path": str(item.get("asset_path") or ""),
            "asset_type": str(item.get("asset_type") or "reference"),
            "content": str(item.get("content") or ""),
            "executable": bool(item.get("executable")),
        }
        for item in (agent.get("skill_assets") or [])
        if isinstance(item, dict)
    ]

    def list_skill_assets() -> str:
        """List references/scripts/assets from standard project custom skill bundles bound to this expert."""
        return json.dumps(
            [
                {
                    "skill_key": item["skill_key"],
                    "asset_path": item["asset_path"],
                    "asset_type": item["asset_type"],
                    "executable": item["executable"],
                }
                for item in skill_assets
            ],
            ensure_ascii=False,
        )

    def read_skill_asset(asset_path: str) -> str:
        """Read one bound standard skill asset by path, for example references/rules.md or scripts/check.py."""
        normalized = str(asset_path or "").strip().replace("\\", "/").lstrip("/")
        if ".." in normalized:
            return "asset_path rejected"
        for item in skill_assets:
            if item["asset_path"] == normalized:
                return item["content"]
        return f"skill asset not found: {normalized}"

    def run_skill_script(script_path: str, input_json: str = "{}") -> str:
        """Declare an intent to run a skill script; execution is blocked unless a sandboxed runner is enabled by policy."""
        normalized = str(script_path or "").strip().replace("\\", "/").lstrip("/")
        if ".." in normalized:
            return "script_path rejected"
        for item in skill_assets:
            if item["asset_path"] == normalized and item["asset_type"] == "script":
                return json.dumps(
                    {
                        "status": "blocked_by_policy",
                        "reason": "uploaded skill scripts are available as standard skill resources, but direct execution requires a sandboxed script runner policy",
                        "script_path": normalized,
                        "input_json": input_json[:1000],
                    },
                    ensure_ascii=False,
                )
        return f"skill script not found: {normalized}"

    tools = [
        inspect_agent_rules,
        inspect_static_observations,
        inspect_diff_summary,
        read_file,
        read_diff_patch,
        read_source_range,
        find_symbol,
        find_callers,
        find_implementations,
        find_tests,
        find_config_refs,
        list_skill_assets,
        read_skill_asset,
        run_skill_script,
    ]
    skill_asset_paths = [item["asset_path"] for item in skill_assets]
    graph = create_deep_agent(
        model=OpenAICompatibleToolChatModel(
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            api_key=str(api_key),
            request_timeout_seconds=request_timeout_seconds,
            enable_stream=enable_stream,
            trace_callback=llm_trace,
            exchange_recorder=exchange_recorder,
            head_sha=head_sha,
            agent_id=agent_id,
            replay_mode=replay_mode_from_config(llm_config),
            exchange_span_id=exchange_span_id,
            llm_config=llm_config,
        ),
        tools=tools,
        system_prompt=(
            "你是 Jolt CodeReview 的受控 DeepAgents 子图。"
            "必须先调用平台只读工具读取真实规则、真实静态扫描观察和真实 diff 摘要；"
            "需要查看具体代码时优先调用 read_source_range 读取冻结 head SHA 的完整源码；"
            "跨文件结论必须使用 find_callers/find_implementations/find_tests/find_config_refs 获取带可信度的语义证据；"
            "read_diff_patch 只用于确认实际变更行；"
            "如果存在项目自定义标准 Skill bundle，必须优先调用 list_skill_assets/read_skill_asset 读取 references 或 scripts；"
            "规则来源优先级固定为 Skill > 绑定规范 > 专家画像；"
            "读取 Skill 后必须在摘要中保留 Skill 中定义的原始 rule_id/checkpoint_id；"
            "后续 finding 的 covered_rules、skipped_rules、rule_id 必须使用 Skill 原始规则 ID，不得改写成绑定规范、专家画像或通用规则 ID；"
            "run_skill_script 默认只记录意图，不执行未沙箱化脚本；"
            "不启用 sub-agent，不直接伪造 finding。"
        ),
        subagents=[],
        name=f"jolt_{agent_id}_deepagent",
    )
    result = graph.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "agent_id": agent_id,
                            "persona": applies_to.get("persona"),
                            "exclusive_scope": applies_to.get("exclusive_scope"),
                            "review_scope": applies_to.get("review_scope"),
                            "bound_custom_skills": agent.get("custom_skills") or [],
                            "skill_asset_paths": skill_asset_paths,
                            "task": "必须调用工具做真实上下文读取，然后输出上下文摘要。",
                            "skill_task": (
                                "如果 skill_asset_paths 非空，必须先调用 list_skill_assets，"
                                "再调用 read_skill_asset 读取 SKILL.md 和 references/ 下的规范资料；"
                                "摘要必须保留 Skill 中定义的原始 rule_id/checkpoint_id；"
                                "covered_rules、skipped_rules、rule_id 必须使用 Skill 原始规则 ID，不能替换成其他规则 ID；"
                                "如果 Skill、绑定规范、专家画像描述同一问题，优先级按 Skill > 绑定规范 > 专家画像；"
                                "scripts/ 下资源只能通过 run_skill_script 记录受控调用意图。"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    )
    messages = result.get("messages") or []
    tool_calls = []
    for message in messages:
        if message.__class__.__name__ == "ToolMessage":
            tool_calls.append(
                {
                    "tool_name": getattr(message, "name", None) or "unknown_tool",
                    "content": str(getattr(message, "content", ""))[:1000],
                }
            )
    if not tool_calls:
        raise RuntimeError("DeepAgents completed without real tool calls")
    final_content = ""
    for message in reversed(messages):
        if message.__class__.__name__ == "AIMessage" and getattr(message, "content", ""):
            final_content = str(getattr(message, "content", ""))
            break
    return {
        "content": final_content,
        "tool_calls": tool_calls[:bounded_max],
        "message_count": len(messages),
        "sub_agents": "disabled",
        "max_tool_calls": bounded_max,
        "provider": provider,
        "model": model_name,
    }


def _message_to_openai(message: BaseMessage) -> dict[str, Any]:
    role_by_type = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    role = role_by_type.get(message.type, message.type)
    item: dict[str, Any] = {"role": role, "content": message.content or ""}
    if message.type == "tool":
        item["tool_call_id"] = getattr(message, "tool_call_id", "")
    if message.type == "ai" and getattr(message, "tool_calls", None):
        item["tool_calls"] = [
            {
                "id": call.get("id"),
                "type": "function",
                "function": {"name": call.get("name"), "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False)},
            }
            for call in message.tool_calls
        ]
    if message.type == "ai":
        reasoning_content = (getattr(message, "additional_kwargs", {}) or {}).get("reasoning_content")
        if reasoning_content:
            item["reasoning_content"] = reasoning_content
    return item
