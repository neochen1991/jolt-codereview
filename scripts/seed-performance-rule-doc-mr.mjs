import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_performance_rule_doc_eval";
const REPO_ID = "repo_github_performance_rule_doc_eval";
const MR_ID = "mr_repo_github_performance_rule_doc_eval_9501";
const MR_NUMBER = 9501;
const RULE_DOCUMENT_ID = "rule_doc_performance_binding_eval";
const RULE_DOCUMENT_PATH = path.join(root, "docs", "standards", "PERFORMANCE_RULE_DOC_BINDING_EVAL.md");
const FIXTURE_DIR = path.join(root, "data", "fixtures", "performance-rule-doc-binding");

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

const sourceLines = [
  "package com.acme.performance;",
  "",
  "import java.sql.Connection;",
  "import java.sql.ResultSet;",
  "import java.sql.Statement;",
  "import java.util.ArrayList;",
  "import java.util.List;",
  "import java.util.Map;",
  "import java.util.Set;",
  "import java.util.stream.Collectors;",
  "import org.springframework.data.redis.core.RedisTemplate;",
  "import org.springframework.stereotype.Service;",
  "",
  "@Service",
  "public class PerformanceOrderQueryService {",
  "    private final RedisTemplate<String, Object> redisTemplate;",
  "    private final RiskClient riskClient;",
  "    private final OrderRepository orderRepository;",
  "",
  "    public PerformanceOrderQueryService(RedisTemplate<String, Object> redisTemplate, RiskClient riskClient, OrderRepository orderRepository) {",
  "        this.redisTemplate = redisTemplate;",
  "        this.riskClient = riskClient;",
  "        this.orderRepository = orderRepository;",
  "    }",
  "",
  "    public List<Map<String, Object>> loadRecentOrders(Connection connection, String merchantId) throws Exception {",
  "        Statement statement = connection.createStatement();",
  "        String sql = \"select * from payment_orders where merchant_id = '\" + merchantId + \"'\";",
  "        ResultSet rs = statement.executeQuery(sql);",
  "        return mapOrders(rs);",
  "    }",
  "",
  "    public List<Map<String, Object>> searchByRemark(String keyword) {",
  "        String sql = \"select * from payment_orders where remark like '%\" + keyword + \"%'\";",
  "        return jdbcSearch(sql);",
  "    }",
  "",
  "    public int clearOrderCache() {",
  "        Set<String> keys = redisTemplate.keys(\"order:*\");",
  "        for (String key : keys) {",
  "            redisTemplate.delete(key);",
  "        }",
  "        return keys.size();",
  "    }",
  "",
  "    public OrderSummary cacheSummary(String userId, String keyword) {",
  "        String cacheKey = \"summary:\" + userId + \":\" + keyword;",
  "        OrderSummary response = querySummary(userId, keyword);",
  "        redisTemplate.opsForValue().set(cacheKey, response);",
  "        return response;",
  "    }",
  "",
  "    public List<RiskScore> enrichRiskScores(List<Order> orders) {",
  "        List<RiskScore> scores = new ArrayList<>();",
  "        for (Order order : orders) {",
  "            RiskScore score = riskClient.fetchRiskScore(order.getId());",
  "            scores.add(score);",
  "        }",
  "        return scores;",
  "    }",
  "",
  "    public String exportAllOrdersCsv() {",
  "        List<Order> orders = orderRepository.findAll().stream().collect(Collectors.toList());",
  "        return orders.stream().map(Order::toCsv).collect(Collectors.joining(\"\\n\"));",
  "    }",
  "",
  "    private List<Map<String, Object>> mapOrders(ResultSet rs) { return List.of(); }",
  "    private List<Map<String, Object>> jdbcSearch(String sql) { return List.of(); }",
  "    private OrderSummary querySummary(String userId, String keyword) { return new OrderSummary(); }",
  "",
  "    interface RiskClient { RiskScore fetchRiskScore(Long orderId); }",
  "    interface OrderRepository { List<Order> findAll(); }",
  "    record Order(Long id) {",
  "        Long getId() { return id; }",
  "        String toCsv() { return String.valueOf(id); }",
  "    }",
  "    record RiskScore(int value) {}",
  "    static class OrderSummary {}",
  "}",
];

