import { createHash } from "node:crypto";

export const SKILL_CHECKPOINT_MANIFEST_SCHEMA = "skill_checkpoint_manifest_v1";
export const SKILL_CHECKPOINT_COMPILER_VERSION = "1.1.0";

export type SkillCheckpointAsset = {
  asset_path: string;
  content: string;
};

export type SkillCheckpointDiagnostic = {
  level: "error" | "warning";
  code: string;
  message: string;
  source_path: string;
  line?: number;
  checkpoint_id?: string;
};

export type CompiledSkillCheckpoint = {
  skill_key: string;
  checkpoint_id: string;
  rule_id: string;
  title: string;
  severity: string;
  applies_to: string;
  check: string;
  required_evidence: string;
  evidence_required: string;
  false_positive_patterns: string;
  positive_examples: string;
  negative_examples: string;
  fix_guidance: string;
  evidence_scope: "symbol" | "cross_file";
  context_queries: string[];
  max_dependency_hops: number;
  source_path: string;
  source_heading: string;
  source_line_start: number;
  source_line_end: number;
  parse_quality: "structured" | "generated_id" | "table";
};

export type SkillCheckpointManifest = {
  schema_version: string;
  compiler_version: string;
  skill_key: string;
  source_hash: string;
  checkpoints: CompiledSkillCheckpoint[];
  diagnostics: SkillCheckpointDiagnostic[];
  ok: boolean;
};

const EXPLICIT_HEADING_RE = /^(#{2,4})\s+(?:checkpoint[:：]\s*)?([A-Za-z][A-Za-z0-9_.:-]*-[A-Za-z0-9_.:-]+)\s+(.+)$/i;
const GENERIC_HEADING_RE = /^(#{2,4})\s+(.+)$/;
const FIELD_RE = /^[-*]\s*([^:：]+)[:：]\s*(.*)$/;
const CONTAINER_NAMES = new Set(["checkpoint", "checkpoints", "检查点", "检查规则", "rules", "review rules"]);

const FIELD_ALIASES: Record<string, string> = {
  id: "checkpoint_id",
  checkpointid: "checkpoint_id",
  ruleid: "checkpoint_id",
  severity: "severity",
  严重级别: "severity",
  严重性: "severity",
  appliesto: "applies_to",
  scope: "applies_to",
  适用范围: "applies_to",
  适用路径: "applies_to",
  check: "check",
  howtocheck: "check",
  检查: "check",
  检查点: "check",
  如何检查: "check",
  检查要求: "check",
  requiredevidence: "required_evidence",
  evidencerequired: "required_evidence",
  证据要求: "required_evidence",
  输出要求: "required_evidence",
  falsepositivepatterns: "false_positive_patterns",
  falsepositives: "false_positive_patterns",
  误报模式: "false_positive_patterns",
  误报排除: "false_positive_patterns",
  例外: "false_positive_patterns",
  positiveexamples: "positive_examples",
  正例: "positive_examples",
  正确示例: "positive_examples",
  negativeexamples: "negative_examples",
  反例: "negative_examples",
  错误示例: "negative_examples",
  fixguidance: "fix_guidance",
  修复建议: "fix_guidance",
  整改建议: "fix_guidance",
  title: "title",
  标题: "title",
  evidencescope: "evidence_scope",
  证据范围: "evidence_scope",
  contextqueries: "context_queries",
  上下文查询: "context_queries",
  maxdependencyhops: "max_dependency_hops",
  最大依赖跳数: "max_dependency_hops"
};

function normalizeField(value: string) {
  const key = value.trim().toLowerCase().replace(/[\s_.-]+/g, "");
  return FIELD_ALIASES[key] || "";
}

function compact(value: unknown) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function stableGeneratedId(skillKey: string, sourcePath: string, title: string) {
  const prefix = skillKey.toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24) || "SKILL";
  const digest = createHash("sha1").update(`${skillKey}\u0000${sourcePath}\u0000${compact(title).toLowerCase()}`).digest("hex").slice(0, 10).toUpperCase();
  return `${prefix}-AUTO-${digest}`;
}

function sourceHash(assets: SkillCheckpointAsset[]) {
  const hash = createHash("sha256");
  for (const asset of [...assets].sort((a, b) => a.asset_path.localeCompare(b.asset_path))) {
    hash.update(asset.asset_path).update("\u0000").update(asset.content).update("\u0000");
  }
  return hash.digest("hex");
}

function splitTableRow(line: string) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => compact(cell));
}

