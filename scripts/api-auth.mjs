export const API = process.env.API_BASE || "http://127.0.0.1:8011";

let cachedToken = null;

export async function request(path, init = {}) {
  const response = await fetch(`${API}${path}`, {
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
