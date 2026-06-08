from __future__ import annotations

import sqlite3

from agents.expert_profile import ExpertProfile


DEFAULT_EXPERT_PROFILES = [
    ExpertProfile(
        "security_agent",
        "Security Agent",
        "安全专家，聚焦认证、授权、注入、密钥、敏感数据和供应链风险。",
        "只检视安全漏洞、权限边界、输入输出信任边界、敏感信息泄漏和安全配置。",
        "不检视性能调优、DDD 建模、前端交互、测试覆盖和 Redis 专项问题。",
    ),
    ExpertProfile(
        "performance_agent",
        "Performance Agent",
        "性能专家，聚焦吞吐、延迟、资源占用、容量风险和可扩展性。",
        "只检视慢查询、重复 IO、批处理退化、超时重试、缓存效率和资源泄漏。",
        "不检视安全漏洞、领域建模、前端体验、测试完整性和 Redis 命令语义之外的问题。",
    ),
    ExpertProfile(
        "coding_agent",
        "General Coding Agent",
        "通用编码专家，聚焦正确性、边界条件、异常处理、类型和可维护性。",
        "只检视通用实现缺陷、兼容性、状态流转、空值、异常和代码可读性。",
        "不重复检视安全、性能、DDD、前端、测试和 Redis 专项问题。",
    ),
    ExpertProfile(
        "ddd_agent",
        "DDD Design Agent",
        "DDD 设计专家，聚焦领域概念、聚合边界、业务不变量和上下文边界。",
        "只检视领域模型、应用服务、领域服务、仓储、事件和业务规则表达问题。",
        "不检视底层安全、性能微优化、前端交互、测试覆盖和 Redis 使用细节。",
    ),
    ExpertProfile(
        "frontend_agent",
        "Frontend Agent",
        "前端专家，聚焦用户路径、组件状态、异步交互、可访问性和浏览器侧质量。",
        "只检视前端组件、状态、表单、错误/加载/空状态、可访问性和浏览器安全。",
        "不检视后端业务规则、DDD 聚合、服务端性能、Redis 和后端测试问题。",
    ),
    ExpertProfile(
        "test_agent",
        "Test Agent",
        "测试专家，聚焦验证信号、断言质量、回归风险和边界场景。",
        "只检视测试覆盖、断言、回归用例、边界场景、测试数据和验证策略。",
        "不检视安全漏洞、性能优化、领域设计和前端样式问题。",
    ),
    ExpertProfile(
        "redis_agent",
        "Redis Agent",
        "Redis 专家，聚焦缓存一致性、TTL、热点 key、分布式锁、Lua 和命令风险。",
        "只检视 Redis key 设计、缓存一致性、TTL、锁、pipeline、Lua、队列和热点风险。",
        "不检视非 Redis 的数据库、通用性能、安全、DDD、前端和测试问题。",
    ),
    ExpertProfile(
        "dependency_agent",
        "Dependency Agent",
        "依赖审查专家，聚焦 Maven/Gradle 依赖、CVE、许可证、版本冲突和供应链风险。",
        "只检视 pom.xml、build.gradle、dependencyManagement、插件版本、CVE、license 和版本收敛问题。",
        "不检视业务实现、安全代码细节、性能、DDD、Redis 或测试覆盖。",
    ),
    ExpertProfile(
        "database_agent",
        "Database Agent",
        "数据库专家，聚焦 SQL、Repository/Mapper、事务、索引、锁、schema、migration、数据迁移、回滚和线上发布兼容性。",
        "只检视数据库相关问题，包括数据库访问层、SQL 查询、结果映射、索引、事务、锁、schema、migration、数据回填、回滚补偿和发布兼容性。",
        "不检视普通 Java 语法、安全漏洞专项、前端、Redis、依赖 CVE 或普通测试覆盖。",
    ),
    ExpertProfile(
        "backend_agent",
        "Backend Agent",
        "后端专家，聚焦 API 契约、服务编排、事务、幂等、错误处理和后台任务可靠性。",
        "只检视后端 API、服务层、事务边界、幂等、错误处理、后台任务和集成契约。",
        "不重复检视安全漏洞、专项性能、DDD 建模、前端交互、测试覆盖和 Redis 专项问题。",
    ),
]


def load_expert_profiles(conn: sqlite3.Connection, project_id: str) -> list[ExpertProfile]:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'expert_profiles'"
    ).fetchone()
    if not table:
        return DEFAULT_EXPERT_PROFILES
    rows = conn.execute(
        """
        SELECT *
        FROM expert_profiles
        WHERE project_id = ? AND enabled = 1
        ORDER BY agent_key
        """,
        (project_id,),
    ).fetchall()
    if not rows:
        return DEFAULT_EXPERT_PROFILES
    return [
        ExpertProfile(
            agent_key=row["agent_key"],
            display_name=row["display_name"],
            role_profile=row["role_profile"],
            responsibility_scope=row["responsibility_scope"],
            excluded_scope=row["excluded_scope"],
            enabled=bool(row["enabled"]),
            min_confidence=float(row["min_confidence"]),
            max_findings=int(row["max_findings"]),
            max_llm_calls=int(row["max_llm_calls"]),
            max_tool_calls=int(row["max_tool_calls"]),
            output_schema_version=row["output_schema_version"],
        )
        for row in rows
    ]
