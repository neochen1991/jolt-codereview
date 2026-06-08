from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from deepagents import create_deep_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


class OpenAICompatibleToolChatModel(BaseChatModel):
    provider: str
    model_name: str
    base_url: str
    api_key: str
    request_timeout_seconds: int = 120
    bound_tools: list[dict[str, Any]] = []

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
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [_message_to_openai(message) for message in messages],
            "temperature": 0.1,
        }
        if self.bound_tools:
            payload["tools"] = self.bound_tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.request_timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw_message = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = []
        for call in raw_message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments") or "{}"
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": function.get("name"), "args": args, "id": call.get("id")})
        message = AIMessage(content=raw_message.get("content") or "", tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])


def run_bounded_deepagent(
    *,
    agent: dict[str, Any],
    files: list[Any],
    skill_summary: str,
    tool_observations: list[dict[str, Any]],
    llm_config: dict[str, Any],
    max_tool_calls: int = 8,
) -> dict[str, Any]:
    agent_id = str(agent.get("agent_id") or "unknown_agent")
    applies_to = agent.get("applies_to") or {}
    bounded_max = max(1, min(max_tool_calls, 16))
    provider = str(llm_config.get("default_provider") or "dashscope-openai-compatible")
    model_name = str(llm_config.get("default_model") or "MiniMax-M2.7")
    base_url = str(llm_config.get("default_base_url") or "").rstrip("/")
    key_env = llm_config.get("default_api_key_env")
    api_key = os.environ.get(str(key_env)) if key_env else llm_config.get("default_api_key")
    if not base_url or not api_key:
        raise RuntimeError("DeepAgents requires a real OpenAI-compatible base_url and api_key")
    try:
        request_timeout_seconds = max(1, min(120, int(llm_config.get("request_timeout_seconds") or llm_config.get("timeout_seconds") or 120)))
    except (TypeError, ValueError):
        request_timeout_seconds = 120

    def inspect_agent_rules() -> str:
        """Read the actual markdown/code-rule summary bound to this expert agent."""
        return (skill_summary or "no bound markdown rules")[:4000]

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

    def read_file(path: str) -> str:
        """Read the real MR changed-file patch by repository-relative file path."""
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
                return item["content"][:8000]
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
        ),
        tools=tools,
        system_prompt=(
            "你是 Jolt CodeReview 的受控 DeepAgents 子图。"
            "必须先调用平台只读工具读取真实规则、真实静态扫描观察和真实 diff 摘要；"
            "需要查看具体代码时必须调用 read_file 或 read_diff_patch 读取真实 MR 变更 patch；"
            "如果存在项目自定义标准 Skill bundle，必须优先调用 list_skill_assets/read_skill_asset 读取 references 或 scripts；"
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
    return item
