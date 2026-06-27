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
      "reference_chunks[:5]",
      "str(asset[\"content\"])[:3000]",
      "custom_text[:12000]",
      "return text[:12000]"
    ],
    required: [
      "for asset in reference_chunks:",
      "return custom_text if custom_text else",
      "return text"
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
