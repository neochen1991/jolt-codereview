from __future__ import annotations

import re
from typing import Any

from tools.tool_normalizer import normalize_tool_finding


def _added_lines(patch: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    new_line = 0
    for raw in patch.splitlines():
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) - 1 if match else new_line
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            new_line += 1
            result.append((new_line, raw[1:]))
        elif raw.startswith(" ") and not raw.startswith(("diff --git", "index ")):
            new_line += 1
    return result


def _text(lines: list[tuple[int, str]]) -> str:
    return "\n".join(line for _, line in lines)


def _finding(
    *,
    agent_id: str,
    severity: str,
    confidence: float,
    file_path: str,
    line: int,
    title: str,
    description: str,
    recommendation: str,
    suggested_code: str,
    evidence: str,
    rule_id: str,
    tool_name: str = "java_web_static",
) -> dict[str, Any]:
    return normalize_tool_finding(
        {
            "severity": severity,
            "confidence": confidence,
            "agent_id": agent_id,
            "head_sha": "",
            "file_path": file_path,
            "line_start": line,
            "line_end": line,
            "title": title,
            "problem_description": description,
            "recommendation": recommendation,
            "suggested_code": suggested_code,
            "evidence": evidence.strip()[:500],
            "tool_name": tool_name,
            "tool_rule_id": rule_id,
            "covered_rules": [rule_id],
            "skipped_rules": [],
        }
    )


