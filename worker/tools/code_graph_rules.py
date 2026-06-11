from __future__ import annotations

from typing import Any


def evaluate_code_graph_rules(
    graph: dict[str, Any],
    changed_files: list[Any],
    *,
    raw_artifact_id: str | None = None,
) -> list[dict[str, Any]]:
    changed_paths = {str(getattr(item, "filename", "")).replace("\\", "/") for item in changed_files}
    changed_paths = {item for item in changed_paths if item}
    if not changed_paths or graph.get("status") not in {"indexed", "indexed_partial", "timeout_partial"}:
        return []

    graph_view = CodeGraphView(graph, changed_paths)
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str]] = set()
    for file_path in sorted(changed_paths):
        role = graph_view.layer_role(file_path)
        candidates = [
            *_architecture_import_findings(graph_view, file_path, role, raw_artifact_id),
            *_domain_model_findings(graph_view, file_path, role, raw_artifact_id),
            *_application_service_findings(graph_view, file_path, role, raw_artifact_id),
            *_endpoint_signature_findings(graph_view, file_path, role, raw_artifact_id),
            *_call_findings(graph_view, file_path, role, raw_artifact_id),
        ]
        for finding in candidates:
            key = (finding["file_path"], finding["tool_rule_id"], int(finding["line_start"]), finding["evidence"])
            if key not in seen:
                seen.add(key)
                findings.append(finding)
    return findings