const files = [
  fixtureFile("src/main/java/com/acme/performance/PerformanceOrderQueryService.java", sourceLines),
];

const expectedIssues = [
  {
    rule_id: "PERFDOC-QUERY-201",
    title: "查询缺少分页或结果上限",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 29,
    keywords: ["executeQuery", "limit"],
  },
  {
    rule_id: "PERFDOC-LIKE-202",
    title: "LIKE 前导通配符导致索引失效",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 34,
    keywords: ["like", "%"],
  },
  {
    rule_id: "PERFDOC-REDIS-203",
    title: "生产路径使用 Redis KEYS",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 39,
    keywords: ["keys", "scan"],
  },
  {
    rule_id: "PERFDOC-CACHE-204",
    title: "缓存写入缺少 TTL",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 49,
    keywords: ["opsForValue", "TTL"],
  },
  {
    rule_id: "PERFDOC-LOOP-205",
    title: "循环内远程调用",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 56,
    keywords: ["fetchRiskScore", "循环"],
  },
  {
    rule_id: "PERFDOC-MEM-206",
    title: "无界结果集一次性进入内存",
    file_path: "src/main/java/com/acme/performance/PerformanceOrderQueryService.java",
    line_start: 63,
    keywords: ["findAll", "collect"],
  },
];

