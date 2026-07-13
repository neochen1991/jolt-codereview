const SENSITIVE_KEY = /(^|_)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|token)$/i;
const VALUE_PATTERNS: Array<[RegExp, string]> = [
  [/\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b/gi, "Bearer <redacted>"],
  [/\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b/g, "<redacted:github-token>"],
  [/(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,}]{8,}/gi, "$1=<redacted>"]
];

export class SensitiveDataRedactionService {
  redact(value: unknown, key = ""): unknown {
    if (SENSITIVE_KEY.test(key)) return "<redacted>";
    if (Array.isArray(value)) return value.map((item) => this.redact(item));
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([childKey, child]) => [childKey, this.redact(child, childKey)]));
    }
    if (typeof value !== "string") return value;
    return VALUE_PATTERNS.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value);
  }
}
