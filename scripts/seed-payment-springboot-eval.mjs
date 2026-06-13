import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const REPO_ID = "repo_github_payment_springboot_eval";
const MR_ID = `mr_${REPO_ID}_1001`;
const MR_NUMBER = 1001;

function id(prefix) {
  return `${prefix}_${randomUUID().replace(/-/g, "").slice(0, 16)}`;
}

function dbPath() {
  const config = loadConfig();
  return path.resolve(root, config.server?.database_path || "data/jolt-codereview.sqlite");
}

function addPatch(lines) {
  return `@@ -0,0 +1,${lines.length} @@\n${lines.map((line) => `+${line}`).join("\n")}\n`;
}

function modifiedPatch(startLine, lines) {
  return `@@ -${startLine},0 +${startLine},${lines.length} @@\n${lines.map((line) => `+${line}`).join("\n")}\n`;
}

function writeText(baseDir, filePath, content) {
  const target = path.join(baseDir, filePath);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, content.endsWith("\n") ? content : `${content}\n`, "utf8");
}

function linesToText(lines) {
  return `${lines.join("\n")}\n`;
}

const baselineFiles = {
  "README.md": `# Payment Spring Boot Service

评测用支付业务代码仓。main 快照保持相对健康，MR fixture 会在此基础上引入典型 Java Web 检视问题。
`,
  "pom.xml": `<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.jolt.eval</groupId>
  <artifactId>payment-springboot-service</artifactId>
  <version>1.0.0</version>
  <properties>
    <java.version>17</java.version>
    <spring-boot.version>3.2.5</spring-boot.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>\${spring-boot.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-validation</artifactId>
      <version>\${spring-boot.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
      <version>\${spring-boot.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-redis</artifactId>
      <version>\${spring-boot.version}</version>
    </dependency>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
`,
  "src/main/java/com/jolt/payment/PaymentApplication.java": `package com.jolt.payment;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class PaymentApplication {
    public static void main(String[] args) {
        SpringApplication.run(PaymentApplication.class, args);
    }
}
`,
  "src/main/java/com/jolt/payment/api/PaymentController.java": `package com.jolt.payment.api;

import com.jolt.payment.api.dto.CreatePaymentRequest;
import com.jolt.payment.application.PaymentService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/payments")
public class PaymentController {
    private final PaymentService paymentService;

    public PaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> create(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody CreatePaymentRequest request) {
        return ResponseEntity.ok(paymentService.create(idempotencyKey, request));
    }
}
`,
  "src/main/java/com/jolt/payment/api/dto/CreatePaymentRequest.java": `package com.jolt.payment.api.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;

public record CreatePaymentRequest(
        @NotBlank String userId,
        @NotBlank String orderNo,
        @NotBlank String channel,
        @NotNull @DecimalMin("0.01") BigDecimal amount) {
}
`,
  "src/main/java/com/jolt/payment/application/PaymentService.java": `package com.jolt.payment.application;

import com.jolt.payment.api.dto.CreatePaymentRequest;
import com.jolt.payment.domain.Payment;
import com.jolt.payment.domain.PaymentStatus;
import com.jolt.payment.infrastructure.IdempotencyService;
import com.jolt.payment.repository.PaymentRepository;
import java.time.Duration;
import java.util.Map;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PaymentService {
    private final PaymentRepository paymentRepository;
    private final RedisTemplate<String, Object> redisTemplate;
    private final IdempotencyService idempotencyService;

    public PaymentService(PaymentRepository paymentRepository, RedisTemplate<String, Object> redisTemplate, IdempotencyService idempotencyService) {
        this.paymentRepository = paymentRepository;
        this.redisTemplate = redisTemplate;
        this.idempotencyService = idempotencyService;
    }

    @Transactional
    public Map<String, Object> create(String idempotencyKey, CreatePaymentRequest request) {
        return idempotencyService.executeOnce(idempotencyKey, () -> {
            Payment payment = Payment.create(request.orderNo(), request.userId(), request.channel(), request.amount());
            paymentRepository.save(payment);
            redisTemplate.opsForValue().set("payment:last:" + request.userId(), payment.getOrderNo(), Duration.ofMinutes(30));
            return Map.of("paymentId", payment.getId(), "status", PaymentStatus.CREATED.name());
        });
    }

    public Object recent(String userId) {
        return paymentRepository.findByUserIdOrderByCreatedAtDesc(userId, PageRequest.of(0, 20));
    }
}
`,
  "src/main/java/com/jolt/payment/domain/Payment.java": `package com.jolt.payment.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.Id;
import java.math.BigDecimal;
import java.time.Instant;

@Entity
public class Payment {
    @Id
    @GeneratedValue
    private Long id;
    private String orderNo;
    private String userId;
    private String channel;
    private BigDecimal amount;
    private PaymentStatus status;
    private Instant createdAt;

    public static Payment create(String orderNo, String userId, String channel, BigDecimal amount) {
        Payment payment = new Payment();
        payment.orderNo = orderNo;
        payment.userId = userId;
        payment.channel = channel;
        payment.amount = amount;
        payment.status = PaymentStatus.CREATED;
        payment.createdAt = Instant.now();
        return payment;
    }

    public Long getId() {
        return id;
    }

    public String getOrderNo() {
        return orderNo;
    }
}
`,
  "src/main/java/com/jolt/payment/domain/PaymentStatus.java": `package com.jolt.payment.domain;

public enum PaymentStatus {
    CREATED,
    PAID,
    REFUNDED,
    CLOSED
}
`,
  "src/main/java/com/jolt/payment/infrastructure/IdempotencyService.java": `package com.jolt.payment.infrastructure;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Supplier;
import org.springframework.stereotype.Component;

@Component
public class IdempotencyService {
    private final Map<String, Object> cache = new ConcurrentHashMap<>();

    @SuppressWarnings("unchecked")
    public <T> T executeOnce(String key, Supplier<T> action) {
        return (T) cache.computeIfAbsent(key, ignored -> action.get());
    }
}
`,
  "src/main/java/com/jolt/payment/repository/PaymentRepository.java": `package com.jolt.payment.repository;

import com.jolt.payment.domain.Payment;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

public interface PaymentRepository extends JpaRepository<Payment, Long> {
    Page<Payment> findByUserIdOrderByCreatedAtDesc(String userId, Pageable pageable);
}
`,
  "src/main/resources/application.yml": `spring:
  datasource:
    url: jdbc:h2:mem:payment
    username: sa
    password: \${PAYMENT_DB_PASSWORD:}
management:
  endpoints:
    web:
      exposure:
        include: "health,prometheus"
`,
  "src/main/resources/db/migration/V1__init_payment_schema.sql": `CREATE TABLE payments (
  id BIGINT PRIMARY KEY,
  order_no VARCHAR(64) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  channel VARCHAR(32) NOT NULL,
  amount DECIMAL(18,2) NOT NULL,
  status VARCHAR(32) NOT NULL,
  created_at TIMESTAMP NOT NULL
);
`,
  "src/test/java/com/jolt/payment/application/PaymentServiceTest.java": `package com.jolt.payment.application;

import org.junit.jupiter.api.Test;

class PaymentServiceTest {
    @Test
    void shouldCreatePaymentOnceForSameIdempotencyKey() {
        // fixture baseline test placeholder
    }
}
`,
};

