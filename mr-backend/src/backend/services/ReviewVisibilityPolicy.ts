export type ReviewDetailVisibility = "full" | "findings_only";

export function reviewDetailVisibility(projectRole: unknown, isRoot: boolean): ReviewDetailVisibility {
  if (isRoot) return "full";
  return projectRole === "project_admin" || projectRole === "system_admin" ? "full" : "findings_only";
}