def scan_java_web_files(files: list[Any], head_sha: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    java_business_added = False
    has_test_file = any("test" in getattr(item, "filename", "").lower() for item in files)
    for changed in files:
        file_path = getattr(changed, "filename", "")
        lines = _added_lines(getattr(changed, "patch", ""))
        content = _text(lines)
        lowered_path = file_path.lower()
        if file_path.endswith(".java"):
            java_business_added = java_business_added or "src/main/java/" in lowered_path
            findings.extend(_scan_java_file(file_path, lines, content))
        if lowered_path.endswith(".xml"):
            findings.extend(_scan_xml_file(file_path, lines, content))
        if lowered_path.endswith((".yml", ".yaml", ".properties")):
            findings.extend(_scan_spring_config(file_path, lines))
        if lowered_path.endswith(("pom.xml", "build.gradle", "build.gradle.kts")):
            findings.extend(_scan_dependency_file(file_path, lines, content))
        if "/db/migration/" in lowered_path or "/changelog/" in lowered_path or lowered_path.endswith(".sql"):
            findings.extend(_scan_database_changes(file_path, lines))
    if java_business_added and not has_test_file:
        first_java = next((item for item in files if getattr(item, "filename", "").endswith(".java")), None)
        if first_java:
            first_lines = _added_lines(getattr(first_java, "patch", ""))
            line = first_lines[0][0] if first_lines else 1
            findings.append(
                _finding(
                    agent_id="test_agent",
                    severity="medium",
                    confidence=0.88,
                    file_path=getattr(first_java, "filename", ""),
                    line=line,
                    title="新增 Java 业务代码缺少测试文件",
                    description="MR 新增 Java 业务代码，但 diff 中没有对应测试文件，关键业务路径缺少回归验证信号。",
                    recommendation="补充单元测试或 Spring slice/integration 测试，覆盖正常路径、错误路径和边界场景。",
                    suggested_code='''@Test
void shouldCoverNewBusinessScenario() {
    // arrange
    // act
    // assert key state, response, and side effects
}''',
                    evidence="新增 src/main/java 代码且未发现 test 文件变更。",
                    rule_id="TEST-COVER-001",
                )
            )
    for item in findings:
        item["head_sha"] = head_sha
    return findings


def _scan_java_file(file_path: str, lines: list[tuple[int, str]], content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered_content = content.lower()
    for line_no, line in lines:
        lowered = line.lower()
        findings.extend(_scan_alibaba_huawei_line_rules(file_path, line_no, line, lowered))
        if "@postmapping" in lowered or "@putmapping" in lowered:
            findings.extend(_maybe_missing_valid(file_path, lines, line_no))
            findings.extend(_maybe_missing_idempotency_guard(file_path, lines, content, line_no))
        if "statement.executequery(" in lowered or "statement.executeupdate(" in lowered:
            if "+" in line:
                findings.append(
                    _finding(
                        agent_id="security_agent",
                        severity="high",
                        confidence=0.92,
                        file_path=file_path,
                        line=line_no,
                        title="JDBC SQL 拼接存在注入风险",
                        description="新增代码将外部输入拼接进 SQL 后执行，攻击者可构造参数绕过查询条件或读取敏感数据。",
                        recommendation="改用 PreparedStatement 参数绑定，动态排序字段必须使用白名单。",
                        suggested_code='''PreparedStatement ps = connection.prepareStatement(
    "select * from payments where user_id = ?"
);
ps.setString(1, userId);
ResultSet rs = ps.executeQuery();''',
                        evidence=line,
                        rule_id="SEC-INJECT-003",
                    )
                )
            if "select" in lowered and " limit " not in lowered and " pageable" not in lowered_content:
                findings.append(
                    _finding(
                        agent_id="performance_agent",
                        severity="medium",
                        confidence=0.82,
                        file_path=file_path,
                        line=line_no,
                        title="查询缺少分页或结果上限",
                        description="请求路径直接执行未分页 SELECT，数据量增长后可能导致慢查询、长事务或接口超时。",
                        recommendation="为查询增加分页、LIMIT 或游标边界，禁止在接口中返回无上限结果集。",
                        suggested_code='''PreparedStatement ps = connection.prepareStatement(
    "select id, amount from payments where user_id = ? order by id desc limit ?"
);
ps.setString(1, userId);
ps.setInt(2, pageSize);''',
                        evidence=line,
                        rule_id="PERF-QUERY-001",
                    )
                )
        if "private static final string" in lowered and re.search(r"(password|secret|token|key)", lowered):
            findings.append(
                _finding(
                    agent_id="security_agent",
                    severity="high",
                    confidence=0.88,
                    file_path=file_path,
                    line=line_no,
                    title="硬编码敏感凭据进入代码",
                    description="新增 Java 常量中出现 password/secret/token/key 等敏感字段，可能导致凭据泄露和长期复用风险。",
                    recommendation="移除硬编码敏感值，改用 secret store、环境变量或配置中心密文，并轮换已暴露凭据。",
                    suggested_code='''private final String adminPassword = secretProvider.get("payment.admin-password");''',
                    evidence=line,
                    rule_id="SEC-SECRET-004",
                )
            )
        if ".keys(" in lowered and "redis" in lowered:
            findings.append(
                _finding(
                    agent_id="redis_agent",
                    severity="high",
                    confidence=0.91,
                    file_path=file_path,
                    line=line_no,
                    title="生产路径使用 Redis KEYS 命令",
                    description="Redis KEYS 会扫描整个 keyspace，在线上热路径可能阻塞 Redis 实例并放大故障。",
                    recommendation="改用 SCAN 分批处理，或维护业务索引集合避免模糊扫描。",
                    suggested_code='''ScanOptions options = ScanOptions.scanOptions()
    .match("payment:*:lock")
    .count(500)
    .build();''',
                    evidence=line,
                    rule_id="REDIS-CMD-003",
                )
            )
        if "opsforvalue().set(" in lowered and "duration" not in lowered and "timeout" not in lowered:
            findings.append(
                _finding(
                    agent_id="redis_agent",
                    severity="medium",
                    confidence=0.86,
                    file_path=file_path,
                    line=line_no,
                    title="Redis 缓存写入缺少 TTL",
                    description="缓存写入没有设置过期时间，可能导致脏数据长期存在或 key 数量持续膨胀。",
                    recommendation="为缓存写入设置明确 TTL，永久 key 需要说明清理机制。",
                    suggested_code='''redisTemplate.opsForValue().set(
    key,
    response,
    Duration.ofMinutes(30)
);''',
                    evidence=line,
                    rule_id="REDIS-TTL-002",
                )
            )
        if "catch (exception" in lowered or "catch (throwable" in lowered:
            findings.append(
                _finding(
                    agent_id="database_agent",
                    severity="medium",
                    confidence=0.82,
                    file_path=file_path,
                    line=line_no,
                    title="异常捕获范围过宽",
                    description="新增代码捕获 Exception/Throwable，容易吞掉不同失败语义并影响事务、审计或错误处理。",
                    recommendation="捕获明确异常类型，记录业务上下文，并按业务语义抛出或返回错误。",
                    suggested_code='''} catch (SQLException e) {
    log.error("payment search failed userId={}", userId, e);
    throw new BusinessException("PAYMENT_QUERY_FAILED", e);
}''',
                    evidence=line,
                    rule_id="CODE-EXC-003",
                )
            )
        if re.search(r"\b(?:String\s+)?\w+\s*=\s*String\.valueOf\(\s*payload\.get\(", line):
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="medium",
                    confidence=0.8,
                    file_path=file_path,
                    line=line_no,
                    title="Map 入参字段缺少显式空值和类型校验",
                    description="从 Map 中直接读取业务字段并转换为 String，会把缺失字段掩盖为字符串 null，后续 SQL、缓存 key 或审计记录可能产生脏数据。",
                    recommendation="使用 DTO + Bean Validation，或对 Map 字段做显式 required/type 校验后再进入业务逻辑。",
                    suggested_code='''String userId = requireText(payload, "userId");

private String requireText(Map<String, Object> payload, String field) {
    Object value = payload.get(field);
    if (!(value instanceof String text) || text.isBlank()) {
        throw new BadRequestException(field + " is required");
    }
    return text;
}''',
                    evidence=line,
                    rule_id="CODE-NULL-001",
                )
            )
        if "e.getmessage()" in lowered and ("response.put" in lowered or "return" in lowered):
            findings.append(
                _finding(
                    agent_id="security_agent",
                    severity="medium",
                    confidence=0.84,
                    file_path=file_path,
                    line=line_no,
                    title="异常详情直接回写响应",
                    description="将异常 message 直接返回给客户端可能泄漏 SQL、路径、类名或内部依赖信息。",
                    recommendation="对外返回稳定错误码和脱敏提示，详细异常只写服务端日志。",
                    suggested_code='''response.put("error", "PAYMENT_QUERY_FAILED");''',
                    evidence=line,
                    rule_id="SEC-SECRET-004:ERROR_RESPONSE",
                )
            )
        if "@autowired" in lowered:
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="medium",
                    confidence=0.84,
                    file_path=file_path,
                    line=line_no,
                    title="Spring 字段注入降低可测试性",
                    description="字段注入隐藏依赖，降低不可变性和单元测试可控性。",
                    recommendation="改用构造器注入，并将依赖声明为 final。",
                    suggested_code='''private final PaymentService paymentService;

public PaymentController(PaymentService paymentService) {
    this.paymentService = paymentService;
}''',
                    evidence=line,
                    rule_id="JOLT_JAVA_FIELD_AUTOWIRED",
                )
            )
        if re.search(r"\breturn\s+null\s*;", line) and re.search(r"\b(List|Set|Map|Collection|Page|Optional)\s*[<\w,\s>]*\s+\w+\s*\(", content):
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="medium",
                    confidence=0.78,
                    file_path=file_path,
                    line=line_no,
                    title="集合/Optional 返回值不应返回 null",
                    description="集合、Map、Optional 或分页类型返回 null 会把空结果和异常状态混淆，调用方容易出现 NPE。",
                    recommendation="集合返回空集合，Optional 返回 Optional.empty()，分页返回空 Page。",
                    suggested_code='''return Collections.emptyList();''',
                    evidence=line,
                    rule_id="ALI-RETURN-001",
                )
            )
        if ".printstacktrace(" in lowered:
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="medium",
                    confidence=0.83,
                    file_path=file_path,
                    line=line_no,
                    title="禁止直接调用 printStackTrace",
                    description="直接 printStackTrace 会绕过统一日志、链路追踪和脱敏策略，线上问题不可检索也可能泄露敏感信息。",
                    recommendation="使用项目统一日志框架记录上下文，禁止直接输出堆栈到标准错误。",
                    suggested_code='''log.error("payment operation failed orderNo={}", orderNo, e);''',
                    evidence=line,
                    rule_id="ALI-EXC-002",
                )
            )
        if "system.out.print" in lowered or "system.err.print" in lowered:
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="low",
                    confidence=0.82,
                    file_path=file_path,
                    line=line_no,
                    title="生产代码禁止使用 System.out/System.err",
                    description="标准输出无法承载结构化日志、日志级别、traceId 和脱敏策略，生产排障困难。",
                    recommendation="改用 SLF4J/Logback 等统一日志框架，并带上必要业务上下文。",
                    suggested_code='''private static final Logger log = LoggerFactory.getLogger(CurrentClass.class);
log.info("payment status changed orderNo={}", orderNo);''',
                    evidence=line,
                    rule_id="ALI-LOG-001",
                )
            )
    if "class PaymentAggregate" in content and "Map<String, Object>" in content:
        line_no = next((no for no, line in lines if "Map<String, Object>" in line), 1)
        findings.append(
            _finding(
                agent_id="ddd_agent",
                severity="medium",
                confidence=0.84,
                file_path=file_path,
                line=line_no,
                title="领域对象使用弱类型 Map 承载业务概念",
                description="聚合内部直接保存 Map 会让状态和业务不变量散落，调用方可写入任意字段导致领域模型失控。",
                recommendation="提炼明确字段和值对象，由聚合方法维护状态变更和业务不变量。",
                suggested_code='''class PaymentAggregate {
    private PaymentStatus status;

    public void changeStatus(PaymentStatus nextStatus) {
        this.status = nextStatus;
    }
}''',
                evidence="PaymentAggregate 使用 Map<String, Object> json 保存领域状态。",
                rule_id="DDD-VO-002",
            )
        )
    findings.extend(_scan_class_level_rules(file_path, lines, content, lowered_content))
    if re.search(r"public\s+\w+[<>,\s\w]*\s+\w*(save|update|delete|insert|pay|cancel)\w*\(", content, re.I):
        if "@Transactional" not in content and ("Repository" in content or ".save(" in content or "markPaid" in content):
            line_no = next((no for no, line in lines if re.search(r"\b(save|update|delete|insert|pay|cancel)\b", line, re.I)), 1)
            findings.append(
                _finding(
                    agent_id="backend_agent",
                    severity="medium",
                    confidence=0.8,
                    file_path=file_path,
                    line=line_no,
                    title="状态变更缺少明确事务边界",
                    description="新增写操作或状态变更未看到 @Transactional 事务边界，多个持久化副作用可能出现部分成功。",
                    recommendation="在应用服务写方法上声明事务，并避免在事务内执行慢外部调用。",
                    suggested_code='''@Transactional
public void updateStatus(...) {
    // keep all state changes in one transaction boundary
}''',
                    evidence="新增疑似 save/update/delete/状态变更方法但文件中未出现 @Transactional。",
                    rule_id="BE-TX-002",
                )
            )
    if "while (rs.next())" in lowered_content and re.search(r"\b(response|result|items)\.put\(", content):
        line_no = next((no for no, line in lines if "while (rs.next())" in line), 1)
        findings.append(
            _finding(
                agent_id="performance_agent",
                severity="medium",
                confidence=0.82,
                file_path=file_path,
                line=line_no,
                title="结果集无上限累积到内存对象",
                description="接口将 ResultSet 全量循环写入 Map/集合，缺少分页或最大行数保护，数据放大后可能造成高内存占用。",
                recommendation="限制单次读取行数，使用分页返回，或采用流式处理并设置最大结果窗口。",
                suggested_code='''int count = 0;
while (rs.next() && count++ < pageSize) {
    response.put(rs.getString("id"), rs.getBigDecimal("amount"));
}''',
                evidence="while (rs.next()) 将数据库结果持续写入 response。",
                rule_id="PERF-MEM-004",
            )
        )
    return findings