function writeFixtureFiles() {
  mkdirSync(FIXTURE_DIR, { recursive: true });
  const fixturePath = path.join(FIXTURE_DIR, "github-performance-rule-doc-mr-files.json");
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
  const ruleContent = readFileSync(RULE_DOCUMENT_PATH, "utf8");
  const { fixturePath, localRepoDir } = writeFixtureFiles();
  const headSha = `performance_rule_doc_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "performance-rule-doc-binding",
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  const db = new DatabaseSync(dbPath());
  db.prepare(`
    INSERT INTO projects (id, name, description, data_policy_json)
    VALUES (?, '性能规范绑定评估项目', '仅启用 performance_agent，用于验证专家绑定 Markdown 性能规范文档后的检视能力', ?)
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      description = excluded.description,
      data_policy_json = excluded.data_policy_json
  `).run(
    PROJECT_ID,
    JSON.stringify({
      llm_providers_allowed: ["internal-minimax-2.7"],
      default_llm_provider: "internal-minimax-2.7",
      prompt_retention: "hash_only",
      diff_max_lines_to_llm: 2000,
      sensitive_paths: ["infra/secrets/**", "config/prod/**"],
      data_residency: "cn-north-1",
      fallback_on_violation: "skip_file",
      redactor_rules: [],
    })
  );
  db.prepare(`
    INSERT INTO review_policy (id, project_id, policy_json)
    VALUES (?, ?, ?)
    ON CONFLICT(project_id) DO UPDATE SET
      policy_json = excluded.policy_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    "policy_project_performance_rule_doc_eval",
    PROJECT_ID,
    JSON.stringify({
      default_effort: "standard",
      allowed_efforts: ["standard", "deep"],
      max_findings_per_mr: 20,
      default_provider: "github",
      enable_mcp: false,
    })
  );
  db.prepare(`
    INSERT INTO expert_profiles (
      id, project_id, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
      enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
    )
    VALUES (?, ?, 'performance_agent', '性能 Agent',
      'Java 性能容量检视专家，按项目绑定 Markdown 规范逐条检查数据库、缓存、Redis、远程调用和内存压力问题。',
      '只检视 Java/Spring 代码中的性能容量风险，包括无界查询、慢查询、Redis 阻塞命令、缓存生命周期、循环远程调用和一次性大内存处理。',
      '不检视低级空指针、金额精度、安全漏洞、DDD 建模、依赖 CVE、前端交互和纯数据库 DDL 兼容问题。',
      1, 0.72, 12, 4, 8, 'finding_v1')
    ON CONFLICT(project_id, agent_key) DO UPDATE SET
      display_name = excluded.display_name,
      role_profile = excluded.role_profile,
      responsibility_scope = excluded.responsibility_scope,
      excluded_scope = excluded.excluded_scope,
      enabled = 1,
      max_findings = excluded.max_findings,
      max_llm_calls = excluded.max_llm_calls,
      max_tool_calls = excluded.max_tool_calls
  `).run("expert_performance_rule_doc_eval", PROJECT_ID);
  db.prepare(`
    INSERT INTO agent_configs (
      id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
      skills_json, rule_sets_json, min_confidence, max_findings_per_mr, requires_deepagents
    )
    VALUES (?, ?, 'performance_agent', '性能 Agent', 1, ?, '[]', '[]', '[]', 0.72, 12, 0)
    ON CONFLICT(project_id, agent_id) DO UPDATE SET
      display_name = excluded.display_name,
      enabled = 1,
      applies_to_json = excluded.applies_to_json,
      tools_json = excluded.tools_json,
      skills_json = excluded.skills_json,
      rule_sets_json = excluded.rule_sets_json,
      min_confidence = excluded.min_confidence,
      max_findings_per_mr = excluded.max_findings_per_mr,
      requires_deepagents = excluded.requires_deepagents,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    "agent_performance_rule_doc_eval",
    PROJECT_ID,
    JSON.stringify({
      persona: "Java 性能容量检视专家",
      review_scope: "只检视 Java 性能容量问题",
      excluded_scope: "不检视低级缺陷、安全专项、DDD、依赖和前端问题",
      exclusive_scope: "performance",
      languages: ["java"],
      paths: ["src/main/java/**", "**/*.java"],
      triggers: ["limit", "pagination", "like", "redis", "keys", "ttl", "loop", "remote", "findall", "collect"],
      custom_prompt: "必须优先依据本项目绑定的 Markdown 性能规范文档 PERFDOC-* 规则逐条检查；每个 finding 的 covered_rules 必须使用命中的 PERFDOC-* rule_id。",
    })
  );
  db.prepare(`
    INSERT INTO rule_documents (id, project_id, name, doc_type, content, version, status)
    VALUES (?, ?, '性能专家规范文档绑定评估', 'markdown', ?, 'eval-v1', 'active')
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      doc_type = excluded.doc_type,
      content = excluded.content,
      version = excluded.version,
      status = excluded.status
  `).run(RULE_DOCUMENT_ID, PROJECT_ID, ruleContent);

  db.prepare(`
    INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
    VALUES ('binding_performance_rule_doc_eval_project', ?, 'performance_agent', ?, 5)
    ON CONFLICT(project_id, agent_key, rule_document_id) DO UPDATE SET
      priority = excluded.priority
  `).run(PROJECT_ID, RULE_DOCUMENT_ID);

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', ?, 'performance-rule-doc-binding', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(REPO_ID, PROJECT_ID, "jolt-fixture/performance-rule-doc-binding", JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, ?, ?, 'Performance rule document binding defects', 'java-fixture-user',
      'feature/performance-rule-doc-binding', 'main', 'queued', 90, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(repository_id, external_mr_id) DO UPDATE SET
      title = excluded.title,
      review_status = 'queued',
      risk_score = excluded.risk_score,
      latest_head_sha = excluded.latest_head_sha,
      html_url = excluded.html_url,
      metadata_json = excluded.metadata_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(
    MR_ID,
    REPO_ID,
    String(MR_NUMBER),
    MR_NUMBER,
    headSha,
    `https://github.com/jolt-fixture/performance-rule-doc-binding/pull/${MR_NUMBER}`,
    JSON.stringify({
      provider: "github",
      fixture: true,
      language: "java",
      local_repo_path: path.relative(root, localRepoDir),
      expected_issues: expectedIssues.map((item) => item.rule_id),
      expected_issue_details: expectedIssues,
      rule_document_id: RULE_DOCUMENT_ID,
      bound_agent: "performance_agent",
      project_id: PROJECT_ID,
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
    VALUES (?, ?, ?, 'queued', 945, 'standard')
  `).run(jobId, MR_ID, headSha);
  db.close();

  return {
    projectId: PROJECT_ID,
    repoId: REPO_ID,
    mrId: MR_ID,
    jobId,
    headSha,
    ruleDocumentId: RULE_DOCUMENT_ID,
    ruleDocumentPath: RULE_DOCUMENT_PATH,
    fixturePath,
    localRepoDir,
    expectedCount: expectedIssues.length,
  };
}

console.log(JSON.stringify(seed(), null, 2));
