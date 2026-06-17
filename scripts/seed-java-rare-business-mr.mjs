import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_default";
const REPO_ID = "repo_github_java_rare_business";
const MR_ID = "mr_repo_github_java_rare_business_9601";
const MR_NUMBER = 9601;
const FIXTURE_DIR = path.join(root, "data", "fixtures", "java-rare-business-mr");

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
  fixtureFile("src/main/java/com/acme/settlement/api/SettlementAdminController.java", [
    "package com.acme.settlement.api;",
    "",
    "import com.acme.settlement.service.SettlementPayoutService;",
    "import java.math.BigDecimal;",
    "import java.util.List;",
    "import java.util.Map;",
    "import org.springframework.web.bind.annotation.PostMapping;",
    "import org.springframework.web.bind.annotation.RequestBody;",
    "import org.springframework.web.bind.annotation.RequestHeader;",
    "import org.springframework.web.bind.annotation.RequestMapping;",
    "import org.springframework.web.bind.annotation.RestController;",
    "",
    "@RestController",
    "@RequestMapping(\"/admin/settlements\")",
    "public class SettlementAdminController {",
    "    private final SettlementPayoutService payoutService;",
    "",
    "    public SettlementAdminController(SettlementPayoutService payoutService) {",
    "        this.payoutService = payoutService;",
    "    }",
    "",
    "    @PostMapping(\"/force-pay\")",
    "    public Map<String, Object> forcePay(@RequestHeader(\"X-Operator\") String operator, @RequestBody Map<String, Object> payload) {",
    "        String tenantId = String.valueOf(payload.get(\"tenantId\"));",
    "        String merchantId = String.valueOf(payload.get(\"merchantId\"));",
    "        BigDecimal amount = new BigDecimal(String.valueOf(payload.get(\"amount\")));",
    "        return payoutService.forcePay(operator, tenantId, merchantId, amount);",
    "    }",
    "",
    "    @PostMapping(\"/bulk-risk\")",
    "    public Map<String, Object> bulkRisk(@RequestBody List<String> settlementIds) {",
    "        return payoutService.refreshRiskScores(settlementIds);",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/SettlementPayoutService.java", [
    "package com.acme.settlement.service;",
    "",
    "import com.acme.settlement.domain.SettlementLedger;",
    "import com.acme.settlement.domain.SettlementStatus;",
    "import java.math.BigDecimal;",
    "import java.time.LocalDate;",
    "import java.time.ZoneId;",
    "import java.util.ArrayList;",
    "import java.util.HashMap;",
    "import java.util.List;",
    "import java.util.Map;",
    "import org.springframework.expression.ExpressionParser;",
    "import org.springframework.expression.spel.standard.SpelExpressionParser;",
    "import org.springframework.transaction.annotation.Transactional;",
    "",
    "public class SettlementPayoutService {",
    "    private static final ThreadLocal<String> CURRENT_TENANT = new ThreadLocal<>();",
    "    private final SettlementRepository repository;",
    "    private final PayoutGateway payoutGateway;",
    "    private final RiskClient riskClient;",
    "    private final AuditRepository auditRepository;",
    "",
    "    public SettlementPayoutService(SettlementRepository repository, PayoutGateway payoutGateway, RiskClient riskClient, AuditRepository auditRepository) {",
    "        this.repository = repository;",
    "        this.payoutGateway = payoutGateway;",
    "        this.riskClient = riskClient;",
    "        this.auditRepository = auditRepository;",
    "    }",
    "",
    "    @Transactional",
    "    public Map<String, Object> forcePay(String operator, String tenantId, String merchantId, BigDecimal amount) {",
    "        CURRENT_TENANT.set(tenantId);",
    "        SettlementLedger ledger = repository.findByMerchantId(merchantId);",
    "        ledger.overrideMerchant(merchantId);",
    "        ledger.setStatus(SettlementStatus.PAID);",
    "        ledger.setPaidAmount(amount);",
    "        repository.save(ledger);",
    "        PayoutReceipt receipt = payoutGateway.payOut(merchantId, amount);",
    "        auditRepository.save(\"forcePay operator=\" + operator + \", tenant=\" + tenantId + \", card=\" + receipt.cardNo());",
    "        Map<String, Object> response = new HashMap<>();",
    "        response.put(\"status\", \"ok\");",
    "        response.put(\"cardNo\", receipt.cardNo());",
    "        response.put(\"trace\", receipt.rawGatewayMessage());",
    "        return response;",
    "    }",
    "",
    "    public Map<String, Object> refreshRiskScores(List<String> settlementIds) {",
    "        List<RiskScore> scores = new ArrayList<>();",
    "        for (String settlementId : settlementIds) {",
    "            RiskScore score = riskClient.fetchScore(settlementId);",
    "            scores.add(score);",
    "        }",
    "        return Map.of(\"scores\", scores);",
    "    }",
    "",
    "    public boolean isPromotionOpen(String expression, Map<String, Object> context) {",
    "        ExpressionParser parser = new SpelExpressionParser();",
    "        return Boolean.TRUE.equals(parser.parseExpression(expression).getValue(context, Boolean.class));",
    "    }",
    "",
    "    public LocalDate settlementDay(long epochMillis) {",
    "        return LocalDate.ofInstant(java.time.Instant.ofEpochMilli(epochMillis), ZoneId.systemDefault());",
    "    }",
    "",
    "    public List<SettlementLedger> exportAll() {",
    "        return repository.findAll().stream().toList();",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/domain/SettlementLedger.java", [
    "package com.acme.settlement.domain;",
    "",
    "import java.math.BigDecimal;",
    "import java.util.HashMap;",
    "import java.util.Map;",
    "",
    "public class SettlementLedger {",
    "    private String tenantId;",
    "    private String merchantId;",
    "    private BigDecimal paidAmount;",
    "    private SettlementStatus status;",
    "    private Map<String, Object> extension = new HashMap<>();",
    "",
    "    public void overrideMerchant(String merchantId) {",
    "        this.merchantId = merchantId;",
    "    }",
    "",
    "    public void setStatus(SettlementStatus status) {",
    "        this.status = status;",
    "    }",
    "",
    "    public void setPaidAmount(BigDecimal paidAmount) {",
    "        this.paidAmount = paidAmount;",
    "    }",
    "",
    "    public void putExtension(String key, Object value) {",
    "        extension.put(key, value);",
    "    }",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/domain/SettlementStatus.java", [
    "package com.acme.settlement.domain;",
    "",
    "public enum SettlementStatus {",
    "    CREATED,",
    "    RISK_CHECKING,",
    "    APPROVED,",
    "    PAID,",
    "    FAILED",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/SettlementRepository.java", [
    "package com.acme.settlement.service;",
    "",
    "import com.acme.settlement.domain.SettlementLedger;",
    "import java.util.List;",
    "",
    "public interface SettlementRepository {",
    "    SettlementLedger findByMerchantId(String merchantId);",
    "    List<SettlementLedger> findAll();",
    "    void save(SettlementLedger ledger);",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/PayoutGateway.java", [
    "package com.acme.settlement.service;",
    "",
    "import java.math.BigDecimal;",
    "",
    "public interface PayoutGateway {",
    "    PayoutReceipt payOut(String merchantId, BigDecimal amount);",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/PayoutReceipt.java", [
    "package com.acme.settlement.service;",
    "",
    "public record PayoutReceipt(String cardNo, String rawGatewayMessage) {}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/RiskClient.java", [
    "package com.acme.settlement.service;",
    "",
    "public interface RiskClient {",
    "    RiskScore fetchScore(String settlementId);",
    "}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/RiskScore.java", [
    "package com.acme.settlement.service;",
    "",
    "public record RiskScore(String settlementId, int score) {}",
  ]),
  fixtureFile("src/main/java/com/acme/settlement/service/AuditRepository.java", [
    "package com.acme.settlement.service;",
    "",
    "public interface AuditRepository {",
    "    void save(String message);",
    "}",
  ]),
  fixtureFile("src/main/resources/db/migration/V20260616__rare_settlement.sql", [
    "ALTER TABLE settlement_ledger ADD COLUMN tenant_id VARCHAR(64) NOT NULL;",
    "ALTER TABLE settlement_ledger DROP COLUMN legacy_batch_no;",
  ]),
  fixtureFile("pom.xml", [
    "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">",
    "  <modelVersion>4.0.0</modelVersion>",
    "  <groupId>com.acme</groupId>",
    "  <artifactId>settlement-service</artifactId>",
    "  <version>1.0.0</version>",
    "  <dependencies>",
    "    <dependency>",
    "      <groupId>com.alibaba</groupId>",
    "      <artifactId>fastjson</artifactId>",
    "      <version>1.2.47</version>",
    "    </dependency>",
    "    <dependency>",
    "      <groupId>org.springframework.boot</groupId>",
    "      <artifactId>spring-boot-starter-test</artifactId>",
    "      <version>3.2.5</version>",
    "    </dependency>",
    "  </dependencies>",
    "</project>",
  ]),
];

const expectedIssues = [
  {
    rule_id: "SEC-AUTHZ-002",
    title: "forcePay 使用请求 tenantId/merchantId 未校验资源归属",
    file_path: "src/main/java/com/acme/settlement/api/SettlementAdminController.java",
    line_start: 24,
    keywords: ["tenant", "merchant", "归属"],
  },
  {
    rule_id: "BE-IDEMP-004",
    title: "forcePay 副作用接口缺少幂等保护",
    file_path: "src/main/java/com/acme/settlement/api/SettlementAdminController.java",
    line_start: 22,
    keywords: ["幂等", "forcePay"],
  },
  {
    rule_id: "BE-API-001",
    title: "bulkRisk 接收无校验 List 请求体",
    file_path: "src/main/java/com/acme/settlement/api/SettlementAdminController.java",
    line_start: 31,
    keywords: ["@RequestBody", "List"],
  },
  {
    rule_id: "DDD-AGG-001",
    title: "SettlementLedger 状态和商户归属被外部任意覆盖",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 34,
    keywords: ["status", "merchant"],
  },
  {
    rule_id: "BE-TX-002",
    title: "事务内调用外部打款网关",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 38,
    keywords: ["transaction", "payOut"],
  },
  {
    rule_id: "SEC-SECRET-004",
    title: "审计日志和响应暴露银行卡号和网关原文",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 39,
    keywords: ["card", "rawGatewayMessage"],
  },
  {
    rule_id: "PERF-QUERY-001",
    title: "bulk risk 循环内逐条远程调用",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 49,
    keywords: ["fetchScore", "循环"],
  },
  {
    rule_id: "SEC-INJECT-003",
    title: "SpEL 表达式来自外部输入可执行",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 57,
    keywords: ["spel", "parseExpression"],
  },
  {
    rule_id: "CODE-STATE-004",
    title: "ThreadLocal 租户上下文未清理",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 31,
    keywords: ["ThreadLocal", "remove"],
  },
  {
    rule_id: "PERF-MEM-004",
    title: "findAll 导出无界结果集进入内存",
    file_path: "src/main/java/com/acme/settlement/service/SettlementPayoutService.java",
    line_start: 65,
    keywords: ["findAll", "toList"],
  },
  {
    rule_id: "DB-NOTNULL-002",
    title: "新增 NOT NULL 列缺少默认值和回填",
    file_path: "src/main/resources/db/migration/V20260616__rare_settlement.sql",
    line_start: 1,
    keywords: ["NOT NULL", "tenant_id"],
  },
  {
    rule_id: "DB-DDL-001",
    title: "迁移脚本直接 DROP COLUMN",
    file_path: "src/main/resources/db/migration/V20260616__rare_settlement.sql",
    line_start: 2,
    keywords: ["DROP COLUMN", "legacy_batch_no"],
  },
  {
    rule_id: "DEP-CVE-001",
    title: "fastjson 1.2.47 已知漏洞",
    file_path: "pom.xml",
    line_start: 10,
    keywords: ["fastjson", "1.2.47"],
  },
];

function writeFixtureFiles() {
  mkdirSync(FIXTURE_DIR, { recursive: true });
  const fixturePath = path.join(FIXTURE_DIR, "github-java-rare-business-mr-files.json");
  const localRepoDir = path.join(FIXTURE_DIR, "repo");
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
  const headSha = `java_rare_business_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "java-rare-business-service",
    token_env: "GITHUB_TOKEN",
    git_url: "https://github.com/jolt-fixture/java-rare-business-service.git",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  const db = new DatabaseSync(dbPath());
  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', 'jolt-fixture/java-rare-business-service', 'java-rare-business-service', 'main', 'active', ?)
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
    VALUES (?, ?, ?, ?, '罕见业务风险 Java MR：结算强制打款与风控刷新', 'java-eval-user', 'feature/rare-settlement-risk', 'main',
      'queued', 99, ?, 'https://github.com/jolt-fixture/java-rare-business-service/pull/9601', ?, CURRENT_TIMESTAMP)
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
      eval_repo_kind: "springboot-settlement-rare-business",
      local_repo_path: path.relative(root, localRepoDir),
      fixture_changed_files: path.relative(root, fixturePath),
      expected_issues: expectedIssues.map((item) => item.rule_id),
      expected_issue_details: expectedIssues,
    })
  );

  db.prepare(`
    UPDATE review_jobs
    SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
    WHERE merge_request_id = ?
      AND status IN ('queued', 'reviewing')
  `).run(MR_ID);
  db.prepare(`
    INSERT INTO review_jobs (id, merge_request_id, head_sha, status, priority, requested_effort_level)
    VALUES (?, ?, ?, 'queued', 9700, 'standard')
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