const riskyControllerLines = [
  "package com.jolt.payment.api;",
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
  "import org.springframework.web.bind.annotation.RequestMapping;",
  "import org.springframework.web.bind.annotation.RestController;",
  "",
  "@RestController",
  "@RequestMapping(\"/api/payments/search\")",
  "public class PaymentSearchController {",
  "    private static final String ADMIN_PASSWORD = \"admin123456\";",
  "    private final Connection connection;",
  "    private final RedisTemplate<String, Object> redisTemplate;",
  "    @Autowired",
  "    private PaymentAuditClient auditClient;",
  "",
  "    public PaymentSearchController(Connection connection, RedisTemplate<String, Object> redisTemplate) {",
  "        this.connection = connection;",
  "        this.redisTemplate = redisTemplate;",
  "    }",
  "",
  "    @PostMapping",
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
  "            auditClient.recordSearch(userId, response);",
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

const auditClientLines = [
  "package com.jolt.payment.api;",
  "",
  "import java.util.Map;",
  "",
  "public interface PaymentAuditClient {",
  "    void recordSearch(String userId, Map<String, Object> result);",
  "}",
];

const aggregateLines = [
  "package com.jolt.payment.domain;",
  "",
  "import java.util.HashMap;",
  "import java.util.Map;",
  "",
  "public class PaymentAggregate {",
  "    private Map<String, Object> json = new HashMap<>();",
  "",
  "    public void update(Map<String, Object> payload) {",
  "        this.json.putAll(payload);",
  "        if (payload.containsKey(\"status\")) {",
  "            this.json.put(\"status\", payload.get(\"status\"));",
  "        }",
  "    }",
  "}",
];

const badPomLines = [
  "    <dependency>",
  "      <groupId>com.alibaba</groupId>",
  "      <artifactId>fastjson</artifactId>",
  "      <version>1.2.47</version>",
  "    </dependency>",
  "    <dependency>",
  "      <groupId>org.mockito</groupId>",
  "      <artifactId>mockito-core</artifactId>",
  "      <version>5.11.0</version>",
  "    </dependency>",
];

const badConfigLines = [
  "spring:",
  "  datasource:",
  "    url: jdbc:mysql://payment-db.internal/payment",
  "    password: paymentRoot123",
  "management:",
  "  endpoints:",
  "    web:",
  "      exposure:",
  "        include: \"*\"",
];

const badMigrationLines = [
  "ALTER TABLE payments ADD COLUMN channel_type VARCHAR(32) NOT NULL;",
  "ALTER TABLE payments DROP COLUMN legacy_remark;",
];

function buildHeadPom() {
  return baselineFiles["pom.xml"].replace("  </dependencies>", `${badPomLines.join("\n")}\n  </dependencies>`);
}

function changedFiles() {
  return [
    {
      filename: "src/main/java/com/jolt/payment/api/PaymentSearchController.java",
      status: "added",
      additions: riskyControllerLines.length,
      deletions: 0,
      changes: riskyControllerLines.length,
      patch: addPatch(riskyControllerLines),
    },
    {
      filename: "src/main/java/com/jolt/payment/api/PaymentAuditClient.java",
      status: "added",
      additions: auditClientLines.length,
      deletions: 0,
      changes: auditClientLines.length,
      patch: addPatch(auditClientLines),
    },
    {
      filename: "src/main/java/com/jolt/payment/domain/PaymentAggregate.java",
      status: "added",
      additions: aggregateLines.length,
      deletions: 0,
      changes: aggregateLines.length,
      patch: addPatch(aggregateLines),
    },
    {
      filename: "pom.xml",
      status: "modified",
      additions: badPomLines.length,
      deletions: 0,
      changes: badPomLines.length,
      patch: modifiedPatch(33, badPomLines),
    },
    {
      filename: "src/main/resources/application-prod.yml",
      status: "added",
      additions: badConfigLines.length,
      deletions: 0,
      changes: badConfigLines.length,
      patch: addPatch(badConfigLines),
    },
    {
      filename: "src/main/resources/db/migration/V2__payment_search_risk.sql",
      status: "added",
      additions: badMigrationLines.length,
      deletions: 0,
      changes: badMigrationLines.length,
      patch: addPatch(badMigrationLines),
    },
  ];
}

function resetDir(dir) {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
}

function writeBaselineRepo(repoDir) {
  resetDir(repoDir);
  for (const [filePath, content] of Object.entries(baselineFiles)) {
    writeText(repoDir, filePath, content);
  }
}

function writeHeadRepo(headDir) {
  resetDir(headDir);
  for (const [filePath, content] of Object.entries(baselineFiles)) {
    writeText(headDir, filePath, content);
  }
  writeText(headDir, "pom.xml", buildHeadPom());
  writeText(headDir, "src/main/java/com/jolt/payment/api/PaymentSearchController.java", linesToText(riskyControllerLines));
  writeText(headDir, "src/main/java/com/jolt/payment/api/PaymentAuditClient.java", linesToText(auditClientLines));
  writeText(headDir, "src/main/java/com/jolt/payment/domain/PaymentAggregate.java", linesToText(aggregateLines));
  writeText(headDir, "src/main/resources/application-prod.yml", linesToText(badConfigLines));
  writeText(headDir, "src/main/resources/db/migration/V2__payment_search_risk.sql", linesToText(badMigrationLines));
}

function seedPaymentSpringbootEval() {
  const baseRepoDir = path.join(root, "data", "eval-repos", "payment-springboot-service");
  const headRepoDir = path.join(root, "data", "eval-repos", "payment-springboot-service-mr-1001");
  const fixturePath = path.join(root, "data", "fixtures", "payment-springboot-mr-1001-files.json");
  mkdirSync(path.dirname(fixturePath), { recursive: true });
  writeBaselineRepo(baseRepoDir);
  writeHeadRepo(headRepoDir);
  writeFileSync(fixturePath, JSON.stringify(changedFiles(), null, 2), "utf8");

  const expectedIssues = [
    "SEC-SECRET-004",
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
    "DDD-VO-002",
    "DEP-CVE-001",
    "DEP-SCOPE-005",
    "SEC-CONFIG-007",
    "DB-NOTNULL-002",
    "DB-DDL-001",
    "TEST-COVER-001",
  ];

  const db = new DatabaseSync(dbPath());
  const headSha = `payment_eval_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-eval",
    repo: "payment-springboot-service",
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-eval/payment-springboot-service', 'payment-springboot-service', 'main', 'active', ?)
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
    VALUES (?, ?, ?, ?, '新增支付查询能力与生产配置调整', 'payment-eval-user', 'feature/payment-search-risk', 'main',
      'queued', 98, ?, 'https://github.com/jolt-eval/payment-springboot-service/pull/1001', ?, CURRENT_TIMESTAMP)
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
      eval_repo_kind: "springboot-payment-service",
      base_repo_path: path.relative(root, baseRepoDir),
      local_repo_path: path.relative(root, headRepoDir),
      fixture_changed_files: path.relative(root, fixturePath),
      expected_issues: expectedIssues,
    })
  );

  db.prepare("UPDATE review_jobs SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE merge_request_id = ? AND status = 'queued'")
    .run(MR_ID);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 1200, 'standard')
  `).run(jobId, MR_ID, headSha);
  db.close();

  return {
    repoId: REPO_ID,
    mrId: MR_ID,
    jobId,
    headSha,
    baseRepoDir,
    headRepoDir,
    fixturePath,
    expectedCount: expectedIssues.length,
  };
}

console.log(JSON.stringify(seedPaymentSpringbootEval(), null, 2));
