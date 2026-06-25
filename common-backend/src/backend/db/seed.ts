import { existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";

import type { Db } from "./connection.js";

const ROOT = path.resolve(import.meta.dirname, "../../..");
const LOCAL_ADMIN_PASSWORD_SALT = "jolt-local-admin-dev-salt";
const LOCAL_ADMIN_PASSWORD_HASH = createHash("sha256")
  .update(`${LOCAL_ADMIN_PASSWORD_SALT}:admin123`)
  .digest("hex");

const skillByAgent: Record<string, string> = {
  security_agent: "security-review",
  performance_agent: "performance-review",
  coding_agent: "coding-review",
  ddd_agent: "ddd-design-review",
  frontend_agent: "frontend-review",
  test_agent: "test-review",
  redis_agent: "redis-review",
  dependency_agent: "dependency-review",
  database_agent: "database-review",
  backend_agent: "backend-review"
};

function loadBoundStandard(agentKey: string, displayName: string, responsibilityScope: string, excludedScope: string) {
  const skillName = skillByAgent[agentKey];
  const standardPath = skillName
    ? path.join(ROOT, "agent-skills", skillName, "JAVA_WEB_STANDARD.md")
    : "";
  if (standardPath && existsSync(standardPath)) {
    return readFileSync(standardPath, "utf8");
  }
  const ruleCode = agentKey.replace("_agent", "").toUpperCase();
  return `# ${displayName} Java Web 代码规范

适用专家：${displayName}

适用范围：${responsibilityScope}

排除范围：${excludedScope}

## ${ruleCode}-001 职责范围内问题检视

### 规范说明

只输出职责范围内、能定位到具体代码行、对生产质量有明确影响的问题。

### 检查点

- 是否命中该专家职责范围。
- 是否有精确文件和代码行证据。
- 是否能给出可执行的修改代码。

### 如何检查

1. 先依据专家画像过滤排除范围。
2. 再逐条检查该专家职责范围内的代码规范。
3. 没有明确证据时不要输出问题。

### 反例

\`\`\`text
仅按个人偏好建议修改命名。
\`\`\`

### 正例

\`\`\`text
指出具体文件、行号、风险、规则 ID 和建议修改代码。
\`\`\`
`;
}

export function seed(db: Db) {
  db.prepare(`
    INSERT OR IGNORE INTO users (id, username, display_name, email, password_hash, password_salt, global_role, status)
    VALUES ('user_local_admin', 'local-admin', '本机管理员', 'local@example.com', ?, ?, 'root', 'active')
  `).run(LOCAL_ADMIN_PASSWORD_HASH, LOCAL_ADMIN_PASSWORD_SALT);
  db.prepare(`
    UPDATE users
    SET global_role = 'root',
        password_hash = CASE WHEN COALESCE(password_hash, '') = '' THEN ? ELSE password_hash END,
        password_salt = CASE WHEN COALESCE(password_salt, '') = '' THEN ? ELSE password_salt END
    WHERE id = 'user_local_admin'
  `).run(LOCAL_ADMIN_PASSWORD_HASH, LOCAL_ADMIN_PASSWORD_SALT);

  db.prepare(`
    INSERT OR IGNORE INTO projects (id, name, description, data_policy_json)
    VALUES (
      'project_default',
      '默认项目',
      '本机调试项目，支持 GitHub PR 数据源',
      '{"llm_providers_allowed":["internal-minimax-2.7"],"default_llm_provider":"internal-minimax-2.7","prompt_retention":"hash_only","diff_max_lines_to_llm":4000,"sensitive_paths":["infra/secrets/**","config/prod/**","**/*.pem","**/*.p12"],"data_residency":"cn-north-1","fallback_on_violation":"skip_file","redactor_rules":[]}'
    )
  `).run();
  db.prepare(`
    UPDATE projects
    SET data_policy_json = '{"llm_providers_allowed":["internal-minimax-2.7"],"default_llm_provider":"internal-minimax-2.7","prompt_retention":"hash_only","diff_max_lines_to_llm":4000,"sensitive_paths":["infra/secrets/**","config/prod/**","**/*.pem","**/*.p12"],"data_residency":"cn-north-1","fallback_on_violation":"skip_file","redactor_rules":[]}'
    WHERE id = 'project_default'
      AND data_policy_json NOT LIKE '%"sensitive_paths"%'
  `).run();

  db.prepare(`
    INSERT OR IGNORE INTO project_members (id, project_id, user_id, role)
    VALUES ('member_local_admin', 'project_default', 'user_local_admin', 'project_admin')
  `).run();

  db.prepare(`
    INSERT OR IGNORE INTO review_policy (id, project_id, policy_json)
    VALUES (
      'policy_project_default',
      'project_default',
      '{"default_effort":"standard","allowed_efforts":["trivial","fast","standard","deep"],"max_findings_per_mr":40,"default_provider":"github","enable_mcp":false}'
    )
  `).run();
  const currentReviewPolicy = db.prepare("SELECT policy_json FROM review_policy WHERE project_id = 'project_default'").get() as { policy_json?: string } | undefined;
  if (currentReviewPolicy?.policy_json) {
    const policy = JSON.parse(currentReviewPolicy.policy_json) as Record<string, unknown>;
    if (Number(policy.max_findings_per_mr ?? 0) < 40) {
      db.prepare("UPDATE review_policy SET policy_json = ?, updated_at = CURRENT_TIMESTAMP WHERE project_id = 'project_default'")
        .run(JSON.stringify({ ...policy, max_findings_per_mr: 40 }));
    }
  }

  db.prepare(`
    INSERT OR IGNORE INTO rule_sets (id, project_id, name, version, scope_json, content, status)
    VALUES (
      'rules_project_default_engineering',
      'project_default',
      '默认工程检视规范',
      'v1',
      '{"source":"published_project_rules","languages":["typescript","python"],"paths":["**/*"]}',
      '高置信、少噪声；只报告有文件位置、证据和可执行修复建议的问题。优先关注权限、注入、幂等、异常、测试覆盖。',
      'active'
    )
  `).run();

  const javaLowLevelSkillContent = [
    "# Java 低级缺陷检视 Skill",
    "",
    "## 角色增强",
    "你是低级缺陷检视专家，优先发现能导致 NPE、数据精度错误、集合运行时异常、异常吞掉、资源泄露和并发基础误用的问题。",
    "",
    "## 必读参考",
    "- references/java-low-level-defects.md",
    "",
    "## 检视步骤",
    "1. 调用 read_skill_asset 读取 references/java-low-level-defects.md。",
    "2. 按参考文档中的规则逐条检查当前 MR diff。",
    "3. 只输出当前 MR 新增/修改行上的高置信低级缺陷。",
    "4. 每个 finding 必须包含 covered_rules、精确行号和 suggested_code。",
  ].join("\n");

  const javaLowLevelReference = [
    "# Java 常见低级缺陷检视规范",
    "",
    "适用专家：低级缺陷 Agent",
    "",
    "适用范围：Java / Spring 业务代码中的空值、集合、字符串、金额精度、异常、资源、时间和基础并发误用。",
    "",
    "排除范围：架构设计、领域建模、专项安全漏洞、性能容量、依赖 CVE、前端交互和数据库专项问题。",
    "",
    "## LLDEF-NULL-001 空值和 Optional 误用",
    "",
    "### 规范说明",
    "新增代码不得直接解引用可能为空的对象，不得在未判断存在性时调用 Optional.get。",
    "",
    "### 检查点",
    "- Map.get、Repository 查询、外部接口返回值是否可能为空。",
    "- Optional.get 前是否有 isPresent、orElseThrow 或明确非空语义。",
    "- 链式调用中间对象是否可能为空。",
    "",
    "### 如何检查",
    "1. 定位新增行中对象来源。",
    "2. 回看同一 diff 或上下文是否有非空保证。",
    "3. 无保证且直接解引用时输出 finding。",
    "",
    "### 反例",
    "```java",
    "String name = userRepository.findById(id).get().getName();",
    "String userId = payload.get(\"userId\").toString();",
    "```",
    "",
    "### 正例",
    "```java",
    "String name = userRepository.findById(id)",
    "    .orElseThrow(() -> new NotFoundException(id))",
    "    .getName();",
    "String userId = requireText(payload, \"userId\");",
    "```",
    "",
    "## LLDEF-STR-002 字符串比较和空串判断错误",
    "",
    "### 规范说明",
    "字符串内容比较必须使用 equals/Objects.equals/StringUtils，不得使用 == 或 !=。",
    "",
    "### 检查点",
    "- 是否出现 str == \"xxx\" 或 str != \"xxx\"。",
    "- 是否用 trim().length() 代替空白判断且未处理 null。",
    "- 是否把空字符串和 null 混为一类但业务语义不同。",
    "",
    "### 如何检查",
    "1. 搜索新增行中的 ==、!=、isEmpty、trim。",
    "2. 判断对象是否为 String。",
    "3. 若会导致条件误判或 NPE，输出 finding。",
    "",
    "### 反例",
    "```java",
    "if (status == \"PAID\") {",
    "    return true;",
    "}",
    "```",
    "",
    "### 正例",
    "```java",
    "if (\"PAID\".equals(status)) {",
    "    return true;",
    "}",
    "```",
    "",
    "## LLDEF-MONEY-003 BigDecimal 精度和舍入误用",
    "",
    "### 规范说明",
    "金额、费率、汇率等精确数字不得使用 double/float 构造 BigDecimal，除法必须指定 scale 和 rounding mode。",
    "",
    "### 检查点",
    "- new BigDecimal(0.1)、new BigDecimal(doubleValue)。",
    "- divide 未指定 RoundingMode。",
    "- 金额比较是否用 equals 导致 scale 差异误判。",
    "",
    "### 如何检查",
    "1. 搜索 BigDecimal 构造、divide、equals。",
    "2. 判断变量是否属于金额/费率/数量精确计算。",
    "3. 给出 valueOf、字符串构造、compareTo 或明确舍入方案。",
    "",
    "### 反例",
    "```java",
    "BigDecimal fee = new BigDecimal(0.1);",
    "BigDecimal avg = total.divide(count);",
    "```",
    "",
    "### 正例",
    "```java",
    "BigDecimal fee = BigDecimal.valueOf(0.1);",
    "BigDecimal avg = total.divide(count, 2, RoundingMode.HALF_UP);",
    "```",
    "",
    "## LLDEF-COLL-004 集合遍历和修改误用",
    "",
    "### 规范说明",
    "不得在 enhanced for 循环中直接修改同一集合；集合访问必须处理空集合和越界。",
    "",
    "### 检查点",
    "- for (Item item : list) 内部 list.remove/add。",
    "- list.get(0) 前未判断空集合。",
    "- stream().findFirst().get() 未处理不存在。",
    "",
    "### 如何检查",
    "1. 搜索 remove/add/get(0)/findFirst().get。",
    "2. 判断集合来源是否可为空或可被并发修改。",
    "3. 若可能抛 ConcurrentModificationException/IndexOutOfBoundsException，输出 finding。",
    "",
    "### 反例",
    "```java",
    "for (Order order : orders) {",
    "    if (order.expired()) {",
    "        orders.remove(order);",
    "    }",
    "}",
    "```",
    "",
    "### 正例",
    "```java",
    "orders.removeIf(Order::expired);",
    "```",
    "",
    "## LLDEF-EXC-005 异常吞掉和错误返回",
    "",
    "### 规范说明",
    "不得 catch Exception 后只打印堆栈、返回 null、返回默认成功或吞掉失败语义。",
    "",
    "### 检查点",
    "- catch 块内只有 printStackTrace。",
    "- catch 后 return null/empty/true/false 掩盖失败。",
    "- 未记录业务关键上下文。",
    "",
    "### 如何检查",
    "1. 搜索 catch、printStackTrace、return null。",
    "2. 判断异常是否会影响事务、资金、状态、外部调用或数据一致性。",
    "3. 输出明确异常类型、日志上下文和异常传播建议。",
    "",
    "### 反例",
    "```java",
    "try {",
    "    paymentClient.pay(req);",
    "} catch (Exception e) {",
    "    e.printStackTrace();",
    "    return true;",
    "}",
    "```",
    "",
    "### 正例",
    "```java",
    "try {",
    "    paymentClient.pay(req);",
    "} catch (PaymentException e) {",
    "    log.error(\"payment failed orderNo={}\", req.orderNo(), e);",
    "    throw new BusinessException(\"PAYMENT_FAILED\", e);",
    "}",
    "```",
    "",
    "## LLDEF-RES-006 资源未关闭",
    "",
    "### 规范说明",
    "IO、JDBC、Stream、Response 等资源必须使用 try-with-resources 或等价生命周期管理。",
    "",
    "### 检查点",
    "- new FileInputStream、Connection.createStatement、ResultSet 未关闭。",
    "- HTTP response body 未关闭。",
    "- finally 中关闭但可能漏掉异常路径。",
    "",
    "### 如何检查",
    "1. 搜索新增资源创建语句。",
    "2. 判断是否进入 try-with-resources。",
    "3. 若没有确定关闭路径，输出 finding。",
    "",
    "### 反例",
    "```java",
    "Statement statement = connection.createStatement();",
    "ResultSet rs = statement.executeQuery(sql);",
    "```",
    "",
    "### 正例",
    "```java",
    "try (Statement statement = connection.createStatement();",
    "     ResultSet rs = statement.executeQuery(sql)) {",
    "    // consume result",
    "}",
    "```",
    "",
    "## LLDEF-CONC-007 基础并发对象误用",
    "",
    "### 规范说明",
    "不得把非线程安全对象作为 static 共享对象；不得直接使用 Executors 隐藏无界队列。",
    "",
    "### 检查点",
    "- static SimpleDateFormat。",
    "- Executors.newCachedThreadPool/newFixedThreadPool/newSingleThreadExecutor。",
    "- 非线程安全集合被多线程写入。",
    "",
    "### 如何检查",
    "1. 搜索 static、SimpleDateFormat、Executors、新线程池。",
    "2. 判断是否在请求链路、后台任务或共享组件中使用。",
    "3. 给出 DateTimeFormatter 或 ThreadPoolExecutor 有界队列建议。",
    "",
    "### 反例",
    "```java",
    "private static final SimpleDateFormat FORMAT = new SimpleDateFormat(\"yyyy-MM-dd\");",
    "ExecutorService executor = Executors.newCachedThreadPool();",
    "```",
    "",
    "### 正例",
    "```java",
    "private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ISO_LOCAL_DATE;",
    "ThreadPoolExecutor executor = new ThreadPoolExecutor(",
    "    core, max, 60, TimeUnit.SECONDS, new ArrayBlockingQueue<>(queueSize),",
    "    new ThreadPoolExecutor.CallerRunsPolicy());",
    "```",
    "",
    "## LLDEF-BOOL-008 布尔和状态判断错误",
    "",
    "### 规范说明",
    "状态枚举、布尔包装类型和多状态流转不得用脆弱判断掩盖未知状态。",
    "",
    "### 检查点",
    "- Boolean 包装类型直接 if (flag) 可能 NPE。",
    "- 状态字符串缺少 else/default 未知状态处理。",
    "- switch 新增状态没有 default 或异常处理。",
    "",
    "### 如何检查",
    "1. 搜索 Boolean、if、switch、状态字符串。",
    "2. 判断是否存在 null 或未知状态来源。",
    "3. 输出显式 Boolean.TRUE.equals 或枚举 default 处理建议。",
    "",
    "### 反例",
    "```java",
    "if (order.getPaid()) {",
    "    settle(order);",
    "}",
    "```",
    "",
    "### 正例",
    "```java",
    "if (Boolean.TRUE.equals(order.getPaid())) {",
    "    settle(order);",
    "}",
    "```",
  ].join("\n");

  db.prepare(`
    INSERT INTO custom_skills (id, project_id, skill_key, name, description, content, version, status)
    VALUES (
      'skill_java_low_level_defect_review',
      'project_default',
      'java-low-level-defect-review',
      'Java 低级缺陷检视 Skill',
      '用于低级缺陷 Agent 的标准 Skill，包含 Java 常见低级缺陷 references 规范。',
      ?,
      'v1',
      'active'
    )
    ON CONFLICT(project_id, skill_key) DO UPDATE SET
      name = excluded.name,
      description = excluded.description,
      content = excluded.content,
      version = excluded.version,
      status = excluded.status,
      updated_at = CURRENT_TIMESTAMP
  `).run(javaLowLevelSkillContent);

  const lowLevelSkillAssets = [
    {
      id: "skill_asset_java_low_level_skill_md",
      asset_path: "SKILL.md",
      asset_type: "skill",
      content: javaLowLevelSkillContent,
      executable: 0
    },
    {
      id: "skill_asset_java_low_level_reference",
      asset_path: "references/java-low-level-defects.md",
      asset_type: "reference",
      content: javaLowLevelReference,
      executable: 0
    }
  ];
  for (const asset of lowLevelSkillAssets) {
    db.prepare(`
      INSERT INTO custom_skill_assets (
        id, project_id, skill_key, asset_path, asset_type, content, executable
      )
      VALUES (?, 'project_default', 'java-low-level-defect-review', ?, ?, ?, ?)
      ON CONFLICT(project_id, skill_key, asset_path) DO UPDATE SET
        asset_type = excluded.asset_type,
        content = excluded.content,
        executable = excluded.executable,
        updated_at = CURRENT_TIMESTAMP
    `).run(asset.id, asset.asset_path, asset.asset_type, asset.content, asset.executable);
  }

  const expertProfiles = [
    {
      agent_key: "security_agent",
      display_name: "Security Agent",
      role_profile: "安全专家，聚焦认证、授权、注入、密钥、敏感数据和供应链风险。",
      responsibility_scope: "只检视安全漏洞、权限边界、输入输出信任边界、敏感信息泄漏和安全配置。",
      excluded_scope: "不检视性能调优、DDD 建模、前端交互、测试覆盖和 Redis 专项问题。"
    },
    {
      agent_key: "performance_agent",
      display_name: "Performance Agent",
      role_profile: "性能专家，聚焦吞吐、延迟、资源占用、容量风险和可扩展性。",
      responsibility_scope: "只检视慢查询、重复 IO、批处理退化、超时重试、缓存效率和资源泄漏。",
      excluded_scope: "不检视安全漏洞、领域建模、前端体验、测试完整性和 Redis 命令语义之外的问题。"
    },
    {
      agent_key: "coding_agent",
      display_name: "General Coding Agent",
      role_profile: "通用编码专家，聚焦正确性、边界条件、异常处理、类型和可维护性。",
      responsibility_scope: "只检视通用实现缺陷、兼容性、状态流转、空值、异常和代码可读性。",
      excluded_scope: "不重复检视安全、性能、DDD、前端、测试和 Redis 专项问题。"
    },
    {
      agent_key: "ddd_agent",
      display_name: "DDD Design Agent",
      role_profile: "DDD 设计专家，聚焦战略设计、限界上下文、领域概念、聚合边界、业务不变量、上下文边界和演进兼容。",
      responsibility_scope: "只检视限界上下文、领域模型、聚合、实体、值对象、应用服务、领域服务、仓储、领域事件、分层依赖、CQRS、业务规则表达、多租户隔离和演进兼容问题。",
      excluded_scope: "不检视底层安全、性能微优化、前端交互、测试覆盖和 Redis 使用细节。"
    },
    {
      agent_key: "frontend_agent",
      display_name: "Frontend Agent",
      role_profile: "前端专家，聚焦用户路径、组件状态、异步交互、可访问性和浏览器侧质量。",
      responsibility_scope: "只检视前端组件、状态、表单、错误/加载/空状态、可访问性和浏览器安全。",
      excluded_scope: "不检视后端业务规则、DDD 聚合、服务端性能、Redis 和后端测试问题。"
    },
    {
      agent_key: "test_agent",
      display_name: "Test Agent",
      role_profile: "测试专家，聚焦验证信号、断言质量、回归风险和边界场景。",
      responsibility_scope: "只检视测试覆盖、断言、回归用例、边界场景、测试数据和验证策略。",
      excluded_scope: "不检视安全漏洞、性能优化、领域设计和前端样式问题。"
    },
    {
      agent_key: "redis_agent",
      display_name: "Redis Agent",
      role_profile: "Redis 专家，聚焦缓存一致性、TTL、热点 key、分布式锁、Lua 和命令风险。",
      responsibility_scope: "只检视 Redis key 设计、缓存一致性、TTL、锁、pipeline、Lua、队列和热点风险。",
      excluded_scope: "不检视非 Redis 的数据库、通用性能、安全、DDD、前端和测试问题。"
    },
    {
      agent_key: "dependency_agent",
      display_name: "Dependency Agent",
      role_profile: "依赖审查专家，聚焦 Maven/Gradle 依赖、CVE、许可证、版本冲突和供应链风险。",
      responsibility_scope: "只检视 pom.xml、build.gradle、dependencyManagement、插件版本、CVE、license 和版本收敛问题。",
      excluded_scope: "不检视业务实现、安全代码细节、性能、DDD、Redis 或测试覆盖。"
    },
    {
      agent_key: "database_agent",
      display_name: "Database Agent",
      role_profile: "数据库专家，聚焦 SQL、Repository/Mapper、事务、索引、锁、schema、migration、数据迁移、回滚和线上发布兼容性。",
      responsibility_scope: "只检视数据库相关问题，包括数据库访问层、SQL 查询、结果映射、索引、事务、锁、schema、migration、数据回填、回滚补偿和发布兼容性。",
      excluded_scope: "不检视普通 Java 语法、安全漏洞专项、前端、Redis、依赖 CVE 或普通测试覆盖。"
    },
    {
      agent_key: "backend_agent",
      display_name: "Backend Agent",
      role_profile: "后端专家，聚焦 API 契约、服务编排、事务、幂等、错误处理和后台任务可靠性。",
      responsibility_scope: "只检视后端 API、服务层、事务边界、幂等、错误处理、后台任务和集成契约。",
      excluded_scope: "不重复检视安全漏洞、专项性能、DDD 建模、前端交互、测试覆盖和 Redis 专项问题。"
    },
    {
      agent_key: "low_level_defect_agent",
      display_name: "低级缺陷 Agent",
      role_profile: "Java 低级缺陷检视专家，专门发现空指针、集合误用、字符串比较、BigDecimal 精度、异常吞掉、资源未关闭、并发基础误用等容易被人工忽略但会造成真实线上 bug 的问题。",
      responsibility_scope: "只检视 Java/Spring 代码中的低级实现缺陷、边界条件缺失、API 误用、空值风险、异常处理错误和基础并发问题。",
      excluded_scope: "不检视架构设计、DDD 建模、性能容量专项、安全漏洞专项、依赖 CVE、前端交互和数据库专项问题。"
    }
  ];

  for (const profile of expertProfiles) {
    db.prepare(`
      INSERT INTO expert_profiles (
        id, project_id, agent_key, display_name, role_profile, responsibility_scope, excluded_scope,
        enabled, min_confidence, max_findings, max_llm_calls, max_tool_calls, output_schema_version
      )
      VALUES (?, 'project_default', ?, ?, ?, ?, ?, 1, 0.75, 12, 6, 12, 'finding_v1')
      ON CONFLICT(project_id, agent_key) DO UPDATE SET
        display_name = excluded.display_name,
        role_profile = excluded.role_profile,
        responsibility_scope = excluded.responsibility_scope,
        excluded_scope = excluded.excluded_scope,
        enabled = excluded.enabled,
        max_findings = MAX(expert_profiles.max_findings, excluded.max_findings),
        max_llm_calls = MAX(expert_profiles.max_llm_calls, excluded.max_llm_calls),
        max_tool_calls = MAX(expert_profiles.max_tool_calls, excluded.max_tool_calls)
    `).run(
      `expert_${profile.agent_key}_default`,
      profile.agent_key,
      profile.display_name,
      profile.role_profile,
      profile.responsibility_scope,
      profile.excluded_scope
    );

    const ruleDocumentId = `rule_doc_${profile.agent_key}_default`;
    const ruleContent = loadBoundStandard(
      profile.agent_key,
      profile.display_name,
      profile.responsibility_scope,
      profile.excluded_scope
    );
    db.prepare(`
      INSERT INTO rule_documents (id, project_id, name, doc_type, content, version, status)
      VALUES (?, 'project_default', ?, 'markdown', ?, 'v1', 'active')
      ON CONFLICT(id) DO UPDATE SET
        name = excluded.name,
        content = excluded.content,
        version = excluded.version,
        status = excluded.status
    `).run(
      ruleDocumentId,
      `${profile.display_name} 专属代码规范`,
      ruleContent
    );
    db.prepare(`
      INSERT OR IGNORE INTO expert_rule_bindings (id, project_id, agent_key, rule_document_id, priority)
      VALUES (?, 'project_default', ?, ?, 100)
    `).run(`binding_${profile.agent_key}_default_rules`, profile.agent_key, ruleDocumentId);
  }

  const agents = [
    {
      id: "agent_performance_default",
      agent_id: "performance_agent",
      name: "Performance Agent",
      applies_to: {
        persona: "性能专家，关注吞吐、延迟、资源消耗和可扩展性。",
        review_scope: "只检视性能、容量、资源、批量处理、超时、重试和缓存效率问题。",
        exclusive_scope: "performance",
        languages: ["python", "typescript", "javascript"],
        paths: ["backend/**", "worker/**", "services/**", "src/**"],
        triggers: ["loop_io", "query", "timeout", "batch", "cache", "large_payload"]
      },
      tools: [],
      skills: ["performance-review"],
      min_confidence: 0.73,
      max_findings: 12
    },
    {
      id: "agent_security_default",
      agent_id: "security_agent",
      name: "Security Agent",
      applies_to: {
        persona: "安全检视专家，关注攻击面、权限边界和数据泄漏路径。",
        review_scope: "只检视认证、授权、注入、敏感信息、加密随机数、安全配置和依赖安全。",
        exclusive_scope: "security",
        languages: ["python", "typescript", "javascript"],
        paths: ["backend/**", "src/**", "services/**", "worker/**"],
        triggers: ["auth", "permission", "eval", "exec", "secret", "token", "password", "webhook"]
      },
      tools: ["github.list_pull_files"],
      skills: ["security-review"],
      min_confidence: 0.72,
      max_findings: 12
    },
    {
      id: "agent_coding_default",
      agent_id: "coding_agent",
      name: "General Coding Agent",
      applies_to: {
        persona: "通用编码专家，关注实现正确性、异常、边界、类型和可维护性。",
        review_scope: "只检视通用实现质量，不覆盖安全、性能、DDD、前端、测试或 Redis 专项问题。",
        exclusive_scope: "general_coding",
        languages: ["python", "typescript", "javascript"],
        paths: ["backend/**", "worker/**", "services/**", "src/**", "scripts/**"],
        triggers: ["null", "exception", "state", "config", "compatibility", "todo"]
      },
      tools: [],
      skills: ["coding-review"],
      min_confidence: 0.74,
      max_findings: 12
    },
    {
      id: "agent_ddd_default",
      agent_id: "ddd_agent",
      name: "DDD Design Agent",
      applies_to: {
        persona: "DDD 设计专家，关注战略设计、限界上下文、领域概念、聚合边界、业务不变量、领域事件和演进兼容。",
        review_scope: "只检视领域建模、聚合、实体、值对象、领域服务、应用服务、仓储、上下文边界、领域事件、分层依赖、CQRS、多租户隔离和业务规则表达。",
        exclusive_scope: "ddd_design",
        languages: ["java", "kotlin", "python", "typescript", "javascript"],
        paths: [
          "src/main/java/**",
          "src/main/kotlin/**",
          "**/domain/**",
          "**/application/**",
          "**/service/**",
          "**/repository/**",
          "**/event/**",
          "**/interfaces/**",
          "**/controller/**",
          "backend/**",
          "services/**",
          "src/**"
        ],
        triggers: [
          "domain",
          "aggregate",
          "entity",
          "value_object",
          "valueobject",
          "repository",
          "applicationservice",
          "application service",
          "domainservice",
          "domain service",
          "bounded context",
          "context",
          "domain event",
          "eventpublisher",
          "outbox",
          "saga",
          "processmanager",
          "anti-corruption",
          "acl",
          "setstatus",
          "forcetransition",
          "override",
          "reassign",
          "merchantid",
          "tenantid"
        ]
      },
      tools: [],
      skills: ["ddd-design-review"],
      min_confidence: 0.76,
      max_findings: 12
    },
    {
      id: "agent_frontend_default",
      agent_id: "frontend_agent",
      name: "Frontend Agent",
      applies_to: {
        persona: "前端专家，关注用户操作路径、状态呈现、可访问性和浏览器侧风险。",
        review_scope: "只检视前端状态、组件、表单、异步请求、加载/错误/空状态、可访问性和浏览器安全。",
        exclusive_scope: "frontend",
        languages: ["typescript", "javascript"],
        paths: ["src/frontend/**", "frontend/**", "web/**", "**/*.tsx", "**/*.jsx", "**/*.vue"],
        triggers: ["react", "hook", "form", "loading", "error_state", "accessibility", "html"]
      },
      tools: [],
      skills: ["frontend-review"],
      min_confidence: 0.73,
      max_findings: 12
    },
    {
      id: "agent_test_default",
      agent_id: "test_agent",
      name: "Test Agent",
      applies_to: {
        persona: "测试专家，关注验证信号、回归风险和边界场景。",
        review_scope: "只检视测试覆盖、断言、回归用例、边界场景和验证策略。",
        exclusive_scope: "test_coverage",
        languages: ["python", "typescript", "javascript"],
        paths: ["**/*"],
        triggers: ["missing_test", "regression", "boundary", "assertion", "coverage"]
      },
      tools: [],
      skills: ["test-review"],
      min_confidence: 0.7,
      max_findings: 12
    },
    {
      id: "agent_redis_default",
      agent_id: "redis_agent",
      name: "Redis Agent",
      applies_to: {
        persona: "Redis 专家，关注缓存一致性、TTL、热点 key、分布式锁和 Redis 命令风险。",
        review_scope: "只检视 Redis、缓存、分布式锁、队列、Lua、pipeline、TTL 和 key 设计问题。",
        exclusive_scope: "redis",
        languages: ["python", "typescript", "javascript"],
        paths: ["backend/**", "worker/**", "services/**", "src/**"],
        triggers: ["redis", "cache", "ttl", "lock", "pipeline", "lua", "keys"]
      },
      tools: [],
      skills: ["redis-review"],
      min_confidence: 0.74,
      max_findings: 12
    },
    {
      id: "agent_dependency_default",
      agent_id: "dependency_agent",
      name: "Dependency Agent",
      applies_to: {
        persona: "依赖审查专家，关注 Maven/Gradle 依赖、CVE、许可证、版本冲突和供应链风险。",
        review_scope: "只检视 pom.xml、build.gradle、dependencyManagement、插件版本、CVE、license 和版本收敛问题。",
        exclusive_scope: "dependency",
        languages: ["java", "xml", "kotlin", "groovy"],
        paths: ["pom.xml", "**/pom.xml", "build.gradle", "**/build.gradle", "build.gradle.kts", "**/build.gradle.kts"],
        triggers: ["dependency", "pom.xml", "gradle", "version", "cve", "license"]
      },
      tools: [],
      skills: ["dependency-review"],
      min_confidence: 0.74,
      max_findings: 12
    },
    {
      id: "agent_database_default",
      agent_id: "database_agent",
      name: "Database Agent",
      applies_to: {
        persona: "数据库专家，关注 SQL、Repository/Mapper、事务、索引、锁、schema、Flyway/Liquibase、数据迁移、回滚和线上发布兼容性。",
        review_scope: "只检视数据库相关问题，包括数据库访问层、SQL 查询、结果映射、索引、事务、锁、schema、migration、数据回填、回滚补偿和发布兼容性。",
        exclusive_scope: "database",
        languages: ["sql", "java", "xml", "yaml"],
        paths: ["src/main/java/**/repository/**", "src/main/java/**/mapper/**", "src/main/resources/db/migration/**", "src/main/resources/changelog/**", "**/*Mapper.xml", "**/*.sql"],
        triggers: ["select ", "insert ", "update ", "delete ", "join ", "order by", "group by", "jdbc", "jdbctemplate", "repository", "mapper", "mybatis", "hibernate", "jpa", "@transactional", "alter table", "drop column", "drop table", "not null", "create index", "flyway", "liquibase"]
      },
      tools: [],
      skills: ["database-review"],
      min_confidence: 0.76,
      max_findings: 12
    },
    {
      id: "agent_backend_default",
      agent_id: "backend_agent",
      name: "Backend Agent",
      applies_to: {
        persona: "后端专家，关注 API 契约、服务编排、事务、幂等和后台任务可靠性。",
        review_scope: "只检视后端 API、服务层、事务边界、幂等、错误处理、后台任务和集成契约。",
        exclusive_scope: "backend",
        languages: ["java", "python", "typescript", "javascript"],
        paths: ["src/main/java/**", "backend/**", "worker/**", "services/**", "src/backend/**"],
        triggers: ["api", "controller", "requestbody", "transaction", "idempotency", "job", "queue", "retry", "exception"]
      },
      tools: [],
      skills: ["backend-review"],
      min_confidence: 0.74,
      max_findings: 12
    },
    {
      id: "agent_low_level_defect_default",
      agent_id: "low_level_defect_agent",
      name: "低级缺陷 Agent",
      applies_to: {
        persona: "Java 低级缺陷检视专家，专门发现 NPE、集合误用、字符串比较、BigDecimal 精度、异常吞掉、资源未关闭和基础并发误用。",
        review_scope: "只检视 Java/Spring 代码中的低级实现缺陷、边界条件缺失、API 误用、空值风险、异常处理错误和基础并发问题。",
        excluded_scope: "不检视架构设计、DDD 建模、性能容量专项、安全漏洞专项、依赖 CVE、前端交互和数据库专项问题。",
        custom_prompt: "检视时优先读取绑定 Skill 的 references/java-low-level-defects.md，逐条检查当前 MR diff。只输出有精确新增行号、能导致真实 bug 或线上排障困难的低级缺陷；每个问题必须包含触发规则、证据、影响和建议修改代码。",
        exclusive_scope: "low_level_defect",
        languages: ["java"],
        paths: ["src/main/java/**", "**/*.java"],
        triggers: ["null", "npe", "equals", "bigdecimal", "optional", "collection", "exception", "close", "stream", "simpledateformat", "executors"]
      },
      tools: [],
      skills: ["java-low-level-defect-review"],
      min_confidence: 0.75,
      max_findings: 12
    }
  ];

  for (const agent of agents) {
    db.prepare(`
      INSERT OR IGNORE INTO agent_configs (
        id, project_id, agent_id, display_name, enabled, applies_to_json, tools_json,
        skills_json, rule_sets_json, min_confidence, max_findings_per_mr
      )
      VALUES (?, 'project_default', ?, ?, 1, ?, ?, ?, '["rules_project_default_engineering"]', ?, ?)
      ON CONFLICT(project_id, agent_id) DO UPDATE SET
        display_name = excluded.display_name,
        applies_to_json = excluded.applies_to_json,
        tools_json = excluded.tools_json,
        skills_json = excluded.skills_json,
        rule_sets_json = excluded.rule_sets_json,
        enabled = excluded.enabled,
        min_confidence = excluded.min_confidence,
        max_findings_per_mr = excluded.max_findings_per_mr,
        updated_at = CURRENT_TIMESTAMP
    `).run(
      agent.id,
      agent.agent_id,
      agent.name,
      JSON.stringify(agent.applies_to),
      JSON.stringify(agent.tools),
      JSON.stringify(agent.skills),
      agent.min_confidence,
      agent.max_findings
    );

    for (const tool of agent.tools) {
      db.prepare(`
        INSERT INTO expert_tool_bindings (id, project_id, agent_key, tool_name, permission_level, max_calls, enabled)
        VALUES (?, 'project_default', ?, ?, 'read_only', 5, 1)
        ON CONFLICT(project_id, agent_key, tool_name) DO UPDATE SET
          permission_level = excluded.permission_level,
          max_calls = excluded.max_calls,
          enabled = excluded.enabled
      `).run(`tool_binding_${agent.agent_id}_${tool.replace(/[^a-zA-Z0-9]+/g, "_")}`, agent.agent_id, tool);
    }
  }

  db.prepare(`
    INSERT INTO expert_skill_bindings (id, project_id, agent_key, skill_key, priority, enabled)
    VALUES (
      'skill_binding_low_level_defect_default',
      'project_default',
      'low_level_defect_agent',
      'java-low-level-defect-review',
      100,
      1
    )
    ON CONFLICT(project_id, agent_key, skill_key) DO UPDATE SET
      priority = excluded.priority,
      enabled = excluded.enabled
  `).run();
}
