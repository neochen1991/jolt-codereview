export type LocationFinding = {
  severity: string;
  file_path: string;
  line_start?: number | null;
  line_end?: number | null;
  title: string;
  problem_description: string;
  recommendation: string;
  suggested_code?: string | null;
};

export type FindingLocationGroup<T extends LocationFinding> = {
  key: string;
  location: string;
  findings: T[];
};

export function findingLocation(finding: LocationFinding) {
  if (!finding.line_start) return finding.file_path;
  if (finding.line_end && finding.line_end !== finding.line_start) {
    return `${finding.file_path}:${finding.line_start}-${finding.line_end}`;
  }
  return `${finding.file_path}:${finding.line_start}`;
}

export function groupFindingsByLocation<T extends LocationFinding>(findings: T[]): FindingLocationGroup<T>[] {
  const groups = new Map<string, FindingLocationGroup<T>>();
  for (const finding of findings) {
    const location = findingLocation(finding);
    const existing = groups.get(location);
    if (existing) existing.findings.push(finding);
    else groups.set(location, { key: location, location, findings: [finding] });
  }
  return [...groups.values()];
}

export function formatLocationGroupBody<T extends LocationFinding>(
  findings: T[],
  provider = "github",
  appendSuggestedCode?: (lines: string[], finding: T, provider: string) => void
) {
  const lines: string[] = [];
  for (const group of groupFindingsByLocation(findings)) {
    lines.push(`- 位置：${group.location}`);
    for (const [index, finding] of group.findings.entries()) {
      lines.push(`  ${index + 1}. [${finding.severity}] ${finding.title}`);
      lines.push(`     - 说明：${finding.problem_description}`);
      lines.push(`     - 建议：${finding.recommendation}`);
      if (appendSuggestedCode) {
        appendSuggestedCode(lines, finding, provider);
      } else if (String(finding.suggested_code ?? "").trim()) {
        lines.push("     - 建议修改代码：");
        lines.push("```");
        lines.push(String(finding.suggested_code).trim());
        lines.push("```");
      }
    }
  }
  return lines.join("\n");
}
