import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const countArg = process.argv.find((arg) => arg.startsWith("--count="));
const scenarioCount = countArg ? Number(countArg.split("=")[1]) : undefined;

function id(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function patch(lines) {
  return `@@ -0,0 +1,${lines.length} @@\n${lines.map((line) => `+${line}`).join("\n")}\n`;
}

function sourceFromPatch(value) {
  return value
    .split("\n")
    .filter((line) => line.startsWith("+") && !line.startsWith("+++"))
    .map((line) => line.slice(1))
    .join("\n");
}

function fixtureFile(filename, lines) {
  const filePatch = patch(lines);
  return {
    filename,
    status: "modified",
    additions: lines.length,
    deletions: 0,
    changes: lines.length,
    patch: filePatch,
    source: sourceFromPatch(filePatch),
  };
}

const controllerLines = [
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
];

const dddLines = [
  "package com.acme.payment.domain;",
  "",
  "import java.util.HashMap;",
  "import java.util.Map;",
  "",
  "public class PaymentAggregate {",
  "    private Map<String, Object> json = new HashMap<>();",
  "    public void update(Map<String, Object> payload) {",
  "        this.json.putAll(payload);",
  "        if (payload.containsKey(\"status\")) {",
  "            this.json.put(\"status\", payload.get(\"status\"));",
  "        }",
  "    }",
  "}",
];

const scenarios = [
  {
    suffix: "9201",
    name: "java-controller-risk",
    title: "Controller security backend redis performance issues",
    files: [fixtureFile("src/main/java/com/acme/payment/PaymentController.java", controllerLines)],
    expected: [
      "SEC-SECRET-004",
      "JOLT_JAVA_FIELD_AUTOWIRED",
      "BE-API-001",
      "BE-IDEMP-004",
      "CODE-NULL-001",
      "SEC-INJECT-003",
      "PERF-QUERY-001",
      "PERF-MEM-004",
      "REDIS-CMD-003",
      "REDIS-TTL-002",
      "CODE-EXC-003",
      "CODE-RESOURCE-005",
      "SEC-SECRET-004:ERROR_RESPONSE",
      "TEST-COVER-001",
    ],
  },
  {
    suffix: "9202",
    name: "java-dependency-risk",
    title: "Dependency CVE and scope issues",
    files: [
      fixtureFile("pom.xml", [
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
        "</project>",
      ]),
    ],
    expected: ["DEP-CVE-001", "DEP-SCOPE-005"],
  },
  {
    suffix: "9203",
    name: "java-config-risk",
    title: "Spring production config exposure",
    files: [
      fixtureFile("src/main/resources/application-prod.yml", [
        "spring:",
        "  datasource:",
        "    url: jdbc:mysql://db/payment",
        "    password: paymentRoot123",
        "management:",
        "  endpoints:",
        "    web:",
        "      exposure:",
        "        include: \"*\"",
      ]),
    ],
    expected: ["SEC-SECRET-004", "SEC-CONFIG-007"],
  },
  {
    suffix: "9204",
    name: "java-db-migration-risk",
    title: "Database migration compatibility issues",
    files: [
      fixtureFile("src/main/resources/db/migration/V20260607__payment_schema.sql", [
        "ALTER TABLE payments ADD COLUMN channel VARCHAR(32) NOT NULL;",
        "ALTER TABLE payments DROP COLUMN legacy_remark;",
      ]),
    ],
    expected: ["DB-NOTNULL-002", "DB-DDL-001"],
  },
  {
    suffix: "9205",
    name: "java-ddd-risk",
    title: "DDD aggregate weak model issue",
    files: [fixtureFile("src/main/java/com/acme/payment/domain/PaymentAggregate.java", dddLines)],
    expected: ["DDD-VO-002", "TEST-COVER-001"],
  },
];

function writeScenarioFiles(fixtureDir, scenario) {
  const fixturePath = path.join(fixtureDir, `github-${scenario.name}-files.json`);
  const localRepoDir = path.join(fixtureDir, `${scenario.name}-repo`);
  const fixtureFiles = scenario.files.map(({ source, ...item }) => item);
  writeFileSync(fixturePath, JSON.stringify(fixtureFiles, null, 2), "utf8");
  for (const file of scenario.files) {
    const target = path.join(localRepoDir, file.filename);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, file.source, "utf8");
  }
  return { fixturePath, localRepoDir };
}

const fixtureDir = path.join(root, "data", "fixtures", "java-5mr");
mkdirSync(fixtureDir, { recursive: true });
const db = new DatabaseSync(dbPath());
db.exec("PRAGMA foreign_keys = ON");
const seeded = [];

for (const scenario of scenarios.slice(0, Number.isFinite(scenarioCount) ? scenarioCount : scenarios.length)) {
  const { fixturePath, localRepoDir } = writeScenarioFiles(fixtureDir, scenario);
  const repoId = `repo_github_${scenario.name}`;
  const mrId = `mr_${repoId}_${scenario.suffix}`;
  const jobId = id("job");
  const headSha = `java_5mr_${scenario.suffix}_${Date.now()}`;
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: scenario.name,
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', ?, ?, 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(repoId, PROJECT_ID, `jolt-fixture/${scenario.name}`, scenario.name, JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, ?, ?, ?, 'java-fixture-user', ?, 'main',
      'queued', 95, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      review_status = 'queued',
      risk_score = excluded.risk_score,
      latest_head_sha = excluded.latest_head_sha,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    mrId,
    repoId,
    scenario.suffix,
    Number(scenario.suffix),
    scenario.title,
    `feature/${scenario.name}`,
    headSha,
    `https://github.com/jolt-fixture/${scenario.name}/pull/${scenario.suffix}`,
    JSON.stringify({
      provider: "github",
      fixture: true,
      language: "java",
      local_repo_path: path.relative(root, localRepoDir),
      expected_issues: scenario.expected,
    })
  );

  db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'")
    .run(mrId);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 900, 'standard')
  `).run(jobId, mrId, headSha);
  seeded.push({ mrId, jobId, headSha, expectedCount: scenario.expected.length, fixturePath, localRepoDir });
}

db.close();
console.log(JSON.stringify({ count: seeded.length, mrIds: seeded.map((item) => item.mrId), seeded }, null, 2));