function isSeparatorRow(cells: string[]) {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

type Draft = Record<string, string> & {
  source_path: string;
  source_heading: string;
  source_line_start: string;
  source_line_end: string;
  parse_quality: CompiledSkillCheckpoint["parse_quality"];
};

function checkpointFromDraft(skillKey: string, draft: Draft): CompiledSkillCheckpoint {
  const title = compact(draft.title || draft.source_heading);
  const checkpointId = compact(draft.checkpoint_id) || stableGeneratedId(skillKey, draft.source_path, title);
  const generated = !compact(draft.checkpoint_id);
  const contextQueries = compact(draft.context_queries)
    .replace(/^\[|\]$/g, "")
    .split(/[,，\s]+/)
    .map((item) => item.replace(/^[-*]\s*/, "").trim())
    .filter(Boolean);
  return {
    skill_key: skillKey,
    checkpoint_id: checkpointId,
    rule_id: checkpointId,
    title,
    severity: compact(draft.severity) || "medium",
    applies_to: compact(draft.applies_to) || "**/*",
    check: compact(draft.check),
    required_evidence: compact(draft.required_evidence),
    evidence_required: compact(draft.required_evidence),
    false_positive_patterns: compact(draft.false_positive_patterns),
    positive_examples: compact(draft.positive_examples),
    negative_examples: compact(draft.negative_examples),
    fix_guidance: compact(draft.fix_guidance),
    evidence_scope: (compact(draft.evidence_scope) || "symbol") as CompiledSkillCheckpoint["evidence_scope"],
    context_queries: contextQueries,
    max_dependency_hops: Number(compact(draft.max_dependency_hops) || 1),
    source_path: draft.source_path,
    source_heading: draft.source_heading,
    source_line_start: Number(draft.source_line_start || 1),
    source_line_end: Number(draft.source_line_end || draft.source_line_start || 1),
    parse_quality: generated ? "generated_id" : draft.parse_quality
  };
}

function parseAsset(skillKey: string, asset: SkillCheckpointAsset) {
  const lines = String(asset.content || "").split(/\r?\n/);
  const drafts: Draft[] = [];
  let current: Draft | null = null;
  let currentHeadingLevel = 0;
  let currentSectionKey = "";
  let containerLevel = 0;
  let fenced = false;

  const flush = (endLine: number) => {
    if (!current) return;
    current.source_line_end = String(Math.max(Number(current.source_line_start), endLine));
    drafts.push(current);
    current = null;
    currentHeadingLevel = 0;
    currentSectionKey = "";
  };

  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    const trimmed = raw.trim();
    if (/^(```|~~~)/.test(trimmed)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;

    if (trimmed.startsWith("|") && index + 1 < lines.length) {
      const headers = splitTableRow(trimmed).map(normalizeField);
      const separator = splitTableRow(lines[index + 1]);
      if (headers.includes("checkpoint_id") && headers.includes("check") && isSeparatorRow(separator)) {
        flush(index);
        index += 2;
        while (index < lines.length && lines[index].trim().startsWith("|")) {
          const cells = splitTableRow(lines[index]);
          const draft = {
            source_path: asset.asset_path,
            source_heading: compact(cells[headers.indexOf("title")] || cells[headers.indexOf("checkpoint_id")]),
            source_line_start: String(index + 1),
            source_line_end: String(index + 1),
            parse_quality: "table" as const
          } as Draft;
          headers.forEach((field, cellIndex) => {
            if (field && cells[cellIndex] !== undefined) draft[field] = cells[cellIndex];
          });
          drafts.push(draft);
          index += 1;
        }
        index -= 1;
        continue;
      }
    }

    const explicit = raw.match(EXPLICIT_HEADING_RE);
    if (explicit) {
      flush(index);
      current = {
        checkpoint_id: explicit[2].trim(),
        title: explicit[3].trim(),
        source_path: asset.asset_path,
        source_heading: explicit[3].trim(),
        source_line_start: String(index + 1),
        source_line_end: String(index + 1),
        parse_quality: "structured"
      } as Draft;
      currentHeadingLevel = explicit[1].length;
      currentSectionKey = "";
      continue;
    }

    const heading = raw.match(GENERIC_HEADING_RE);
    if (heading) {
      const level = heading[1].length;
      const title = heading[2].trim();
      const normalizedTitle = title.toLowerCase().replace(/[:：]$/, "");
      if (current && level > currentHeadingLevel) {
        const sectionKey = normalizeField(normalizedTitle);
        if (sectionKey && !["checkpoint_id", "title"].includes(sectionKey)) {
          currentSectionKey = sectionKey;
          continue;
        }
      }
      if (CONTAINER_NAMES.has(normalizedTitle)) {
        flush(index);
        containerLevel = level;
        continue;
      }
      if (containerLevel && level > containerLevel) {
        flush(index);
        current = {
          title,
          source_path: asset.asset_path,
          source_heading: title,
          source_line_start: String(index + 1),
          source_line_end: String(index + 1),
          parse_quality: "generated_id"
        } as Draft;
        currentHeadingLevel = level;
        currentSectionKey = "";
        continue;
      }
      if (containerLevel && level <= containerLevel) containerLevel = 0;
    }

    if (!current) continue;
    const field = trimmed.match(FIELD_RE);
    if (field) {
      const key = normalizeField(field[1]);
      if (key) {
        current[key] = field[2].trim();
        currentSectionKey = "";
      }
      continue;
    }
    if (currentSectionKey && trimmed) {
      const value = trimmed.replace(/^[-*]\s+/, "");
      current[currentSectionKey] = compact(`${current[currentSectionKey] || ""} ${value}`);
    }
  }
  flush(lines.length);
  return drafts.map((draft) => checkpointFromDraft(skillKey, draft));
}

export function compileSkillCheckpointManifest(skillKey: string, rawAssets: SkillCheckpointAsset[]): SkillCheckpointManifest {
  const assets = rawAssets
    .map((asset) => ({ asset_path: String(asset.asset_path || ""), content: String(asset.content || "") }))
    .filter((asset) => asset.asset_path && asset.content.trim());
  const checkpoints = assets.flatMap((asset) => parseAsset(skillKey, asset));
  const diagnostics: SkillCheckpointDiagnostic[] = [];
  const ids = new Map<string, CompiledSkillCheckpoint>();
  const requiredFields: Array<keyof CompiledSkillCheckpoint> = ["check", "required_evidence", "false_positive_patterns", "fix_guidance"];
  const allowedQueries = new Set(["callers", "callees", "implementations", "tests", "config_refs"]);
  for (const checkpoint of checkpoints) {
    const duplicate = ids.get(checkpoint.checkpoint_id);
    if (duplicate) {
      diagnostics.push({
        level: "error",
        code: "duplicate_checkpoint_id",
        message: `duplicate checkpoint_id: ${checkpoint.checkpoint_id}`,
        source_path: checkpoint.source_path,
        line: checkpoint.source_line_start,
        checkpoint_id: checkpoint.checkpoint_id
      });
    } else {
      ids.set(checkpoint.checkpoint_id, checkpoint);
    }
    for (const field of requiredFields) {
      if (!compact(checkpoint[field])) {
        diagnostics.push({
          level: "error",
          code: "missing_checkpoint_field",
          message: `checkpoint missing ${field}`,
          source_path: checkpoint.source_path,
          line: checkpoint.source_line_start,
          checkpoint_id: checkpoint.checkpoint_id
        });
      }
    }
    if (!['symbol', 'cross_file'].includes(checkpoint.evidence_scope)) {
      diagnostics.push({ level: "error", code: "invalid_evidence_scope", message: `unsupported evidence_scope: ${checkpoint.evidence_scope}`, source_path: checkpoint.source_path, line: checkpoint.source_line_start, checkpoint_id: checkpoint.checkpoint_id });
    }
    for (const query of checkpoint.context_queries) {
      if (!allowedQueries.has(query)) diagnostics.push({ level: "error", code: "invalid_context_query", message: `unsupported context query: ${query}`, source_path: checkpoint.source_path, line: checkpoint.source_line_start, checkpoint_id: checkpoint.checkpoint_id });
    }
    if (!Number.isInteger(checkpoint.max_dependency_hops) || checkpoint.max_dependency_hops < 1 || checkpoint.max_dependency_hops > 3) {
      diagnostics.push({ level: "error", code: "invalid_max_dependency_hops", message: `max_dependency_hops must be an integer between 1 and 3`, source_path: checkpoint.source_path, line: checkpoint.source_line_start, checkpoint_id: checkpoint.checkpoint_id });
    }
  }
  if (!checkpoints.length) {
    diagnostics.push({ level: "error", code: "no_checkpoints", message: "no checkpoints compiled", source_path: assets[0]?.asset_path || "SKILL.md" });
  }
  return {
    schema_version: SKILL_CHECKPOINT_MANIFEST_SCHEMA,
    compiler_version: SKILL_CHECKPOINT_COMPILER_VERSION,
    skill_key: skillKey,
    source_hash: sourceHash(assets),
    checkpoints,
    diagnostics,
    ok: diagnostics.every((item) => item.level !== "error")
  };
}
