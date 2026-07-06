import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

function read(relativePath) {
  return readFileSync(path.join(root, relativePath), "utf8");
}

const checks = [
  {
    file: "mr-backend/worker/prompts/builder.py",
    forbidden: [
      "_compact_text(skill_summary, 5000)",
      "_compact_json_value(agent.get(\"bound_rules\") or [], text_limit=500, list_limit=18)"
    ],
    required: [
      "\"dedicated_markdown_standard\": _compact_text(skill_summary, None)",
      "\"bound_markdown_rules\": _compact_json_value(agent.get(\"bound_rules\") or [], text_limit=None, list_limit=None)"
    ]
  },
  {
    file: "mr-backend/worker/rules/markdown_rule_parser.py",
    forbidden: [
      "_compact(check, 900)",
      "_compact(required_evidence, 400)",
      "_compact(positive_examples, 700)",
      "_compact(negative_examples, 700)",
      "_compact(false_positive_patterns, 700)",
      "_compact(fix_guidance, 700)",
      "return compacted[:limit]"
    ],
    required: [
      "def _compact(text: str) -> str:",
      "return re.sub"
    ]
  },
  {
    file: "mr-backend/worker/review_runtime.py",
    forbidden: [
      "reference_chunks =",
      "for asset in reference_chunks:",
      "reference_chunks[:5]",
      "str(asset[\"content\"])[:3000]",
      "custom_text[:12000]",
      "return text[:12000]"
    ],
    required: [
      "readable_assets = [asset for asset in assets if str(asset.get(\"asset_path\") or \"\")]",
      "## Skill Bundle 完整文件内容",
      "for asset in readable_assets:",
      "return custom_text if custom_text else",
      "return text"
    ]
  },
  {
    file: "mr-backend/worker/orchestration/nodes/route_agents.py",
    forbidden: [
      "def _augment_agents_from_bound_rules_and_skills(",
      "router_bound_config_experts_appended",
      "bound_config_augmented_agents"
    ],
    required: [
      "route_agents(",
      "_augment_agents_from_tool_observations("
    ]
  },
  {
    file: "mr-backend/worker/orchestration/nodes/run_experts.py",
    forbidden: [],
    required: [
      "def _bound_rule_batches(agent_context: dict[str, Any])",
      "\"bound_rules\": [rule]",
      "\"bound_skill_batch\": {",
      "\"enforce_skill_scope\": True",
      "\"skill_checkpoints\": [checkpoint]",
      "parse_skill_checkpoints(",
      "def _enforce_bound_batch_findings(batch: dict[str, Any], items: list[dict[str, Any]])",
      "def _audit_bound_evidence_contract(finding: dict[str, Any], contract_source: dict[str, Any], expected_id: str)",
      "bound_evidence_contract",
      "bound_false_positive_pattern_match",
      "bound_required_evidence_incomplete",
      "def _summarize_bound_review_coverage(records: list[dict[str, Any]])",
      "def _coverage_retry_batch(batch: dict[str, Any], *, reason: str)",
      "bound_rule_coverage_low",
      "bound_rule_coverage_retry_completed",
      "bound_review_coverage_summarized",
      "\"bound_review_coverage\": bound_review_coverage",
      "bound_batch_findings_rejected",
      "bound_skill_checkpoint_mismatch",
      "bound_rule_mismatch",
      "bound_skill_started",
      "bound_skill_checked",
      "batch_skill_summary = load_skill_summary(str(batch[\"skill_key\"]), files)",
      "\"purpose\": \"free_review_after_all_bound_rules\"",
      "def _has_required_bound_review(agent_context: dict[str, Any])",
      "if effort == \"trivial\" and not _has_required_bound_review(agent_context):",
      "\"checked\": True",
      "bound_rule_batch_started",
      "bound_rule_checked",
      "expert_free_review_started"
    ]
  },
  {
    file: "mr-backend/worker/prompts/builder.py",
    forbidden: [],
    required: [
      "bound_rule_batch = agent.get(\"bound_rule_batch\") if isinstance(agent.get(\"bound_rule_batch\"), dict) else {}",
      "bound_skill_batch = agent.get(\"bound_skill_batch\") if isinstance(agent.get(\"bound_skill_batch\"), dict) else {}",
      "\"bound_rule_batch\": _compact_json_value(bound_rule_batch, text_limit=None, list_limit=None)",
      "\"bound_skill_batch\": _compact_json_value(bound_skill_batch, text_limit=None, list_limit=None)",
      "\"coverage_retry\": coverage_retry",
      "\"skill_checkpoints\": _compact_json_value(agent.get(\"skill_checkpoints\") or [], text_limit=None, list_limit=None)",
      "\"bound_skill_review_contract\": {",
      "禁止执行专家自由检视",
      "必须只检查当前 checkpoint",
      "如果 coverage_retry.enabled=true"
    ]
  },
  {
    file: "mr-backend/worker/orchestration/nodes/judge_findings.py",
    forbidden: [],
    required: [
      "\"bound_evidence_contract\": finding.get(\"bound_evidence_contract\") or {}"
    ]
  },
  {
    file: "mr-backend/worker/orchestration/deepagents_runner.py",
    forbidden: [
      "(skill_summary or \"no bound markdown rules\")[:4000]",
      "item[\"content\"][:8000]"
    ],
    required: [
      "return skill_summary or \"no bound markdown rules\"",
      "return item[\"content\"]"
    ]
  }
];

const failures = [];
for (const check of checks) {
  const source = read(check.file);
  for (const pattern of check.forbidden) {
    if (source.includes(pattern)) failures.push({ file: check.file, forbidden: pattern });
  }
  for (const pattern of check.required) {
    if (!source.includes(pattern)) failures.push({ file: check.file, missing: pattern });
  }
}

if (failures.length) {
  throw new Error(`bound rule/skill full-read verification failed:\n${JSON.stringify(failures, null, 2)}`);
}

console.log(JSON.stringify({ ok: true, files: checks.length }, null, 2));
