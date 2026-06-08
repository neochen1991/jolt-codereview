import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const REPO_ID = "repo_github_java_complex_10file";
const MR_ID = "mr_repo_github_java_complex_10file_9301";
const MR_NUMBER = 9301;
const FIXTURE_DIR = path.join(root, "data", "fixtures", "java-complex-10file-mr");

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

const files = [
  fixtureFile("src/main/java/com/acme/payment/api/PaymentAdminController.java", [
    "package com.acme.payment.api;",
    "",
    "import com.acme.payment.service.PaymentQueryService;",
    "import jakarta.validation.Valid;",
    "import java.util.HashMap;",
    "import java.util.Map;",
    "import org.springframework.web.bind.annotation.PostMapping;",
    "import org.springframework.web.bind.annotation.RequestBody;",
    "import org.springframework.web.bind.annotation.RequestMapping;",
    "import org.springframework.web.bind.annotation.RestController;",
    "",
    "@RestController",
    "@RequestMapping(\"/admin/payments\")",
    "public class PaymentAdminController {",
    "    private final PaymentQueryService paymentQueryService;",
    "",
    "    public PaymentAdminController(PaymentQueryService paymentQueryService) {",
    "        this.paymentQueryService = paymentQueryService;",
    "    }",
    "",
    "    @PostMapping(\"/search\")",
    "    public Map<String, Object> search(@RequestBody Map<String, Object> payload) {",
    "        String userId = String.valueOf(payload.get(\"userId\"));",
    "        Map<String, Object> response = new HashMap<>();",
    "        response.put(\"items\", paymentQueryService.searchByUser(userId));",
    "        response.put(\"requestUser\", userId);",
    "        return response;",
    "    }",
    "",
    "    @PostMapping(\"/audit\")",
    "    public Map<String, Object> audit(@Valid @RequestBody AuditRequest request) {",
    "        return Map.of(\"status\", \"accepted\", \"operator\", request.operator());",
    "    }",
    "",
    "    public record AuditRequest(String operator, String reason) {}",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/payment/service/PaymentQueryService.java", [
    "package com.acme.payment.service;",
    "",
    "import java.math.BigDecimal;",
    "import java.sql.Connection;",
    "import java.sql.ResultSet;",
    "import java.sql.Statement;",
    "import java.util.ArrayList;",
    "import java.util.List;",
    "import javax.sql.DataSource;",
    "import org.springframework.stereotype.Service;",
    "",
    "@Service",
    "public class PaymentQueryService {",
    "    private final DataSource dataSource;",
    "",
    "    public PaymentQueryService(DataSource dataSource) {",
    "        this.dataSource = dataSource;",
    "    }",
    "",
    "    public List<PaymentView> searchByUser(String userId) {",
    "        List<PaymentView> result = new ArrayList<>();",
    "        String sql = \"select id, order_no, amount from payments where user_id = '\" + userId + \"' order by created_at desc\";",
    "        try (Connection connection = dataSource.getConnection();",
    "             Statement statement = connection.createStatement();",
    "             ResultSet rs = statement.executeQuery(sql)) {",
    "            while (rs.next()) {",
    "                result.add(new PaymentView(rs.getLong(\"id\"), rs.getString(\"order_no\"), rs.getBigDecimal(\"amount\")));",
    "            }",
    "        } catch (Exception ex) {",
    "            throw new IllegalStateException(\"payment query failed\", ex);",
    "        }",
    "        return result;",
    "    }",
    "",
    "    public record PaymentView(long id, String orderNo, BigDecimal amount) {}",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/payment/infra/RedisPaymentCache.java", [
    "package com.acme.payment.infra;",
    "",
    "import java.util.Set;",
    "import org.springframework.data.redis.core.RedisTemplate;",
    "import org.springframework.stereotype.Component;",
    "",
    "@Component",
    "public class RedisPaymentCache {",
    "    private final RedisTemplate<String, Object> redisTemplate;",
    "",
    "    public RedisPaymentCache(RedisTemplate<String, Object> redisTemplate) {",
    "        this.redisTemplate = redisTemplate;",
    "    }",
    "",
    "    public void clearProcessingPayments() {",
    "        Set<String> keys = redisTemplate.keys(\"payment:*:processing\");",
    "        if (keys != null && !keys.isEmpty()) {",
    "            redisTemplate.delete(keys);",
    "        }",
    "    }",
    "",
    "    public void cacheLastPayment(String orderNo, Object value) {",
    "        redisTemplate.opsForValue().set(\"payment:last:\" + orderNo, value);",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/payment/domain/PaymentAggregate.java", [
    "package com.acme.payment.domain;",
    "",
    "import java.math.BigDecimal;",
    "import java.util.HashMap;",
    "import java.util.Map;",
    "",
    "public class PaymentAggregate {",
    "    private Long id;",
    "    private String orderNo;",
    "    private BigDecimal amount;",
    "    private PaymentStatus status;",
    "    private Map<String, Object> extensionAttributes = new HashMap<>();",
    "",
    "    public void markPaid(String channel, Map<String, Object> attributes) {",
    "        this.status = PaymentStatus.PAID;",
    "        this.extensionAttributes.put(\"channel\", channel);",
    "        this.extensionAttributes.putAll(attributes);",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/payment/domain/PaymentStatus.java", [
    "package com.acme.payment.domain;",
    "",
    "public enum PaymentStatus {",
    "    INIT,",
    "    PROCESSING,",
    "    PAID,",
    "    FAILED",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/payment/infra/PaymentRepository.java", [
    "package com.acme.payment.infra;",
    "",
    "import com.acme.payment.domain.PaymentAggregate;",
    "import java.util.Optional;",
    "import org.springframework.stereotype.Repository;",
    "",
    "@Repository",
    "public interface PaymentRepository {",
    "    Optional<PaymentAggregate> findByOrderNo(String orderNo);",
    "    void save(PaymentAggregate payment);",
    "}",
  ]),
  fixtureFile("src/test/java/com/acme/payment/service/PaymentQueryServiceTest.java", [
    "package com.acme.payment.service;",
    "",
    "import static org.assertj.core.api.Assertions.assertThat;",
    "",
    "import org.junit.jupiter.api.Test;",
    "",
    "class PaymentQueryServiceTest {",
    "    @Test",
    "    void keepsFixtureVisibleForMrReview() {",
    "        assertThat(\"payment\").startsWith(\"pay\");",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/resources/application-prod.yml", [
    "spring:",
    "  application:",
    "    name: payment-service",
    "  datasource:",
    "    url: jdbc:mysql://mysql.internal/payment",
    "    username: payment_app",
    "    password: paymentRoot123",
    "payment:",
    "  callback:",
    "    endpoint: https://pay.example.com/callback",
  ]),
  fixtureFile("src/main/resources/db/migration/V20260607__complex_payment.sql", [
    "ALTER TABLE payments ADD COLUMN settlement_channel VARCHAR(32);",
    "ALTER TABLE payments DROP COLUMN legacy_channel;",
    "CREATE INDEX idx_payments_order_no ON payments(order_no);",
  ]),
  fixtureFile("pom.xml", [
    "<project xmlns=\"http://maven.apache.org/POM/4.0.0\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"",
    "  xsi:schemaLocation=\"http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd\">",
    "  <modelVersion>4.0.0</modelVersion>",
    "  <groupId>com.acme</groupId>",
    "  <artifactId>payment-service</artifactId>",
    "  <version>1.0.0</version>",
    "  <properties>",
    "    <java.version>17</java.version>",
    "  </properties>",
    "  <dependencies>",
    "    <dependency>",
    "      <groupId>org.springframework.boot</groupId>",
    "      <artifactId>spring-boot-starter-web</artifactId>",
    "      <version>3.2.5</version>",
    "    </dependency>",
    "    <dependency>",
    "      <groupId>com.alibaba</groupId>",
    "      <artifactId>fastjson</artifactId>",
    "      <version>1.2.47</version>",
    "    </dependency>",
    "    <dependency>",
    "      <groupId>org.junit.jupiter</groupId>",
    "      <artifactId>junit-jupiter</artifactId>",
    "      <version>5.10.2</version>",
    "      <scope>test</scope>",
    "    </dependency>",
    "  </dependencies>",
    "</project>",
  ]),
];