class CodeGraphView:
    def __init__(self, graph: dict[str, Any], changed_paths: set[str]) -> None:
        self.changed_paths = changed_paths
        self.imports_by_file = self._group_by_file(graph.get("imports") or [])
        self.classes_by_file = self._group_by_file(graph.get("classes") or [])
        self.functions_by_file = self._group_by_file(graph.get("functions") or [])
        self.calls_by_file = self._group_by_file(graph.get("callers") or [])

    def _group_by_file(self, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            file_path = str(item.get("file_path") or "").replace("\\", "/")
            if file_path in self.changed_paths:
                grouped.setdefault(file_path, []).append(item)
        return grouped

    def layer_role(self, file_path: str) -> str:
        lowered = file_path.lower()
        class_names = " ".join(str(item.get("name") or "") for item in self.classes_by_file.get(file_path, [])).lower()
        combined = f"{lowered} {class_names}"
        if any(marker in combined for marker in ["/controller/", "/interfaces/", "/adapter/in/", "controller", "restcontroller"]):
            return "interface"
        if any(marker in combined for marker in ["/application/", "/app/", "applicationservice", "commandhandler"]):
            return "application"
        if any(marker in combined for marker in ["/domain/", "/model/", "/aggregate/", "domainservice"]):
            return "domain"
        if any(marker in combined for marker in ["/infrastructure/", "/infra/", "/persistence/", "/adapter/out/"]):
            return "infrastructure"
        return "unknown"

    def function_for_line(self, file_path: str, line: int) -> dict[str, Any] | None:
        candidates = self.functions_by_file.get(file_path, [])
        before = [item for item in candidates if int(item.get("line") or 0) <= line]
        if before:
            return max(before, key=lambda item: int(item.get("line") or 0))
        return candidates[0] if candidates else None

    def function_context(self, file_path: str, line: int) -> str:
        function = self.function_for_line(file_path, line)
        return str(function.get("snippet") or "") if function else ""

    def file_context(self, file_path: str) -> str:
        snippets = [
            *(str(item.get("snippet") or "") for item in self.classes_by_file.get(file_path, [])),
            *(str(item.get("snippet") or "") for item in self.functions_by_file.get(file_path, [])),
        ]
        return "\n".join(item for item in snippets if item)


def _architecture_import_findings(
    graph_view: CodeGraphView,
    file_path: str,
    role: str,
    raw_artifact_id: str | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for import_item in graph_view.imports_by_file.get(file_path, []):
        import_text = str(import_item.get("import") or "")
        line = int(import_item.get("line") or 1)
        target = _import_target_kind(import_text)
        if role == "interface" and (target == "infrastructure" or _looks_like_repository_dependency(import_text)):
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-LAYER-001",
                    severity="high",
                    confidence=0.91,
                    file_path=file_path,
                    line=line,
                    title="Controller 直接依赖仓储或 Mapper",
                    description="tree-sitter 代码图谱发现接口层文件直接 import Repository/Mapper/JPA 类型，绕过应用层和领域边界，容易把持久化调用泄漏到 Controller。",
                    recommendation="Controller 只依赖应用服务或用例入口；仓储、Mapper、JPA/MyBatis 类型应留在 infrastructure adapter 内部。",
                    suggested_code="""@RestController
class PaymentController {
    private final CapturePaymentUseCase capturePaymentUseCase;

    void capture(CapturePaymentRequest request) {
        capturePaymentUseCase.capture(request.toCommand());
    }
}""",
                    evidence=f"{file_path}:{line} imports infrastructure dependency: {import_text}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if role == "domain" and target in {"infrastructure", "interface"}:
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-LAYER-002",
                    severity="high",
                    confidence=0.9,
                    file_path=file_path,
                    line=line,
                    title="领域层反向依赖外层技术实现",
                    description="tree-sitter 代码图谱发现领域层 import 基础设施或接口层类型，破坏领域模型的内向依赖原则。",
                    recommendation="领域层只能依赖领域对象、领域服务接口和必要的语言基础类型；外部技术类型通过端口、ACL 或 mapper 隔离。",
                    suggested_code="""public interface PaymentRepository {
    Optional<Payment> find(PaymentId paymentId);
}""",
                    evidence=f"{file_path}:{line} domain layer imports outer dependency: {import_text}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if role == "application" and target == "infrastructure":
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-APP-003",
                    severity="medium",
                    confidence=0.86,
                    file_path=file_path,
                    line=line,
                    title="应用层直接依赖基础设施实现",
                    description="tree-sitter 代码图谱发现应用层 import infrastructure/persistence 具体实现，应用服务边界容易与技术细节耦合。",
                    recommendation="应用层依赖领域端口或应用端口，基础设施通过 adapter 实现端口并在装配层注入。",
                    suggested_code="""class CapturePaymentService {
    private final PaymentRepository paymentRepository;
    private final PaymentGateway paymentGateway;
}""",
                    evidence=f"{file_path}:{line} application layer imports infrastructure dependency: {import_text}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if role == "domain" and target == "framework_paging":
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-REPO-003",
                    severity="medium",
                    confidence=0.84,
                    file_path=file_path,
                    line=line,
                    title="领域仓储接口暴露框架分页类型",
                    description="tree-sitter 代码图谱发现领域层 import Spring Data 分页类型，领域端口被框架 API 污染。",
                    recommendation="领域仓储接口使用业务查询对象和业务结果类型，在 infrastructure adapter 中转换 Pageable/Page。",
                    suggested_code="""PaymentPage findByCriteria(PaymentQuery query);
Page<PaymentEntity> page = paymentJpaRepository.findAll(toPageable(query));""",
                    evidence=f"{file_path}:{line} domain layer imports framework paging type: {import_text}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
    return findings


def _domain_model_findings(
    graph_view: CodeGraphView,
    file_path: str,
    role: str,
    raw_artifact_id: str | None,
) -> list[dict[str, Any]]:
    if role != "domain":
        return []
    findings: list[dict[str, Any]] = []
    context = graph_view.file_context(file_path)
    compact = context.replace("\n", " ")
    if _contains_map_string_object(context):
        findings.append(
            _finding(
                agent_id="ddd_agent",
                rule_id="DDD-VO-002",
                severity="medium",
                confidence=0.86,
                file_path=file_path,
                line=_first_context_line(graph_view, file_path),
                title="领域模型使用 Map<String,Object> 弱类型属性",
                description="tree-sitter 结构分析发现领域对象使用 Map<String,Object> 承载业务属性，字段语义、约束和不变量无法在模型中表达。",
                recommendation="为业务属性建模为明确的 Value Object 或领域字段，在构造/工厂方法中校验约束，避免把动态 Map 暴露为领域状态。",
                suggested_code="""final class PaymentAttributes {
    private final PaymentChannel channel;
    private final Money amount;
}""",
                evidence=f"{file_path} domain model contains weak Map<String,Object> state: {compact[:260]}",
                raw_artifact_id=raw_artifact_id,
            )
        )
    for function in graph_view.functions_by_file.get(file_path, []):
        name = str(function.get("name") or "")
        snippet = str(function.get("snippet") or "")
        if name.startswith("set") and ("public" in snippet or "void set" in snippet):
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-AGG-004",
                    severity="medium",
                    confidence=0.85,
                    file_path=file_path,
                    line=int(function.get("line") or 1),
                    title="聚合/实体暴露 public setter 破坏不变量封装",
                    description="tree-sitter 方法签名发现领域对象暴露 public setter，外部代码可绕过领域行为直接改状态，聚合不变量难以集中维护。",
                    recommendation="用表达业务意图的方法替代 setter，并在方法内部校验状态流转、金额、租户等不变量。",
                    suggested_code="""public void markCaptured(CaptureResult result) {
    ensureCanCapture();
    this.status = PaymentStatus.CAPTURED;
}""",
                    evidence=f"{file_path}:{function.get('line')} exposes setter in domain model: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
    return findings


def _application_service_findings(
    graph_view: CodeGraphView,
    file_path: str,
    role: str,
    raw_artifact_id: str | None,
) -> list[dict[str, Any]]:
    if role != "application":
        return []
    findings: list[dict[str, Any]] = []
    for call in graph_view.calls_by_file.get(file_path, []):
        callee = str(call.get("callee") or "")
        snippet = str(call.get("snippet") or "")
        line = int(call.get("line") or 1)
        context = graph_view.function_context(file_path, line)
        if _is_mutating_repository_call(callee, snippet) and "@Transactional" not in context:
            findings.append(
                _finding(
                    agent_id="backend_agent",
                    rule_id="BE-TX-002",
                    severity="medium",
                    confidence=0.86,
                    file_path=file_path,
                    line=line,
                    title="应用服务执行写库操作但缺少事务边界",
                    description="tree-sitter 调用图发现应用层方法调用 Repository/Mapper 写操作，但方法上下文没有 @Transactional，异常时可能出现部分写入或领域事件与状态不一致。",
                    recommendation="在应用服务用例方法上声明事务边界，或把写操作编排移动到已有事务的应用服务中。",
                    suggested_code="""@Transactional
public void capture(Payment payment) {
    paymentRepository.save(payment);
}""",
                    evidence=f"{file_path}:{line} mutating repository call without @Transactional: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
    return findings


def _endpoint_signature_findings(
    graph_view: CodeGraphView,
    file_path: str,
    role: str,
    raw_artifact_id: str | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if role != "interface":
        return findings
    for function in graph_view.functions_by_file.get(file_path, []):
        snippet = str(function.get("snippet") or "")
        compact = snippet.replace("\n", " ")
        if "@RequestBody" in snippet and "@Valid" not in snippet and "@Validated" not in snippet:
            findings.append(
                _finding(
                    agent_id="backend_agent",
                    rule_id="BE-API-001",
                    severity="medium",
                    confidence=0.87,
                    file_path=file_path,
                    line=int(function.get("line") or 1),
                    title="接口 RequestBody 缺少 Bean Validation",
                    description="tree-sitter 方法签名分析发现 Controller 写接口接收 @RequestBody，但没有 @Valid 或等价校验，非法字段可能直接进入业务层。",
                    recommendation="为 @RequestBody DTO 添加 @Valid，并在 DTO 字段上声明 @NotNull、@NotBlank、@Size 等约束；避免直接接收 Map<String,Object>。",
                    suggested_code="""public ResponseEntity<?> create(@Valid @RequestBody CreatePaymentRequest request) {
    applicationService.create(request.toCommand());
    return ResponseEntity.ok().build();
}""",
                    evidence=f"{file_path}:{function.get('line')} method accepts @RequestBody without @Valid: {compact[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
    return findings


def _call_findings(graph_view: CodeGraphView, file_path: str, role: str, raw_artifact_id: str | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for call in graph_view.calls_by_file.get(file_path, []):
        callee = str(call.get("callee") or "")
        snippet = str(call.get("snippet") or "")
        lowered = snippet.lower()
        line = int(call.get("line") or 1)
        function_context = graph_view.function_context(file_path, line)
        context_lowered = function_context.lower()
        if role == "interface" and _is_repository_call(callee, snippet):
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-LAYER-001",
                    severity="high",
                    confidence=0.89,
                    file_path=file_path,
                    line=line,
                    title="Controller 直接调用仓储/Mapper",
                    description="tree-sitter 调用图发现接口层方法直接调用 Repository/Mapper，绕过应用服务用例编排，接口层会承担事务、领域规则和持久化细节。",
                    recommendation="Controller 调用应用服务或 UseCase，由应用层协调仓储和领域对象；接口层只做协议适配和 DTO 转换。",
                    suggested_code="""capturePaymentUseCase.capture(request.toCommand());""",
                    evidence=f"{file_path}:{line} controller calls repository/mapper directly: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if callee == "readObject":
            findings.append(
                _finding(
                    agent_id="security_agent",
                    rule_id="jolt.java.objectinputstream-readobject",
                    severity="high",
                    confidence=0.9,
                    file_path=file_path,
                    line=line,
                    title="ObjectInputStream 反序列化调用进入新增代码",
                    description="tree-sitter 调用图发现新增代码调用 ObjectInputStream.readObject，若输入来自请求、文件或外部消息，可能触发不可信反序列化风险。",
                    recommendation="避免直接反序列化不可信对象；改用 JSON/DTO 白名单解析，或配置 ObjectInputFilter 限制允许类型、大小和深度。",
                    suggested_code="""ObjectInputFilter filter = ObjectInputFilter.Config.createFilter("com.acme.safe.*;!*");
input.setObjectInputFilter(filter);
SafeCommand command = safeJsonMapper.readValue(payload, SafeCommand.class);""",
                    evidence=f"{file_path}:{line} calls readObject: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if callee in {"parseExpression", "getValue"} and "spel" in lowered:
            findings.append(
                _finding(
                    agent_id="security_agent",
                    rule_id="jolt.java.spel-standard-evaluation-context",
                    severity="high",
                    confidence=0.86,
                    file_path=file_path,
                    line=line,
                    title="SpEL 表达式执行缺少受限上下文",
                    description="tree-sitter 调用图发现 SpEL 表达式解析/执行调用，若表达式或上下文来自外部配置，需要限制类型访问和方法调用能力。",
                    recommendation="使用 SimpleEvaluationContext 或受限 DSL，禁止将外部表达式交给 StandardEvaluationContext 直接执行。",
                    suggested_code="""SimpleEvaluationContext context = SimpleEvaluationContext
    .forReadOnlyDataBinding()
    .build();""",
                    evidence=f"{file_path}:{line} calls SpEL evaluation API: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
        if _is_query_call(callee, snippet):
            if int(call.get("loop_depth") or 0) > 0:
                findings.append(
                    _finding(
                        agent_id="performance_agent",
                        rule_id="PERF-QUERY-001",
                        severity="high",
                        confidence=0.88,
                        file_path=file_path,
                        line=line,
                        title="循环内执行数据库查询或持久化调用",
                        description="tree-sitter 调用图发现新增代码在循环体内执行查询/Repository 调用，数据量增长后容易形成 N+1 查询或请求线程长时间阻塞。",
                        recommendation="将循环内查询改为批量查询、预加载映射或分页游标处理，并为结果集设置明确上限。",
                        suggested_code="""Map<String, Payment> payments = paymentRepository.findByUserIds(userIds)
    .stream()
    .collect(Collectors.toMap(Payment::userId, Function.identity()));""",
                        evidence=f"{file_path}:{line} query call inside loop: {snippet[:260]}",
                        raw_artifact_id=raw_artifact_id,
                    )
                )
            if ("executequery" in lowered or "executeupdate" in lowered) and ("+" in snippet or _has_sql_concat_context(function_context)):
                findings.append(
                    _finding(
                        agent_id="security_agent",
                        rule_id="SEC-INJECT-003",
                        severity="high",
                        confidence=0.89,
                        file_path=file_path,
                        line=line,
                        title="SQL 执行调用包含字符串拼接",
                        description="tree-sitter 调用图发现 JDBC SQL 执行调用中包含字符串拼接，外部输入进入 SQL 时存在注入风险。",
                        recommendation="改用 PreparedStatement 参数绑定；动态字段、排序和表名使用白名单枚举。",
                        suggested_code="""PreparedStatement ps = connection.prepareStatement(
    "select * from payments where user_id = ?"
);
ps.setString(1, userId);
ResultSet rs = ps.executeQuery();""",
                        evidence=f"{file_path}:{line} SQL execution uses concatenated expression: {(snippet or function_context)[:260]}",
                        raw_artifact_id=raw_artifact_id,
                    )
                )
        if callee == "set" and "redis" in context_lowered and "opsforvalue" in context_lowered and not _has_ttl_context(function_context):
            findings.append(
                _finding(
                    agent_id="backend_agent",
                    rule_id="REDIS-TTL-002",
                    severity="medium",
                    confidence=0.84,
                    file_path=file_path,
                    line=line,
                    title="Redis 缓存写入缺少 TTL",
                    description="tree-sitter 调用图发现 Redis opsForValue().set 写缓存时没有过期时间，业务缓存可能无限增长或长期保留旧状态。",
                    recommendation="为业务缓存设置明确 TTL，并把 key 设计为包含租户/业务维度的稳定结构。",
                    suggested_code="""redisTemplate.opsForValue().set(key, value, Duration.ofMinutes(30));""",
                    evidence=f"{file_path}:{line} Redis set without TTL: {snippet[:260]}",
                    raw_artifact_id=raw_artifact_id,
                )
            )
    return findings


def _import_target_kind(import_text: str) -> str:
    lowered = import_text.lower()
    if any(marker in lowered for marker in [".infrastructure.", ".infra.", ".persistence.", ".mapper.", ".jpa", "jparepository", "mybatis"]):
        return "infrastructure"
    if any(marker in lowered for marker in [".interfaces.", ".controller.", ".adapter.in.", ".web."]):
        return "interface"
    if any(marker in lowered for marker in [".application.", ".app."]):
        return "application"
    if ".domain." in lowered:
        return "domain"
    if any(marker in lowered for marker in ["org.springframework.data.domain.page", "org.springframework.data.domain.pageable"]):
        return "framework_paging"
    return "unknown"


def _is_query_call(callee: str, snippet: str) -> bool:
    lowered = snippet.lower()
    if callee in {"executeQuery", "executeUpdate", "queryForList", "queryForObject", "selectList", "selectOne"}:
        return True
    if callee in {"findAll", "findById", "save", "delete", "update"} and any(
        marker in lowered for marker in ["repository", "mapper", "dao", "jdbctemplate", "statement", "entitymanager"]
    ):
        return True
    return False


def _looks_like_repository_dependency(import_text: str) -> bool:
    lowered = import_text.lower()
    return any(marker in lowered for marker in ["repository", "mapper", "dao", "jparepository", "mybatis"])


def _contains_map_string_object(value: str) -> bool:
    compact = value.replace(" ", "")
    return "Map<String,Object>" in compact or "Map<java.lang.String,Object>" in compact


def _first_context_line(graph_view: CodeGraphView, file_path: str) -> int:
    lines = [
        *(int(item.get("line") or 1) for item in graph_view.classes_by_file.get(file_path, [])),
        *(int(item.get("line") or 1) for item in graph_view.functions_by_file.get(file_path, [])),
    ]
    return min(lines) if lines else 1


def _is_repository_call(callee: str, snippet: str) -> bool:
    lowered = snippet.lower()
    return _is_query_call(callee, snippet) or any(marker in lowered for marker in ["repository.", "mapper.", "dao."])


def _is_mutating_repository_call(callee: str, snippet: str) -> bool:
    if callee not in {"save", "delete", "update", "insert", "merge", "persist", "flush"}:
        return False
    return any(marker in snippet.lower() for marker in ["repository", "mapper", "dao", "entitymanager"])


def _has_sql_concat_context(context: str) -> bool:
    lowered = context.lower()
    return bool(("select " in lowered or "update " in lowered or "delete " in lowered or "insert " in lowered) and "+" in context)


def _has_ttl_context(context: str) -> bool:
    lowered = context.lower()
    return any(marker in lowered for marker in ["duration.", "chronounit.", "expire(", "timeout", "ttl"])


def _finding(
    *,
    agent_id: str,
    rule_id: str,
    severity: str,
    confidence: float,
    file_path: str,
    line: int,
    title: str,
    description: str,
    recommendation: str,
    suggested_code: str,
    evidence: str,
    raw_artifact_id: str | None,
) -> dict[str, Any]:
    return {
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
        "evidence": evidence,
        "tool_name": "tree_sitter_code_graph",
        "tool_rule_id": rule_id,
        "raw_artifact_id": raw_artifact_id,
        "covered_rules": [rule_id],
        "skipped_rules": [],
    }
