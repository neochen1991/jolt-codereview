import { createHash } from "node:crypto";

import type { Db } from "./connection.js";

const LOCAL_ADMIN_PASSWORD_SALT = "jolt-local-admin-dev-salt";
const LOCAL_ADMIN_PASSWORD_HASH = createHash("sha256")
  .update(`${LOCAL_ADMIN_PASSWORD_SALT}:admin123`)
  .digest("hex");

export function seed(db: Db) {
  db.prepare(`
    INSERT INTO users (id, username, display_name, email, password_hash, password_salt, global_role, status)
    VALUES ('user_local_admin', 'local-admin', '本机管理员', 'local@example.com', ?, ?, 'root', 'active')
    ON CONFLICT DO NOTHING
  `).run(LOCAL_ADMIN_PASSWORD_HASH, LOCAL_ADMIN_PASSWORD_SALT);
  db.prepare(`
    UPDATE users
    SET global_role = 'root',
        password_hash = CASE WHEN COALESCE(password_hash, '') = '' THEN ? ELSE password_hash END,
        password_salt = CASE WHEN COALESCE(password_salt, '') = '' THEN ? ELSE password_salt END
    WHERE id = 'user_local_admin'
  `).run(LOCAL_ADMIN_PASSWORD_HASH, LOCAL_ADMIN_PASSWORD_SALT);

  db.prepare(`
    INSERT INTO projects (id, name, description, data_policy_json)
    VALUES (
      'project_default',
      '默认项目',
      '本机调试项目',
      '{"prompt_retention":"hash_only","data_residency":"cn-north-1"}'
    )
    ON CONFLICT DO NOTHING
  `).run();

  db.prepare(`
    INSERT INTO project_members (id, project_id, user_id, role)
    VALUES ('member_local_admin', 'project_default', 'user_local_admin', 'project_admin')
    ON CONFLICT DO NOTHING
  `).run();
}
