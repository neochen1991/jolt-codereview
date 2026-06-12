import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const systemRoutesModule = await import(pathToFileURL(path.join(root, "build/backend/routes/system.routes.js")));
const { effectivePostgresStorageInput, pgConnectionConfig } = systemRoutesModule;

function fakeContext({ saved = {}, server = {} } = {}) {
  return {
    config: { server },
    get() {
      return { settings_json: JSON.stringify(saved) };
    }
  };
}

const savedPasswordInput = effectivePostgresStorageInput(
  fakeContext({ saved: { postgres_password: "saved-secret" } }),
  {
    driver: "postgres",
    postgres_url: " postgresql://127.0.0.1:5432/app ",
    postgres_user: " app_user ",
    postgres_password: "",
    postgres_password_has_value: true,
    postgres_password_masked: "****cret"
  }
);
assert.equal(savedPasswordInput.postgres_password, "saved-secret");
assert.equal(savedPasswordInput.postgres_url, "postgresql://127.0.0.1:5432/app");
assert.equal(savedPasswordInput.postgres_user, "app_user");

const maskedPasswordInput = effectivePostgresStorageInput(
  fakeContext({ saved: { postgres_password: "saved-secret" } }),
  {
    driver: "postgres",
    postgres_url: "postgresql://127.0.0.1:5432/app",
    postgres_password: "****cret",
    postgres_password_has_value: true,
    postgres_password_masked: "****cret"
  }
);
assert.equal(maskedPasswordInput.postgres_password, "saved-secret");

const explicitPasswordInput = effectivePostgresStorageInput(
  fakeContext({ saved: { postgres_password: "saved-secret" } }),
  {
    driver: "postgres",
    postgres_url: "postgresql://127.0.0.1:5432/app",
    postgres_password: "new-secret"
  }
);
assert.equal(explicitPasswordInput.postgres_password, "new-secret");

const configPasswordInput = effectivePostgresStorageInput(
  fakeContext({ server: { postgres_password: "config-secret" } }),
  {
    driver: "postgres",
    postgres_url: "postgresql://127.0.0.1:5432/app",
    postgres_password: ""
  }
);
assert.equal(configPasswordInput.postgres_password, "config-secret");

assert.deepEqual(
  pgConnectionConfig({ postgres_url: "postgresql://127.0.0.1:5432/app", postgres_user: "app_user", postgres_password: 1234 }),
  { connectionString: "postgresql://127.0.0.1:5432/app", user: "app_user", password: "1234" }
);

console.log("PG storage setting password merge checks passed.");
