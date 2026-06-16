import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { loadConfig, root } from "./config-utils.mjs";

const PROJECT_ID = process.env.PROJECT_ID || "project_low_level_rule_doc_eval";
const REPO_ID = "repo_github_low_level_rule_doc_eval";
const MR_ID = "mr_repo_github_low_level_rule_doc_eval_9401";
const MR_NUMBER = 9401;
const RULE_DOCUMENT_ID = "rule_doc_low_level_binding_eval";
const RULE_DOCUMENT_PATH = path.join(root, "docs", "standards", "LOW_LEVEL_RULE_DOC_BINDING_EVAL.md");
const FIXTURE_DIR = path.join(root, "data", "fixtures", "low-level-rule-doc-binding");

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
  "package com.acme.lowlevel;",
  "",
  "import java.io.File;",
  "import java.io.FileInputStream;",
  "import java.math.BigDecimal;",
  "import java.text.SimpleDateFormat;",
  "import java.util.ArrayList;",
  "import java.util.Date;",
  "import java.util.List;",
  "import java.util.Optional;",
  "import java.util.Properties;",
  "import org.springframework.stereotype.Service;",
  "",
  "@Service",
  "public class LowLevelSettlementService {",
  "    private static final SimpleDateFormat DAY_FORMAT = new SimpleDateFormat(\"yyyyMMdd\");",
  "    private final CustomerRepository customerRepository;",
  "    private final OrderRepository orderRepository;",
  "",
  "    public LowLevelSettlementService(CustomerRepository customerRepository, OrderRepository orderRepository) {",
  "        this.customerRepository = customerRepository;",
  "        this.orderRepository = orderRepository;",
  "    }",
  "",
  "    public String normalizeNickname(Long customerId) {",
  "        Customer customer = customerRepository.findById(customerId);",
  "        return customer.getProfile().getNickname().trim();",
  "    }",
  "",
  "    public PaymentOrder loadOrder(String orderNo) {",
  "        Optional<PaymentOrder> order = orderRepository.findByOrderNo(orderNo);",
  "        return order.get();",
  "    }",
  "",
  "    public BigDecimal calculateDiscount(BigDecimal amount, double rate) {",
  "        BigDecimal discountRate = new BigDecimal(rate);",
  "        return amount.multiply(discountRate).setScale(2);",
  "    }",
  "",
  "    public List<PaymentOrder> removeExpiredOrders(List<PaymentOrder> orders) {",
  "        List<PaymentOrder> activeOrders = new ArrayList<>(orders);",
  "        for (PaymentOrder order : activeOrders) {",
  "            if (order.isExpired()) {",
  "                activeOrders.remove(order);",
  "            }",
  "        }",
  "        return activeOrders;",
  "    }",
  "",
  "    public SettlementSnapshot loadSnapshot(String orderNo) {",
  "        try {",
  "            return orderRepository.fetchSnapshot(orderNo);",
  "        } catch (Exception ex) {",
  "            ex.printStackTrace();",
  "            return null;",
  "        }",
  "    }",
  "",
  "    public Properties loadProperties(File file) throws Exception {",
  "        Properties props = new Properties();",
  "        FileInputStream input = new FileInputStream(file);",
  "        props.load(input);",
  "        return props;",
  "    }",
  "",
  "    public String formatBusinessDay(Date date) {",
  "        return DAY_FORMAT.format(date);",
  "    }",
  "",
  "    interface CustomerRepository {",
  "        Customer findById(Long customerId);",
  "    }",
  "",
  "    interface OrderRepository {",
  "        Optional<PaymentOrder> findByOrderNo(String orderNo);",
  "        SettlementSnapshot fetchSnapshot(String orderNo);",
  "    }",
  "",
  "    record Customer(Profile profile) {",
  "        Profile getProfile() { return profile; }",
  "    }",
  "",
  "    record Profile(String nickname) {",
  "        String getNickname() { return nickname; }",
  "    }",
  "",
  "    record PaymentOrder(boolean expired) {",
  "        boolean isExpired() { return expired; }",
  "    }",
  "",
  "    record SettlementSnapshot(String orderNo) {}",
  "}",
];

const files = [
  fixtureFile("src/main/java/com/acme/lowlevel/LowLevelSettlementService.java", sourceLines),
];

const expectedIssues = [
  {
    rule_id: "LLDOC-CONC-107",
    title: "static SimpleDateFormat 跨线程共享",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 16,
    keywords: ["SimpleDateFormat", "static"],
  },
  {
    rule_id: "LLDOC-NULL-101",
    title: "可空对象链式解引用",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 27,
    keywords: ["getProfile", "getNickname"],
  },
  {
    rule_id: "LLDOC-OPT-102",
    title: "Optional.get 未先判断存在性",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 32,
    keywords: ["Optional", ".get"],
  },
  {
    rule_id: "LLDOC-MONEY-103",
    title: "BigDecimal 使用 double 构造金额",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 36,
    keywords: ["BigDecimal", "double"],
  },
  {
    rule_id: "LLDOC-COLL-104",
    title: "增强 for 遍历中修改集合",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 44,
    keywords: ["remove", "for"],
  },
  {
    rule_id: "LLDOC-EXC-105",
    title: "异常被吞掉并返回 null",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 55,
    keywords: ["printStackTrace", "return null"],
  },
  {
    rule_id: "LLDOC-RES-106",
    title: "IO 资源未使用 try-with-resources 关闭",
    file_path: "src/main/java/com/acme/lowlevel/LowLevelSettlementService.java",
    line_start: 61,
    keywords: ["FileInputStream", "try-with-resources"],
  },
];

