import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";

function id(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function javaPatch() {
  const lines = [
    "package com.acme.payment;",
    "",
    "import java.sql.Connection;",
    "import java.sql.ResultSet;",
    "import java.sql.Statement;",
    "import java.util.HashMap;",
    "import java.util.Map;",
    "import org.springframework.beans.factory.annotation.Autowired;",
    "import org.springframework.data.redis.core.RedisTemplate;",
    "import org.springframework.web.bind.annotation.PostMapping;",
    "import org.springframework.web.bind.annotation.RequestBody;",
    "import org.springframework.web.bind.annotation.RestController;",
    "",
    "@RestController",
    "public class PaymentController {",
    "    private static final String ADMIN_PASSWORD = \"admin123456\";",
    "    private final Connection connection;",
    "    private final RedisTemplate<String, Object> redisTemplate;",
    "    @Autowired",
    "    private PaymentAuditService auditService;",
    "",
    "    public PaymentController(Connection connection, RedisTemplate<String, Object> redisTemplate) {",
    "        this.connection = connection;",
    "        this.redisTemplate = redisTemplate;",
    "    }",
    "",
    "    @PostMapping(\"/api/payments/search\")",
    "    public Map<String, Object> search(@RequestBody Map<String, Object> payload) {",
    "        String userId = String.valueOf(payload.get(\"userId\"));",
    "        Map<String, Object> response = new HashMap<>();",
    "        try {",
    "            Statement statement = connection.createStatement();",
    "            ResultSet rs = statement.executeQuery(\"select * from payments where user_id = '\" + userId + \"'\");",
    "            while (rs.next()) {",
    "                response.put(rs.getString(\"id\"), rs.getBigDecimal(\"amount\"));",
    "            }",
    "            redisTemplate.keys(\"payment:*:lock\").forEach(redisTemplate::delete);",
    "            redisTemplate.opsForValue().set(\"payment:last:\" + userId, response);",
    "            auditService.recordSearch(userId, response);",
    "            if (String.valueOf(payload.get(\"password\")).equals(ADMIN_PASSWORD)) {",
    "                response.put(\"admin\", true);",
    "            }",
    "        } catch (Exception e) {",
    "            response.put(\"error\", e.getMessage());",
    "        }",
    "        return response;",
    "    }",
    "}",
    "",
    "class PaymentAggregate {",
    "    private Map<String, Object> json = new HashMap<>();",
    "    public void update(Map<String, Object> payload) {",
    "        this.json.putAll(payload);",
    "        if (payload.containsKey(\"status\")) {",
    "            this.json.put(\"status\", payload.get(\"status\"));",
    "        }",
    "    }",
    "}",
  ];
  while (lines.length < 92) {
    lines.push(`// TODO generated branch scenario ${lines.length}`);
  }
  return "@@ -0,0 +1," + lines.length + " @@\n" + lines.map((line) => `+${line}`).join("\n") + "\n";
}

function pomPatch() {
  const lines = [
    "<project>",
    "  <modelVersion>4.0.0</modelVersion>",
    "  <groupId>com.acme</groupId>",
    "  <artifactId>payment-service</artifactId>",
    "  <version>1.0.0</version>",
    "  <dependencies>",
    "    <dependency>",
    "      <groupId>com.alibaba</groupId>",
    "      <artifactId>fastjson</artifactId>",
    "      <version>1.2.47</version>",
    "    </dependency>",
    "    <dependency>",
    "      <groupId>org.junit.jupiter</groupId>",
    "      <artifactId>junit-jupiter</artifactId>",
    "      <version>5.10.0</version>",
    "    </dependency>",
    "  </dependencies>",
    "</project>"
  ];
  return "@@ -0,0 +1," + lines.length + " @@\n" + lines.map((line) => `+${line}`).join("\n") + "\n";
}

function configPatch() {
  const lines = [
    "spring:",
    "  datasource:",
    "    url: jdbc:mysql://db/payment",
    "    password: paymentRoot123",
    "management:",
    "  endpoints:",
    "    web:",
    "      exposure:",
    "        include: \"*\""
  ];
  return "@@ -0,0 +1," + lines.length + " @@\n" + lines.map((line) => `+${line}`).join("\n") + "\n";
}

function migrationPatch() {
  const lines = [
    "ALTER TABLE payments ADD COLUMN channel VARCHAR(32) NOT NULL;",
    "ALTER TABLE payments DROP COLUMN legacy_remark;"
  ];
  return "@@ -0,0 +1," + lines.length + " @@\n" + lines.map((line) => `+${line}`).join("\n") + "\n";
}

function seedJavaReview() {
  const fixtureDir = path.join(root, "data", "fixtures");
  mkdirSync(fixtureDir, { recursive: true });
  const localRepoDir = path.join(fixtureDir, "java-risky-service-repo");
  mkdirSync(path.join(localRepoDir, "src", "main", "java", "com", "acme", "payment"), { recursive: true });
  mkdirSync(path.join(localRepoDir, "src", "main", "resources", "db", "migration"), { recursive: true });
  const fixturePath = path.join(fixtureDir, "github-java-risky-pr-files.json");
  const fixtureFiles = [
    {
      filename: "src/main/java/com/acme/payment/PaymentController.java",
      status: "modified",
      additions: 92,
      deletions: 0,
      changes: 92,
      patch: javaPatch(),
    },
    {
      filename: "pom.xml",
      status: "modified",
      additions: 18,
      deletions: 0,
      changes: 18,
      patch: pomPatch(),
    },
    {
      filename: "src/main/resources/application-prod.yml",
      status: "modified",
      additions: 9,
      deletions: 0,
      changes: 9,
      patch: configPatch(),
    },
    {
      filename: "src/main/resources/db/migration/V20260607__payment_schema.sql",
      status: "modified",
      additions: 2,
      deletions: 0,
      changes: 2,
      patch: migrationPatch(),
    },
  ];
  writeFileSync(fixturePath, JSON.stringify(fixtureFiles, null, 2), "utf8");
  writeFileSync(path.join(localRepoDir, "src", "main", "java", "com", "acme", "payment", "PaymentController.java"), javaPatch().split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++")).map((line) => line.slice(1)).join("\n"), "utf8");
  writeFileSync(path.join(localRepoDir, "pom.xml"), pomPatch().split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++")).map((line) => line.slice(1)).join("\n"), "utf8");
  writeFileSync(path.join(localRepoDir, "src", "main", "resources", "application-prod.yml"), configPatch().split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++")).map((line) => line.slice(1)).join("\n"), "utf8");
  writeFileSync(path.join(localRepoDir, "src", "main", "resources", "db", "migration", "V20260607__payment_schema.sql"), migrationPatch().split("\n").filter((line) => line.startsWith("+") && !line.startsWith("+++")).map((line) => line.slice(1)).join("\n"), "utf8");

  const db = new DatabaseSync(dbPath());
  const repoId = "repo_github_java_fixture";
  const mrId = `mr_${repoId}_9101`;
  const headSha = `java_fixture_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "java-risky-service",
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-fixture/java-risky-service', 'java-risky-service', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(repoId, PROJECT_ID, JSON.stringify(providerConfig));

  const expectedIssues = [
    "SEC-SECRET-004",
    "JOLT_JAVA_FIELD_AUTOWIRED",
    "BE-API-001",
    "SEC-INJECT-003",
    "REDIS-CMD-003",
    "REDIS-TTL-002",
    "PERF-QUERY-001",
    "PERF-MEM-004",
    "CODE-EXC-003",
    "CODE-NULL-001",
    "CODE-RESOURCE-005",
    "SEC-SECRET-004:ERROR_RESPONSE",
    "DDD-VO-002",
    "BE-IDEMP-004",
    "DEP-CVE-001",
    "DEP-SCOPE-005",
    "SEC-CONFIG-007",
    "DB-NOTNULL-002",
    "DB-DDL-001",
    "TEST-COVER-001"
  ];

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, '9101', 9101, 'Java MR with 10+ security backend dependency DB issues', 'java-fixture-user', 'feature/java-risky-payment', 'main',
      'queued', 98, ?, 'https://github.com/jolt-fixture/java-risky-service/pull/9101', ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      review_status = 'queued',
      risk_score = excluded.risk_score,
      latest_head_sha = excluded.latest_head_sha,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    mrId,
    repoId,
    headSha,
    JSON.stringify({ provider: "github", fixture: true, language: "java", local_repo_path: path.relative(root, localRepoDir), additions: 121, deletions: 0, expected_issues: expectedIssues })
  );

  db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'")
    .run(mrId);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 1000, 'standard')
  `).run(jobId, mrId, headSha);
  db.close();
  return { mrId, jobId, headSha, fixturePath, localRepoDir, expectedCount: expectedIssues.length };
}

console.log(JSON.stringify(seedJavaReview(), null, 2));