def _scan_alibaba_huawei_line_rules(file_path: str, line_no: int, line: str, lowered: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if re.search(r"\b(class|interface|enum|record)\s+[_$]|[_$]\s*\{", line) or re.search(r"\b(?:String|Long|Integer|Boolean|BigDecimal|List|Map|Set)\s+[_$]\w*|\b(?:String|Long|Integer|Boolean|BigDecimal|List|Map|Set)\s+\w*[_$]\b", line):
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="low",
                confidence=0.78,
                file_path=file_path,
                line=line_no,
                title="命名不应以下划线或美元符号开始/结束",
                description="阿里 Java 编码规约要求标识符不得以下划线或美元符号开始或结束，避免可读性差和工具生成命名冲突。",
                recommendation="使用清晰英文语义命名，不使用 `_` 或 `$` 作为首尾字符。",
                suggested_code='''private String orderNo;''',
                evidence=line,
                rule_id="ALI-NAMING-001",
            )
        )
    if re.search(r"[\u4e00-\u9fff]", line) and re.search(r"\b(class|interface|enum|record|void|String|Long|Integer|Boolean|BigDecimal)\b", line):
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="low",
                confidence=0.78,
                file_path=file_path,
                line=line_no,
                title="代码标识符不应使用中文或拼音混合命名",
                description="阿里 Java 编码规约禁止中文、拼音或中英文混合命名，业务含义应使用准确英文表达。",
                recommendation="将类名、方法名、字段名改为准确英文，领域词可通过统一术语表维护。",
                suggested_code='''private String paymentChannel;''',
                evidence=line,
                rule_id="ALI-NAMING-002",
            )
        )
    if re.search(r"new\s+BigDecimal\s*\(\s*(?:\d+\.\d+|[0-9]+[dDfF]|\w+\s*)\)", line):
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="medium",
                confidence=0.86,
                file_path=file_path,
                line=line_no,
                title="BigDecimal 不应使用 double/float 构造",
                description="使用 double/float 构造 BigDecimal 会引入二进制浮点误差，支付金额计算可能不准确。",
                recommendation="使用字符串构造或 BigDecimal.valueOf，并统一金额精度和舍入模式。",
                suggested_code='''BigDecimal amount = new BigDecimal("0.01");
// or
BigDecimal amount = BigDecimal.valueOf(value);''',
                evidence=line,
                rule_id="ALI-BIGDECIMAL-001",
            )
        )
    if "executors.newfixedthreadpool" in lowered or "executors.newcachedthreadpool" in lowered or "executors.newsinglethreadexecutor" in lowered or "executors.newscheduledthreadpool" in lowered:
        findings.append(
            _finding(
                agent_id="performance_agent",
                severity="medium",
                confidence=0.85,
                file_path=file_path,
                line=line_no,
                title="禁止直接使用 Executors 创建线程池",
                description="Executors 工厂方法可能隐藏无界队列或过大线程上限，流量突增时导致 OOM 或线程失控。",
                recommendation="显式使用 ThreadPoolExecutor，配置有界队列、线程数、拒绝策略和线程命名。",
                suggested_code='''ThreadPoolExecutor executor = new ThreadPoolExecutor(
    corePoolSize,
    maxPoolSize,
    60L,
    TimeUnit.SECONDS,
    new ArrayBlockingQueue<>(queueSize),
    new ThreadPoolExecutor.CallerRunsPolicy()
);''',
                evidence=line,
                rule_id="ALI-CONCURRENCY-001",
            )
        )
    if re.search(r"new\s+SimpleDateFormat\s*\(", line) and re.search(r"\b(static|public\s+static|private\s+static)", line):
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="medium",
                confidence=0.84,
                file_path=file_path,
                line=line_no,
                title="SimpleDateFormat 不应作为 static 共享对象",
                description="SimpleDateFormat 非线程安全，static 共享后在并发请求下可能解析/格式化出错。",
                recommendation="使用 DateTimeFormatter，或使用 ThreadLocal 包装旧 API。",
                suggested_code='''private static final DateTimeFormatter FORMATTER =
    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");''',
                evidence=line,
                rule_id="ALI-CONCURRENCY-002",
            )
        )
    if "thread.sleep(" in lowered and ("/controller/" in file_path.lower() or "/service/" in file_path.lower() or "controller" in file_path.lower()):
        findings.append(
            _finding(
                agent_id="performance_agent",
                severity="medium",
                confidence=0.78,
                file_path=file_path,
                line=line_no,
                title="业务请求路径不应使用 Thread.sleep",
                description="在 Controller/Service 请求链路中 sleep 会阻塞容器线程，降低吞吐并放大超时风险。",
                recommendation="使用异步调度、重试组件或限流退避机制，不要阻塞请求线程。",
                suggested_code='''retryTemplate.execute(context -> paymentClient.query(orderNo));''',
                evidence=line,
                rule_id="HW-PERF-001",
            )
        )
    if re.search(r"\b(Random|java\.util\.Random)\s+\w+\s*=", line) and ("security" in file_path.lower() or "token" in lowered or "password" in lowered):
        findings.append(
            _finding(
                agent_id="security_agent",
                severity="medium",
                confidence=0.8,
                file_path=file_path,
                line=line_no,
                title="安全令牌场景不应使用 java.util.Random",
                description="Random 不适合生成安全令牌、验证码或密码相关随机值，可能被预测。",
                recommendation="使用 SecureRandom 或框架提供的安全随机能力。",
                suggested_code='''private static final SecureRandom SECURE_RANDOM = new SecureRandom();''',
                evidence=line,
                rule_id="HW-SEC-001",
            )
        )
    if re.search(r"new\s+SecureRandom\s*\(\s*(new\s+byte\s*\[\]\s*\{|\"[^\"]*\"|[A-Za-z_][A-Za-z0-9_]*\.getBytes\s*\()", line) or re.search(r"\.setSeed\s*\(\s*(new\s+byte\s*\[\]\s*\{|\"[^\"]*\"|\d+L?)", line):
        findings.append(
            _finding(
                agent_id="security_agent",
                severity="high",
                confidence=0.9,
                file_path=file_path,
                line=line_no,
                title="SecureRandom 使用固定种子",
                description="SecureRandom 被固定字节、字符串或常量重新播种后会产生可预测序列，用于 token、抽样、风控或审计时会削弱随机性。",
                recommendation="不要传入固定种子或调用 setSeed 固定值；安全随机直接使用系统熵初始化，业务抽样使用可审计的稳定哈希。",
                suggested_code='''private static final SecureRandom SECURE_RANDOM = new SecureRandom();

public String nextReviewToken() {
    byte[] bytes = new byte[32];
    SECURE_RANDOM.nextBytes(bytes);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
}''',
                evidence=line,
                rule_id="HW-SEC-001",
            )
        )
    return findings


