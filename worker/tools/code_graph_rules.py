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
            *_endpoint_signature_findings(graph_view, file_path, role, raw_artifact_id),
            *_call_findings(graph_view, file_path, raw_artifact_id),
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
        if role == "interface" and target == "infrastructure":
            findings.append(
                _finding(
                    agent_id="ddd_agent",
                    rule_id="DDD-LAYER-001",
                    severity="high",
                    confidence=0.91,
                    file_path=file_path,
                    line=line,
                    title="Controller 直接依赖基础设施仓储或 Mapper",
                    description="tree-sitter 代码图谱发现接口层文件直接 import 基础设施/持久化类型，绕过应用层和领域边界，容易把 Repository/Mapper 调用泄漏到 Controller。",
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


def _call_findings(graph_view: CodeGraphView, file_path: str, raw_artifact_id: str | None) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for call in graph_view.calls_by_file.get(file_path, []):
        callee = str(call.get("callee") or "")
        snippet = str(call.get("snippet") or "")
        lowered = snippet.lower()
        line = int(call.get("line") or 1)
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
            if ("executequery" in lowered or "executeupdate" in lowered) and "+" in snippet:
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
                        evidence=f"{file_path}:{line} SQL execution uses concatenated expression: {snippet[:260]}",
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