const expectedIssues = [
  {
    rule_id: "BE-API-001",
    title: "接口 RequestBody 缺少 @Valid",
    file_path: "src/main/java/com/acme/payment/api/PaymentAdminController.java",
    line_start: 22,
    category: "backend_api",
  },
  {
    rule_id: "CODE-NULL-001",
    title: "String.valueOf 可能把缺失字段转成字符串 null",
    file_path: "src/main/java/com/acme/payment/api/PaymentAdminController.java",
    line_start: 23,
    category: "coding",
  },
  {
    rule_id: "SEC-INJECT-003",
    title: "SQL 使用字符串拼接存在注入风险",
    file_path: "src/main/java/com/acme/payment/service/PaymentQueryService.java",
    line_start: 22,
    category: "security_sql",
  },
  {
    rule_id: "PERF-QUERY-001",
    title: "查询缺少分页或 limit 容易产生大结果集",
    file_path: "src/main/java/com/acme/payment/service/PaymentQueryService.java",
    line_start: 22,
    category: "performance_sql",
  },
  {
    rule_id: "REDIS-CMD-003",
    title: "生产路径使用 Redis KEYS 命令",
    file_path: "src/main/java/com/acme/payment/infra/RedisPaymentCache.java",
    line_start: 16,
    category: "redis",
  },
  {
    rule_id: "REDIS-TTL-002",
    title: "Redis 缓存写入缺少 TTL",
    file_path: "src/main/java/com/acme/payment/infra/RedisPaymentCache.java",
    line_start: 23,
    category: "redis",
  },
  {
    rule_id: "DDD-VO-002",
    title: "聚合根使用 Map<String,Object> 表达领域属性",
    file_path: "src/main/java/com/acme/payment/domain/PaymentAggregate.java",
    line_start: 12,
    category: "ddd",
  },
  {
    rule_id: "SEC-SECRET-004",
    title: "生产配置包含明文数据库密码",
    file_path: "src/main/resources/application-prod.yml",
    line_start: 7,
    category: "secret",
  },
  {
    rule_id: "DB-DDL-001",
    title: "迁移脚本直接 DROP COLUMN 存在兼容风险",
    file_path: "src/main/resources/db/migration/V20260607__complex_payment.sql",
    line_start: 2,
    category: "database",
  },
  {
    rule_id: "DEP-CVE-001",
    title: "fastjson 1.2.47 存在已知高危漏洞",
    file_path: "pom.xml",
    line_start: 17,
    category: "dependency_vulnerability",
  },
];

