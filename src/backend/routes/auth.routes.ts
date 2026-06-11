import { createHash, randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { badRequest, id, notFound, route, sha1, type Route } from "../http.js";
import type { FindingRow } from "../types.js";
import type { BackendRouteContext } from "./context.js";

type UserRow = {
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  global_role?: string;
  status: string;
  password_hash?: string;
  password_salt?: string;
};

function publicUser(user: UserRow | undefined | null) {
  if (!user) return null;
  return {
    id: user.id,
    username: user.username,
    display_name: user.display_name,
    email: user.email ?? null,
    global_role: user.global_role ?? "user",
    status: user.status
  };
}

function redactSecret(value: unknown) {
  const text = String(value ?? "");
  if (!text) return "";
  return `****${text.slice(-4)}`;
}

function redactUserSetting(key: string, value: Record<string, unknown>) {
  const next = { ...value };
  for (const secretKey of ["default_api_key", "github_token", "codehub_token"]) {
    if (typeof next[secretKey] === "string" && next[secretKey]) {
      next[`${secretKey}_masked`] = redactSecret(next[secretKey]);
      next[`${secretKey}_has_value`] = true;
      delete next[secretKey];
    }
  }
  return { key, value: next };
}

function compactUserSettingValue(value: Record<string, unknown>) {
  const next = { ...value };
  for (const secretKey of ["default_api_key", "github_token", "codehub_token"]) {
    if (typeof next[secretKey] === "string" && next[secretKey].trim() === "") {
      delete next[secretKey];
    }
  }
  return next;
}

function hashPassword(password: string, salt = randomBytes(16).toString("hex")) {
  const hash = scryptSync(password, salt, 64).toString("hex");
  return { salt, hash: `scrypt$${hash}` };
}

function verifyPassword(password: string, user: UserRow) {
  const stored = String(user.password_hash || "");
  const salt = String(user.password_salt || "");
  if (!stored || !salt) return false;
  if (stored.startsWith("scrypt$")) {
    const expected = Buffer.from(stored.slice("scrypt$".length), "hex");
    const actual = scryptSync(password, salt, expected.length);
    return expected.length === actual.length && timingSafeEqual(expected, actual);
  }
  return createHash("sha256").update(`${salt}:${password}`).digest("hex") === stored;
}

export function createAuthRoutes(ctx: BackendRouteContext): Route[] {
  const {
    all,
    get,
    db,
    config,
    runWorkerOnce,
    repoConfig,
    riskScore,
    verifyGitHubSignature,
    verifyCodeHubSignature,
    normalizeCodeHubWebhookPayload,
    codehubRepoMatches,
    bearerToken,
    currentUserId,
    ensureProjectRole,
    ensureProjectWrite,
    auditLog,
    syncProject,
    publishFindings,
    projectRepository,
    repositoryRepository,
    mergeRequestRepository,
    reviewJobRepository,
    agentRepository,
    ruleDocumentRepository,
    auditRepository
  } = ctx;
  const routes: Route[] = [
    route("POST", "/api/auth/login", ({ body }) => {
      const input = body as Record<string, unknown>;
      const username = String(input.username ?? "").trim();
      const password = String(input.password ?? "");
      if (!username || !password) return badRequest("username and password are required");
      const user = projectRepository.findActiveUserByUsername(username) as UserRow | undefined;
      if (!user || !verifyPassword(password, user)) {
        return { statusCode: 401, error: "invalid_credentials", message: "username or password is invalid" };
      }
      const token = randomBytes(32).toString("hex");
      projectRepository.createAuthSession(id("session"), user.id, sha1(token));
      projectRepository.markLogin(user.id);
      auditLog({ userId: user.id, action: "auth.login", resourceType: "user", resourceId: user.id, summary: `${username} logged in` });
      return { token, user: publicUser(user) };
    }),
    route("POST", "/api/auth/register", ({ body }) => {
      const input = body as Record<string, unknown>;
      const username = String(input.username ?? "").trim();
      const password = String(input.password ?? "");
      const displayName = String(input.display_name ?? username).trim() || username;
      const email = String(input.email ?? "").trim();
      if (!/^[a-zA-Z0-9_.-]{3,40}$/.test(username)) return badRequest("username must be 3-40 chars and contain only letters, numbers, dot, underscore or dash");
      if (password.length < 6) return badRequest("password must be at least 6 chars");
      if (projectRepository.findActiveUserByUsername(username)) return badRequest("username already exists");
      const userCount = Number((get<{ count: number }>("SELECT COUNT(*) AS count FROM users")?.count) ?? 0);
      const passwordDigest = hashPassword(password);
      const user = projectRepository.createUser({
        id: id("user"),
        username,
        displayName,
        email: email || null,
        passwordHash: passwordDigest.hash,
        passwordSalt: passwordDigest.salt,
        globalRole: userCount === 0 ? "root" : "user"
      }) as UserRow;
      auditLog({ userId: user.id, action: "auth.register", resourceType: "user", resourceId: user.id, summary: `${username} registered` });
      return { user: publicUser(user) };
    }),
    route("GET", "/api/auth/session", ({ req }) => {
      const userId = currentUserId(req);
      const user = projectRepository.findUserById(userId) as UserRow | undefined;
      return { user: publicUser(user), authenticated: Boolean(user) };
    }),
    route("POST", "/api/auth/logout", ({ req }) => {
      const token = bearerToken(req);
      if (token) {
        projectRepository.revokeSession(sha1(token));
      }
      auditLog({ userId: currentUserId(req), action: "auth.logout", resourceType: "session", summary: "session revoked" });
      return { ok: true };
    }),
    route("POST", "/api/auth/change-password", ({ body, req }) => {
      const userId = currentUserId(req);
      if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const user = projectRepository.findUserById(userId) as UserRow | undefined;
      if (!user || user.status !== "active") return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const input = body as Record<string, unknown>;
      const currentPassword = String(input.current_password ?? "");
      const newPassword = String(input.new_password ?? "");
      const confirmPassword = String(input.confirm_password ?? "");
      if (!currentPassword || !newPassword || !confirmPassword) return badRequest("current password, new password and confirmation are required");
      if (!verifyPassword(currentPassword, user)) {
        return { statusCode: 401, error: "invalid_current_password", message: "current password is invalid" };
      }
      if (newPassword.length < 6) return badRequest("new password must be at least 6 chars");
      if (newPassword !== confirmPassword) return badRequest("new password confirmation does not match");
      if (newPassword === currentPassword) return badRequest("new password must be different from current password");
      const passwordDigest = hashPassword(newPassword);
      projectRepository.updateUserPassword(user.id, passwordDigest.hash, passwordDigest.salt);
      auditLog({ userId: user.id, action: "auth.change_password", resourceType: "user", resourceId: user.id, summary: `${user.username} changed password` });
      return { ok: true };
    }),
    route("GET", "/api/me", ({ req }) => {
      const userId = currentUserId(req);
      if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const user = projectRepository.findUserById(userId) as UserRow | undefined;
      if (!user) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const projects = projectRepository.isRoot(userId) ? projectRepository.listProjects() : projectRepository.listProjectsForUser(userId);
      return { user: publicUser(user), projects };
    }),
    route("GET", "/api/me/settings", ({ req }) => {
      const userId = currentUserId(req);
      if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      const rows = projectRepository.listUserSettings(userId) as Array<{ settings_key: string; settings_json: string; updated_at: string }>;
      return {
        items: rows.map((row) => {
          const value = JSON.parse(row.settings_json || "{}") as Record<string, unknown>;
          return { ...redactUserSetting(row.settings_key, value), updated_at: row.updated_at };
        })
      };
    }),
    route("PATCH", "/api/me/settings/:key", ({ params, body, req }) => {
      const userId = currentUserId(req);
      if (!userId) return { statusCode: 401, error: "unauthorized", message: "login is required" };
      if (!["vcs_tokens", "preferences"].includes(params.key)) {
        return badRequest("settings key must be vcs_tokens or preferences");
      }
      const input = (body as Record<string, unknown> | undefined) ?? {};
      const nextInput = compactUserSettingValue((typeof input.value === "object" && input.value ? input.value : input) as Record<string, unknown>);
      const existingRow = (projectRepository.listUserSettings(userId) as Array<{ settings_key: string; settings_json: string }>)
        .find((item) => item.settings_key === params.key);
      const existingValue = existingRow ? JSON.parse(existingRow.settings_json || "{}") as Record<string, unknown> : {};
      const value = { ...existingValue, ...nextInput };
      const row = projectRepository.upsertUserSetting({
        id: id("user_setting"),
        userId,
        key: params.key,
        value
      }) as { key: string; settings_json: string; updated_at: string } | undefined;
      auditLog({ userId, action: "user.settings.update", resourceType: "user_settings", resourceId: params.key, summary: `updated ${params.key}` });
      if (!row) return notFound();
      return {
        ...redactUserSetting(row.key, JSON.parse(row.settings_json || "{}") as Record<string, unknown>),
        updated_at: row.updated_at
      };
    }),
  ];
  return routes;
}