def _scan_class_level_rules(
    file_path: str,
    lines: list[tuple[int, str]],
    content: str,
    lowered_content: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lower_path = file_path.lower()
    if "/controller/" in lower_path and re.search(r"\b\w*(Repository|Mapper)\b", content):
        line_no = next((no for no, line in lines if "Repository" in line or "Mapper" in line), 1)
        findings.append(
            _finding(
                agent_id="backend_agent",
                severity="medium",
                confidence=0.82,
                file_path=file_path,
                line=line_no,
                title="Controller 不应直接依赖 Repository/Mapper",
                description="Controller 直接访问持久层会绕过应用服务的事务、鉴权、幂等和领域编排，破坏分层边界。",
                recommendation="Controller 只依赖应用服务，由 Service 编排 Repository/Mapper 和领域逻辑。",
                suggested_code='''private final PaymentService paymentService;''',
                evidence="Controller 中出现 Repository/Mapper 依赖。",
                rule_id="HW-LAYER-001",
            )
        )
    if (
        ("/application/" in lower_path or "/service/" in lower_path)
        and re.search(r"\.(setStatus|setMerchantId|setTenantId|setAmount|setOwnerId|setState)\s*\(", content)
        and re.search(r"(force|override|transition|reassign|PaymentStatus\.valueOf|Status\.valueOf)", content, re.I)
    ):
        line_no = next((no for no, line in lines if re.search(r"\.(setStatus|setMerchantId|setTenantId|setAmount|setOwnerId|setState)\s*\(", line)), 1)
        findings.append(
            _finding(
                agent_id="ddd_agent",
                severity="high",
                confidence=0.84,
                file_path=file_path,
                line=line_no,
                title="应用服务直接改写聚合状态或归属",
                description="应用服务通过 setter/force/override 直接改写聚合核心状态或租户商户归属，聚合无法维护状态机和业务不变量。",
                recommendation="将状态流转、归属变更和校验收敛到聚合业务方法或领域服务，应用服务只编排命令、事务和端口调用。",
                suggested_code='''payment.transferMerchant(new MerchantId(merchantId), transferPolicy);
payment.transitionTo(PaymentStatus.fromExternal(nextStatus), transitionPolicy);
paymentRepository.save(payment);''',
                evidence="应用服务中出现聚合 setter 与 force/override/transition/reassign 状态流转组合。",
                rule_id="DDD-AGG-002",
            )
        )
    preview_start = next(
        (
            no
            for no, line in lines
            if re.search(r"\bpreview[A-Za-z0-9_]*\s*\([^)]*(merchantId|tenantId|userId|accountId)[^)]*\)", line, re.I)
        ),
        None,
    )
    preview_findall_line = next((no for no, line in lines if preview_start and preview_start <= no <= preview_start + 80 and "findAll(" in line), None)
    preview_window = "\n".join(line for no, line in lines if preview_start and preview_start <= no <= preview_start + 80)
    if preview_start and preview_findall_line and re.search(r"\b(totalLoaded|first[A-Za-z0-9_]*Id|Map\.of|put\s*\()", preview_window):
        line_no = preview_findall_line
        findings.append(
            _finding(
                agent_id="security_agent",
                severity="high",
                confidence=0.88,
                file_path=file_path,
                line=line_no,
                title="预览接口返回全局数据摘要",
                description="带有商户、租户或用户入参的 preview/summary 方法调用 findAll 后返回全局数量或首条资源 ID，可能泄露跨租户数据。",
                recommendation="按当前主体和资源归属过滤查询，只返回该主体可访问的数据，不返回全局总量或无关资源标识。",
                suggested_code='''List<PaymentOrder> orders = paymentRepository.findByMerchantId(merchantId, PageRequest.of(0, 20));
return Map.of(
    "merchantId", merchantId,
    "totalLoaded", orders.size()
);''',
                evidence="preview/summary 方法中出现 findAll 并返回 total/first id 类摘要字段。",
                rule_id="SEC-AUTHZ-002",
            )
        )
    if (
        re.search(r"\b(class\s+\w*(Policy|Rule|Strategy)\w*|new\s+\w*(Policy|Rule|Strategy)\w*\s*\([^)]*priority|int\s+priority|Integer\s+priority)", content)
        and re.search(r"\b(getPriority\s*\(\s*\)|this\.priority\s*=|priority\s*=)", content)
        and not re.search(r"\b(sorted|sort|max|min|Comparator\.[A-Za-z]*comparing|Order\.by)\s*\([^)]*(priority|getPriority)", content)
    ):
        line_no = next((no for no, line in lines if "priority" in line or "getPriority" in line), 1)
        findings.append(
            _finding(
                agent_id="ddd_agent",
                severity="medium",
                confidence=0.86,
                file_path=file_path,
                line=line_no,
                title="策略优先级字段未参与决策选择",
                description="Policy/Rule/Strategy 接收或保存 priority，但当前变更中没有看到排序、选择、冲突解决或决策审计使用该字段，策略优先级可能形同虚设。",
                recommendation="在策略选择流程中显式按 priority/version/effectiveAt 进行排序或冲突解决，并在决策日志中记录命中的策略优先级。",
                suggested_code='''RiskPolicy selected = policies.stream()
    .filter(policy -> policy.appliesTo(order))
    .sorted(Comparator.comparingInt(RiskPolicy::getPriority).reversed())
    .findFirst()
    .orElseThrow(() -> new PolicyNotFoundException(merchantId));''',
                evidence="策略对象出现 priority/getPriority，但未发现排序或选择逻辑使用该字段。",
                rule_id="DDD-POLICY-001",
            )
        )
    if ("/domain/" in lower_path and "repository" in lower_path) or lower_path.endswith("repository.java"):
        if re.search(r"\b(QueryWrapper|EntityManager|Pageable|Specification|CriteriaBuilder|SqlSession|Wrapper<|Example)\b", content):
            line_no = next((no for no, line in lines if re.search(r"\b(QueryWrapper|EntityManager|Pageable|Specification|CriteriaBuilder|SqlSession|Wrapper<|Example)\b", line)), 1)
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    severity="medium",
                    confidence=0.82,
                    file_path=file_path,
                    line=line_no,
                    title="领域 Repository 接口泄漏 ORM 或查询实现细节",
                    description="领域层仓储接口暴露 QueryWrapper、EntityManager、Pageable 等基础设施类型，会让领域层依赖存储实现并削弱聚合边界。",
                    recommendation="领域 Repository 只暴露业务值对象、聚合根和业务查询条件；复杂查询放入 query service/read model。",
                    suggested_code='''Optional<PaymentOrder> find(PaymentId paymentId);
List<PaymentSummary> findPendingPayments(MerchantId merchantId);''',
                    evidence="领域 Repository 签名中出现 ORM/查询基础设施类型。",
                    rule_id="DDD-REPO-002",
                )
            )
    if lower_path.endswith("event.java") or "/event/" in lower_path:
        event_class = re.search(r"\b(class|record)\s+([A-Z][A-Za-z0-9_]*Event)\b", content)
        if event_class and re.match(r"(Pay|Create|Update|Delete|Cancel|Refund|Set|Sync)[A-Z].*Event", event_class.group(2)):
            line_no = next((no for no, line in lines if event_class.group(2) in line), 1)
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    severity="medium",
                    confidence=0.8,
                    file_path=file_path,
                    line=line_no,
                    title="领域事件命名为命令式动作",
                    description="领域事件应表达已经发生的业务事实，命令式事件名会混淆意图和事实，导致消费方语义不清。",
                    recommendation="将事件命名为过去式事实，并由命令/应用服务触发领域动作。",
                    suggested_code='''public record OrderPaidEvent(OrderId orderId, Money paidAmount, Instant occurredAt) {}''',
                    evidence=event_class.group(2),
                    rule_id="DDD-EVENT-001",
                )
            )
        if re.search(r"\b[A-Z][A-Za-z0-9_]*(Order|Payment|Aggregate|Entity)\s+\w+", content):
            line_no = next((no for no, line in lines if re.search(r"\b[A-Z][A-Za-z0-9_]*(Order|Payment|Aggregate|Entity)\s+\w+", line)), 1)
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    severity="medium",
                    confidence=0.8,
                    file_path=file_path,
                    line=line_no,
                    title="领域事件直接携带聚合或实体对象",
                    description="事件直接携带可变聚合/实体会把对象图和持久化状态泄漏给消费方，破坏事件快照语义和兼容性。",
                    recommendation="事件只携带领域 ID、版本、发生时间和值对象快照，消费方按自身上下文转换。",
                    suggested_code='''public record PaymentConfirmedEvent(PaymentId paymentId, Money amount, Instant occurredAt) {}''',
                    evidence="Event 字段或 record 参数中出现聚合/实体对象。",
                    rule_id="DDD-EVENT-002",
                )
            )
    if "@transactional" in lowered_content:
        for no, line in lines:
            lowered = line.lower()
            if "@transactional" in lowered:
                window = "\n".join(text for line_no, text in lines if no <= line_no <= no + 3).lower()
                if re.search(r"\b(private|final|static)\b", window):
                    findings.append(
                        _finding(
                            agent_id="backend_agent",
                            severity="medium",
                            confidence=0.8,
                            file_path=file_path,
                            line=no,
                            title="@Transactional 标注在 private/final/static 方法上可能失效",
                            description="Spring AOP 代理无法拦截 private/final/static 方法，事务可能没有按预期生效。",
                            recommendation="将事务边界放在 public 应用服务方法上，并通过代理对象调用。",
                            suggested_code='''@Transactional
public void updatePaymentStatus(...) {
    // transactional boundary
}''',
                            evidence=window[:500],
                            rule_id="HW-TX-001",
                        )
                    )
    if re.search(r"equals\s*\([^)]*\)", content) and "hashCode(" not in content:
        line_no = next((no for no, line in lines if "equals(" in line), 1)
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="medium",
                confidence=0.78,
                file_path=file_path,
                line=line_no,
                title="重写 equals 时必须同时重写 hashCode",
                description="只重写 equals 不重写 hashCode 会破坏 HashMap/HashSet 等集合契约，导致对象查找异常。",
                recommendation="同时重写 equals 和 hashCode，或使用 IDE/record/lombok 生成一致实现。",
                suggested_code='''@Override
public int hashCode() {
    return Objects.hash(id);
}''',
                evidence="类中出现 equals 但未发现 hashCode。",
                rule_id="ALI-EQUALS-001",
            )
        )
    if "hashCode(" in content and not re.search(r"equals\s*\([^)]*\)", content):
        line_no = next((no for no, line in lines if "hashCode(" in line), 1)
        findings.append(
            _finding(
                agent_id="coding_agent",
                severity="medium",
                confidence=0.78,
                file_path=file_path,
                line=line_no,
                title="重写 hashCode 时必须同时重写 equals",
                description="只重写 hashCode 不重写 equals 会破坏对象等价语义，集合行为不可预期。",
                recommendation="同时重写 equals 和 hashCode，确保使用相同业务唯一键。",
                suggested_code='''@Override
public boolean equals(Object other) {
    // compare business identity
}''',
                evidence="类中出现 hashCode 但未发现 equals。",
                rule_id="ALI-EQUALS-001",
            )
        )
    return findings