function writeFixtureFiles() {
  mkdirSync(FIXTURE_DIR, { recursive: true });
  const fixturePath = path.join(FIXTURE_DIR, "github-java-complex-10file-mr-files.json");
  const localRepoDir = path.join(FIXTURE_DIR, "payment-complex-repo");
  const fixtureFiles = files.map(({ source, ...item }) => item);
  writeFileSync(fixturePath, JSON.stringify(fixtureFiles, null, 2), "utf8");
  writeFileSync(path.join(FIXTURE_DIR, "expected-issues.json"), JSON.stringify(expectedIssues, null, 2), "utf8");
  for (const file of files) {
    const target = path.join(localRepoDir, file.filename);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, file.source, "utf8");
  }
  return { fixturePath, localRepoDir };
}

function seed() {
  const { fixturePath, localRepoDir } = writeFixtureFiles();
  const headSha = `java_complex_10file_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "java-complex-payment-service",
    token_env: "GITHUB_TOKEN",
    git_url: "https://github.com/jolt-fixture/java-complex-payment-service.git",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  const db = new DatabaseSync(dbPath());
  db.exec("PRAGMA foreign_keys = ON");
  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-fixture/java-complex-payment-service', 'java-complex-payment-service', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(REPO_ID, PROJECT_ID, JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, ?, ?, '复杂支付项目 MR：10 文件 10 个预埋问题', 'java-eval-user', 'feature/complex-payment-risk', 'main',
      'queued', 99, ?, 'https://github.com/jolt-fixture/java-complex-payment-service/pull/9301', ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      title = excluded.title,
      review_status = 'queued',
      risk_score = excluded.risk_score,
      latest_head_sha = excluded.latest_head_sha,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    MR_ID,
    REPO_ID,
    String(MR_NUMBER),
    MR_NUMBER,
    headSha,
    JSON.stringify({
      provider: "github",
      fixture: true,
      language: "java",
      eval_repo_kind: "springboot-payment-complex-10file",
      local_repo_path: path.relative(root, localRepoDir),
      fixture_changed_files: path.relative(root, fixturePath),
      expected_issues: expectedIssues.map((item) => item.rule_id),
      expected_issue_details: expectedIssues,
    })
  );

  db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'")
    .run(MR_ID);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 5000, 'standard')
  `).run(jobId, MR_ID, headSha);
  db.close();

  return {
    repoId: REPO_ID,
    mrId: MR_ID,
    jobId,
    headSha,
    expectedCount: expectedIssues.length,
    fixturePath,
    localRepoDir,
  };
}

console.log(JSON.stringify(seed(), null, 2));