function writeFixtureFiles() {
  mkdirSync(FIXTURE_DIR, { recursive: true });
  const fixturePath = path.join(FIXTURE_DIR, "github-low-level-rule-doc-mr-files.json");
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
  const headSha = `low_level_rule_doc_${Date.now()}`;
  const jobId = id("job");
  const providerConfig = {
    endpoint: "https://api.github.com",
    owner: "jolt-fixture",
    repo: "low-level-rule-doc-binding",
    token_env: "GITHUB_TOKEN",
    fixture_changed_files: path.relative(root, fixturePath),
  };

  const db = new DatabaseSync(dbPath());
  db.prepare(`
    INSERT INTO projects (id, name, description, data_policy_json)
    VALUES (?, '低级缺陷规范绑定评估项目', '仅启用 low_level_defect_agent，用于验证专家绑定 Markdown 规范文档后的检视能力', ?)
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
    "policy_project_low_level_rule_doc_eval",
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
    VALUES (?, ?, 'low_level_defect_agent', '低级缺陷 Agent',
      'Java 低级缺陷检视专家，按项目绑定 Markdown 规范逐条检查空值、Optional、金额、集合、异常、资源和基础并发 API 误用。',
      '只检视 Java/Spring 代码中的低级实现缺陷、边界条件缺失、API 误用、空值风险、异常处理错误和基础并发问题。',
      '不检视架构设计、DDD 建模、性能容量专项、安全漏洞专项、依赖 CVE、前端交互和数据库专项问题。',
      1, 0.75, 12, 4, 8, 'finding_v1')
    ON CONFLICT(project_id, agent_key) DO UPDATE SET
      display_name = excluded.display_name,
      role_profile = excluded.role_profile,
      responsibility_scope = excluded.responsibility_scope,
      excluded_scope = excluded.excluded_scope,
      enabled = 1,
      max_findings = excluded.max_findings,
      max_llm_calls = excluded.max_llm_calls,
      max_tool_calls = excluded.max_tool_calls
  `).run("expert_low_level_rule_doc_eval", PROJECT_ID);
  db.prepare(`
    INSERT INTO agent_configs (
      id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
      skills_json, rule_sets_json, min_confidence, max_findings_per_mr, requires_deepagents
    )
    VALUES (?, ?, 'low_level_defect_agent', '低级缺陷 Agent', 1, ?, '[]', '[]', '[]', 0.75, 12, 0)
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
    "agent_low_level_rule_doc_eval",
    PROJECT_ID,
    JSON.stringify({
      persona: "Java 低级缺陷检视专家",
      review_scope: "只检视 Java 低级实现缺陷",
      excluded_scope: "不检视架构、DDD、安全专项、数据库专项和依赖问题",
      exclusive_scope: "low_level_defect",
      languages: ["java"],
      paths: ["src/main/java/**", "**/*.java"],
      triggers: ["null", "optional", "bigdecimal", "remove", "exception", "close", "fileinputstream", "simpledateformat"],
      custom_prompt: "必须优先依据本项目绑定的 Markdown 规范文档 LLDOC-* 规则逐条检查；每个 finding 的 covered_rules 必须使用命中的 LLDOC-* rule_id。",
    })
  );
  db.prepare(`
    INSERT INTO rule_documents (id, project_id, name, doc_type, content, version, status)
    VALUES (?, ?, '低级缺陷专家规范文档绑定评估', 'markdown', ?, 'eval-v1', 'active')
    ON CONFLICT(id) DO UPDATE SET
      name = excluded.name,
      doc_type = excluded.doc_type,
      content = excluded.content,
      version = excluded.version,
      status = excluded.status
  `).run(RULE_DOCUMENT_ID, PROJECT_ID, ruleContent);

  db.prepare(`
    INSERT INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
    VALUES ('binding_low_level_rule_doc_eval_project', ?, 'low_level_defect_agent', ?, 5)
    ON CONFLICT(project_id, agent_key, rule_document_id) DO UPDATE SET
      priority = excluded.priority
  `).run(PROJECT_ID, RULE_DOCUMENT_ID);

  db.prepare(`
    INSERT INTO repositories (id, project_id, provider, external_repo_id, name, default_branch, status, provider_config_json)
    VALUES (?, ?, 'github', ?, 'low-level-rule-doc-binding', 'main', 'active', ?)
    ON CONFLICT(project_id, provider, external_repo_id) DO UPDATE SET
      name = excluded.name,
      status = 'active',
      provider_config_json = excluded.provider_config_json,
      updated_at = CURRENT_TIMESTAMP
  `).run(REPO_ID, PROJECT_ID, "jolt-fixture/low-level-rule-doc-binding", JSON.stringify(providerConfig));

  db.prepare(`
    INSERT INTO merge_requests (
      id, repository_id, external_mr_id, number, title, author, source_branch, target_branch,
      review_status, risk_score, latest_head_sha, html_url, metadata_json, updated_at
    )
    VALUES (?, ?, ?, ?, 'Low-level rule document binding defects', 'java-fixture-user',
      'feature/low-level-rule-doc-binding', 'main', 'queued', 92, ?, ?, ?, CURRENT_TIMESTAMP)
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
    `https://github.com/jolt-fixture/low-level-rule-doc-binding/pull/${MR_NUMBER}`,
    JSON.stringify({
      provider: "github",
      fixture: true,
      language: "java",
      local_repo_path: path.relative(root, localRepoDir),
      expected_issues: expectedIssues.map((item) => item.rule_id),
      expected_issue_details: expectedIssues,
      rule_document_id: RULE_DOCUMENT_ID,
      bound_agent: "low_level_defect_agent",
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
    VALUES (?, ?, ?, 'queued', 950, 'standard')
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