def _maybe_missing_valid(file_path: str, lines: list[tuple[int, str]], mapping_line: int) -> list[dict[str, Any]]:
    window = "\n".join(line for no, line in lines if mapping_line <= no <= mapping_line + 4)
    if "@RequestBody" not in window or "@Valid" in window:
        return []
    method_line = next((no for no, line in lines if no >= mapping_line and "RequestBody" in line), mapping_line)
    return [
        _finding(
            agent_id="backend_agent",
            severity="medium",
            confidence=0.87,
            file_path=file_path,
            line=method_line,
            title="Controller 入参缺少 Bean Validation",
            description="新增写接口接收 @RequestBody，但没有 @Valid 或等价校验，非法字段可能进入业务层。",
            recommendation="为请求 DTO 增加校验注解，并在 Controller 参数上声明 @Valid。",
            suggested_code='''public ResponseEntity<?> create(@Valid @RequestBody CreatePaymentRequest request) {
    return ResponseEntity.ok(paymentService.create(request));
}''',
            evidence=window,
            rule_id="BE-API-001",
        )
    ]


def _maybe_missing_idempotency_guard(
    file_path: str,
    lines: list[tuple[int, str]],
    content: str,
    mapping_line: int,
) -> list[dict[str, Any]]:
    lowered_content = content.lower()
    window = "\n".join(line for no, line in lines if mapping_line <= no <= mapping_line + 36)
    lowered_window = window.lower()
    has_side_effect = any(
        token in lowered_window
        for token in [
            ".save(",
            ".delete(",
            ".record",
            ".send(",
            ".publish(",
            ".opsforvalue().set(",
            "executeupdate(",
        ]
    )
    if not has_side_effect:
        return []
    if "idempot" in lowered_content or "idempotency-key" in lowered_content or "requestid" in lowered_content or "request_id" in lowered_content:
        return []
    return [
        _finding(
            agent_id="backend_agent",
            severity="medium",
            confidence=0.81,
            file_path=file_path,
            line=mapping_line,
            title="POST 副作用接口缺少幂等保护",
            description="新增 POST 接口包含缓存、审计、持久化或外部副作用，但未看到幂等键或请求去重逻辑，重试可能造成重复处理。",
            recommendation="对写接口接入 Idempotency-Key/requestId 去重，或在业务唯一键上实现幂等状态机。",
            suggested_code='''String requestId = request.getHeader("Idempotency-Key");
idempotencyGuard.executeOnce(requestId, () -> {
    paymentService.process(command);
});''',
            evidence=window.strip()[:500],
            rule_id="BE-IDEMP-004",
        )
    ]


