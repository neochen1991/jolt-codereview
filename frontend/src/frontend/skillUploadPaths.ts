export type SkillUploadFile = {
  name: string;
  webkitRelativePath?: string;
};

const SCRIPT_EXTENSIONS = new Set([
  ".bash",
  ".bat",
  ".cjs",
  ".cmd",
  ".js",
  ".mjs",
  ".ps1",
  ".py",
  ".sh",
  ".ts"
]);

function extensionOf(path: string) {
  const name = path.split("/").pop() || path;
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function canonicalSkillSegment(segment: string) {
  const lower = segment.toLowerCase();
  if (lower === "skill.md") return "SKILL.md";
  if (lower === "references") return "references";
  if (lower === "scripts") return "scripts";
  if (lower === "assets") return "assets";
  return segment;
}

function fallbackFlatSkillAssetPath(path: string) {
  const segments = path.split("/").filter(Boolean);
  const filename = segments.at(-1) || path;
  if (filename.toLowerCase() === "skill.md") return "SKILL.md";
  const extension = extensionOf(filename);
  if (SCRIPT_EXTENSIONS.has(extension)) return `scripts/${filename}`;
  if (extension === ".md" || extension === ".mdx" || extension === ".txt") return `references/${filename}`;
  return `assets/${filename}`;
}

export function cleanUploadPath(value: string) {
  return value.trim().replace(/\\/g, "/").replace(/^\/+/, "").replace(/\/+/g, "/");
}

export function uploadRelativePath(file: SkillUploadFile) {
  return cleanUploadPath(file.webkitRelativePath || file.name);
}

export function normalizeSkillBundleAssetPath(file: SkillUploadFile) {
  const rawPath = uploadRelativePath(file);
  const segments = rawPath.split("/").filter(Boolean).map(canonicalSkillSegment);
  const standardIndex = segments.findIndex((segment) => (
    segment === "SKILL.md" ||
    segment === "references" ||
    segment === "scripts" ||
    segment === "assets"
  ));
  if (standardIndex >= 0) return segments.slice(standardIndex).join("/");
  if (segments.length > 1) return segments.slice(1).join("/");
  return fallbackFlatSkillAssetPath(rawPath);
}

export function isStandardSkillAssetPath(path: string) {
  const normalized = cleanUploadPath(path);
  return normalized === "SKILL.md" ||
    normalized.startsWith("references/") ||
    normalized.startsWith("scripts/") ||
    normalized.startsWith("assets/");
}

export function skillRootNameFromFiles(files: SkillUploadFile[]) {
  const firstPath = files.map(uploadRelativePath).find((path) => path.includes("/"));
  return firstPath ? firstPath.split("/")[0] : "";
}
