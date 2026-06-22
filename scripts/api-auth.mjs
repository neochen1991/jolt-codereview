export const API = process.env.API_BASE || "http://127.0.0.1:8011";
export const COMMON_API = process.env.COMMON_API_BASE || API;
export const MR_API = process.env.MR_API_BASE || API;

const COMMON_PATH_PATTERNS = [
  /^\/api\/auth(?:\/|$)/,
  /^\/api\/me(?:\/|$)/,
  /^\/api\/users(?:\/|$)/,
  /^\/api\/permissions(?:\/|$)/,
  /^\/api\/models(?:\/|$)/,
  /^\/api\/system(?:\/|$)/,
  /^\/internal\/auth(?:\/|$)/,
  /^\/internal\/models(?:\/|$)/
];

export function apiBaseForPath(path) {
  return COMMON_PATH_PATTERNS.some((pattern) => pattern.test(path)) ? COMMON_API : MR_API;
}

let cachedToken = null;

export async function request(path, init = {}) {
  const response = await fetch(`${apiBaseForPath(path)}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {})
    }
  });
  const text = await response.text();
  const json = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${JSON.stringify(json)}`);
  }
  return json;
}

export async function loginToken() {
  if (cachedToken) return cachedToken;
  const username = process.env.JOLT_TEST_USERNAME || "local-admin";
  const password = process.env.JOLT_TEST_PASSWORD || process.env.JOLT_LOCAL_ADMIN_PASSWORD || "admin123";
  const login = await request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
  if (!login.token) throw new Error("login did not return token");
  cachedToken = login.token;
  return cachedToken;
}

export async function authHeaders() {
  const token = await loginToken();
  return { Authorization: `Bearer ${token}` };
}

export async function authenticatedRequest(path, init = {}) {
  return request(path, {
    ...init,
    headers: {
      ...(await authHeaders()),
      ...(init.headers || {})
    }
  });
}
