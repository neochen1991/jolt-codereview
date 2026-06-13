import type { AppConfig } from "../types.js";

export const DEFAULT_MAX_ADDED_LINES_PER_MR = 2000;

export interface MrSizePolicyDecision {
  allowed: boolean;
  addedLines: number;
  maxAddedLines: number;
}

function numberValue(value: unknown): number {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

function parseMetadata(value: unknown): Record<string, unknown> {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  try {
    const parsed = JSON.parse(String(value));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

export function maxAddedLinesPerMr(config?: AppConfig): number {
  const configured = numberValue(config?.review_policy?.max_added_lines_per_mr);
  return configured > 0 ? Math.floor(configured) : DEFAULT_MAX_ADDED_LINES_PER_MR;
}

export function mergeRequestAdditions(input: Record<string, unknown>): number {
  const direct = numberValue(input.additions);
  if (direct > 0 || input.additions !== undefined) return direct;
  const metadata = parseMetadata(input.metadata ?? input.metadata_json);
  return numberValue(metadata.additions ?? metadata.added_lines ?? metadata.addedLines);
}

function countPatchAdditions(value: unknown): number {
  const patch = String(value ?? "");
  if (!patch) return 0;
  return patch
    .split(/\r?\n/)
    .filter((line) => line.startsWith("+") && !line.startsWith("+++"))
    .length;
}

export function changedFileAdditions(input: unknown): number {
  if (!Array.isArray(input)) return 0;
  return input.reduce((total, row) => {
    if (!row || typeof row !== "object" || Array.isArray(row)) return total;
    const item = row as Record<string, unknown>;
    const direct = numberValue(item.additions ?? item.added_lines ?? item.addedLines);
    const patchAdded = countPatchAdditions(item.patch ?? item.diff);
    return total + Math.max(direct, patchAdded);
  }, 0);
}

export function evaluateMrSizePolicy(input: Record<string, unknown>, config?: AppConfig): MrSizePolicyDecision {
  const addedLines = mergeRequestAdditions(input);
  const maxAddedLines = maxAddedLinesPerMr(config);
  return {
    allowed: addedLines <= maxAddedLines,
    addedLines,
    maxAddedLines
  };
}

export function evaluateMrSizePolicyWithFiles(input: Record<string, unknown>, files: unknown[], config?: AppConfig): MrSizePolicyDecision {
  const metadataAddedLines = mergeRequestAdditions(input);
  const fileAddedLines = changedFileAdditions(files);
  const maxAddedLines = maxAddedLinesPerMr(config);
  const addedLines = Math.max(metadataAddedLines, fileAddedLines);
  return {
    allowed: addedLines <= maxAddedLines,
    addedLines,
    maxAddedLines
  };
}

export function mrSizeBlockedMessage(decision: MrSizePolicyDecision): string {
  return `该 MR 过大，新增代码行数 ${decision.addedLines} 行超过项目配置阈值 ${decision.maxAddedLines} 行，已停止检视。`;
}