def _scan_spring_config(file_path: str, lines: list[tuple[int, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_no, line in lines:
        lowered = line.lower()
        if "include:" in lowered and "*" in line:
            findings.append(
                _finding(
                    agent_id="security_agent",
                    severity="high",
                    confidence=0.88,
                    file_path=file_path,
                    line=line_no,
                    title="Actuator 端点全量暴露",
                    description="management endpoints include=* 会暴露过多运维端点，若鉴权或网络隔离不足会导致敏感信息泄露。",
                    recommendation="只暴露 health、prometheus 等必要端点，并确认管理端口鉴权和网络隔离。",
                    suggested_code='''management:
  endpoints:
    web:
      exposure:
        include: "health,prometheus"''',
                    evidence=line,
                    rule_id="SEC-CONFIG-007",
                )
            )
        if "spring.datasource.password" in lowered or re.search(r"\bpassword\s*[:=]\s*[^\\s]+", lowered):
            findings.append(
                _finding(
                    agent_id="security_agent",
                    severity="high",
                    confidence=0.87,
                    file_path=file_path,
                    line=line_no,
                    title="Spring 配置中出现明文密码",
                    description="配置文件新增明文 password，可能随代码仓库泄露并被长期复用。",
                    recommendation="改用环境变量、密文配置或 secret store，并轮换已暴露密码。",
                    suggested_code='''spring:
  datasource:
    password: ${DB_PASSWORD}''',
                    evidence=line,
                    rule_id="SEC-SECRET-004",
                )
            )
    return findings


def _scan_xml_file(file_path: str, lines: list[tuple[int, str]], content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered_path = file_path.lower()
    if "mapper" not in lowered_path and "sqlmap" not in lowered_path and "mybatis" not in content.lower():
        return findings
    for line_no, line in lines:
        lowered = line.lower()
        if "${" in line:
            findings.append(
                _finding(
                    agent_id="security_agent",
                    severity="high",
                    confidence=0.9,
                    file_path=file_path,
                    line=line_no,
                    title="MyBatis SQL 中使用 ${} 存在注入风险",
                    description="阿里 Java 编码规约要求 MyBatis/iBatis SQL 参数使用 #{}，`${}` 会直接拼接字符串，外部输入可能形成 SQL 注入。",
                    recommendation="将 `${}` 改为 `#{}` 参数绑定；表名、排序字段等无法绑定的内容必须使用白名单枚举。",
                    suggested_code='''WHERE user_id = #{userId}
ORDER BY ${safeOrderBy} -- safeOrderBy must come from enum whitelist''',
                    evidence=line,
                    rule_id="ALI-MYBATIS-001",
                )
            )
        if "resulttype" in lowered and ("hashmap" in lowered or "java.util.map" in lowered or "java.util.hashmap" in lowered):
            findings.append(
                _finding(
                    agent_id="coding_agent",
                    severity="medium",
                    confidence=0.82,
                    file_path=file_path,
                    line=line_no,
                    title="数据库查询结果不应使用 HashMap/Map 承载",
                    description="阿里 Java 编码规约要求不要使用 HashMap/Hashtable 作为数据库查询结果类型，字段含义不清且类型不安全。",
                    recommendation="定义明确 DO/DTO/Projection 类型承载查询结果。",
                    suggested_code='''<select id="findPayment" resultType="com.jolt.payment.PaymentRecord">''',
                    evidence=line,
                    rule_id="ALI-DB-001",
                )
            )
        if "queryforlist" in lowered and re.search(r",\s*\w+\s*,\s*\w+\s*\)", line):
            findings.append(
                _finding(
                    agent_id="database_agent",
                    severity="medium",
                    confidence=0.82,
                    file_path=file_path,
                    line=line_no,
                    title="iBatis queryForList 分页方式可能导致 OOM",
                    description="阿里 Java 编码规约指出 queryForList(statement, start, size) 会先取全量结果再 subList，数据量大时可能 OOM。",
                    recommendation="在 SQL 中使用 start/size 参数进行数据库侧分页。",
                    suggested_code='''WHERE ...
LIMIT #{size} OFFSET #{start}''',
                    evidence=line,
                    rule_id="ALI-DB-002",
                )
            )
    return findings


def _scan_dependency_file(file_path: str, lines: list[tuple[int, str]], content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    risky_versions = [
        ("com.alibaba", "fastjson", "1.2.47", "fastjson 1.2.47 存在多类反序列化安全风险"),
        ("org.springframework", "spring-web", "5.3.0", "老版本 Spring 组件可能受已知 CVE 影响"),
        ("log4j", "log4j", "1.2.17", "Log4j 1.x 已停止维护且存在高风险漏洞"),
    ]
    for group, artifact, version, message in risky_versions:
        if group in content and artifact in content and version in content:
            line_no = next((no for no, line in lines if artifact in line or version in line), 1)
            findings.append(
                _finding(
                    agent_id="dependency_agent",
                    severity="high",
                    confidence=0.9,
                    file_path=file_path,
                    line=line_no,
                    title=f"高风险依赖版本：{group}:{artifact}:{version}",
                    description=message,
                    recommendation="升级到官方修复版本，或提供项目级安全例外和补丁证明。",
                    suggested_code=f'''<dependency>
  <groupId>{group}</groupId>
  <artifactId>{artifact}</artifactId>
  <version><!-- use patched version --></version>
</dependency>''',
                    evidence=f"{group}:{artifact}:{version}",
                    rule_id="DEP-CVE-001",
                )
            )
    if re.search(r"<artifactId>junit|testcontainers|mockito", content, re.I) and "<scope>test</scope>" not in content:
        line_no = next((no for no, line in lines if "junit" in line.lower() or "testcontainers" in line.lower() or "mockito" in line.lower()), 1)
        findings.append(
            _finding(
                agent_id="dependency_agent",
                severity="medium",
                confidence=0.8,
                file_path=file_path,
                line=line_no,
                title="测试依赖缺少 test scope",
                description="测试依赖未限定 scope，可能进入运行时 classpath 或生产包。",
                recommendation="为测试依赖添加 test scope，Gradle 使用 testImplementation。",
                suggested_code='''<scope>test</scope>''',
                evidence="检测到测试依赖但未看到 test scope。",
                rule_id="DEP-SCOPE-005",
            )
        )
    return findings


def _scan_database_changes(file_path: str, lines: list[tuple[int, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_no, line in lines:
        lowered = line.lower()
        if "drop column" in lowered or "drop table" in lowered:
            findings.append(
                _finding(
                    agent_id="database_agent",
                    severity="critical",
                    confidence=0.93,
                    file_path=file_path,
                    line=line_no,
                    title="数据库迁移包含破坏性 DROP 操作",
                    description="直接删除表或列会破坏新旧应用兼容窗口，并可能导致不可恢复的数据丢失。",
                    recommendation="采用 expand-contract 分阶段迁移，先停止读写并完成备份，再在兼容窗口后删除。",
                    suggested_code='''-- phase 1: stop application reads/writes
-- phase 2: backup data
-- phase 3: drop column after compatibility window''',
                    evidence=line,
                    rule_id="DB-DDL-001",
                )
            )
        if "not null" in lowered and "default" not in lowered and "add column" in lowered:
            findings.append(
                _finding(
                    agent_id="database_agent",
                    severity="high",
                    confidence=0.9,
                    file_path=file_path,
                    line=line_no,
                    title="新增 NOT NULL 列缺少默认值或回填方案",
                    description="已有表新增非空列且无默认值，会导致 migration 在存量数据上失败或长时间锁表。",
                    recommendation="提供默认值、分批回填或分阶段先加 nullable 字段再补约束。",
                    suggested_code='''ALTER TABLE orders
ADD COLUMN channel VARCHAR(32) DEFAULT 'UNKNOWN' NOT NULL;''',
                    evidence=line,
                    rule_id="DB-NOTNULL-002",
                )
            )
    return findings
