export type ApiBaseConfig = {
  legacyBase?: string;
  commonBase?: string;
  mrBase?: string;
};

export const COMMON_API_PATH_PATTERNS = [
  /^\/api\/auth(?:\/|$)/,
  /^\/api\/me(?:\/|$)/,
  /^\/api\/users(?:\/|$)/,
  /^\/api\/permissions(?:\/|$)/,
  /^\/api\/models(?:\/|$)/,
  /^\/api\/system(?:\/|$)/,
  /^\/internal\/auth(?:\/|$)/,
  /^\/internal\/models(?:\/|$)/
];

function cleanBase(value?: string) {
  return String(value || "").replace(/\/+$/, "");
}

export function resolveApiBase(path: string, bases: ApiBaseConfig) {
  const legacyBase = cleanBase(bases.legacyBase) || "http://127.0.0.1:8011";
  const commonBase = cleanBase(bases.commonBase);
  const mrBase = cleanBase(bases.mrBase);
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  if (COMMON_API_PATH_PATTERNS.some((pattern) => pattern.test(normalizedPath))) {
    return commonBase || legacyBase;
  }
  return mrBase || legacyBase;
}
