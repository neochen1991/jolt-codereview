from __future__ import annotations

import json
from typing import Any

from db_helpers import table_exists
from tools.tool_normalizer import sha1


JUDGE_REASON_MESSAGES = {
    "judge_unclassified_rejection": "Judge 删除了该候选，但未提供可分类原因；已记录为质量异常。",
    "bound_false_positive_pattern_match": "候选命中了 Skill 定义的误报排除模式。",
    "bound_skill_checkpoint_mismatch": "候选内容与当前 Skill Checkpoint 不一致。",
    "bound_rule_mismatch": "候选引用的规则与当前绑定规则不一致。",
    "rule_attribution_mismatch": "候选证据有效，但模型返回的规则归属与当前批次不一致，已保留复核。",
    "rule_attribution_missing": "候选证据有效，但模型未返回可确认的规则归属，已保留复核。",
    "critic_rejected": "Critic 复核未通过，候选证据或结论不足。",
    "evidence_contract_not_satisfied": "候选未满足 Checkpoint 定义的证据合同。",
    "deduped_lower_rank": "候选与更高优先级问题重复，已合并。",
    "deduped_same_business_issue": "候选描述同一业务问题，已合并。",
    "deduped_after_rule_reconciliation": "规则归一化后候选重复，已合并。",
    "not_selected_final_issue": "候选未达到最终问题选择门槛。",
    "not_selected_after_quality_calibration": "质量校准后候选未达到保留门槛。",
    "max_findings_exceeded": "候选超过本次 Review 的最大问题数量限制。",
    "unsupported_low_precision_llm_finding": "候选属于低精度且缺少可靠支撑的模型结论。",
    "unresolved_context": "候选上下文不完整，无法可靠确认或排除，已保留人工复核。",
    "heuristic_semantic_path": "跨文件结论仅由启发式同名关系支撑，不能自动确认。",
    "contradicting_evidence": "源码或工具证据与候选结论相矛盾。",
    "contradicting_authorization_guard": "源码中存在与候选结论相矛盾的权限拦截。",
    "contradicting_null_guard": "源码中存在与候选结论相矛盾的空值保护。",
    "contradicting_transaction_compensation": "源码中存在与候选结论相矛盾的事务补偿。",
    "rule_auto_suppressed_low_confidence": "规则历史精度过低且当前置信度不足，候选被抑制。",
}

MERGED_REASON_CODES = {
    "deduped_lower_rank",
    "deduped_same_business_issue",
    "deduped_after_rule_reconciliation",
    "auxiliary_overlap_core_issue",
    "nearby_sensitive_duplicate",
}


def _candidate_table_exists(conn: Any) -> bool:
    return table_exists(conn, "candidate_findings")


def _candidate_id(review_run_id: str, dedupe_hash: str, stage: str) -> str:
    return "cand_" + sha1("|".join([review_run_id, dedupe_hash, stage]))[:16]


def _safe_json(value: Any, default: Any) -> str:
    try:
        return json.dumps(value if value is not None else default, ensure_ascii=False)
    except TypeError:
        return json.dumps(default, ensure_ascii=False)


def sanitize_rejected_reasons(reasons: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    removed_legacy_evidence_reason = False
    for reason in reasons or []:
        value = str(reason or "").strip()
        if not value:
            continue
        if value == "evidence_not_in_source":
            removed_legacy_evidence_reason = True
            continue
        if value not in cleaned:
            cleaned.append(value)
    if removed_legacy_evidence_reason and not cleaned:
        cleaned.append("low_evidence_match")
    return cleaned


def decision_status_for_rejection(reasons: list[str] | None) -> str:
    clean = sanitize_rejected_reasons(reasons)
    return "merged" if any(reason in MERGED_REASON_CODES for reason in clean) else "rejected"


def build_decision_reason_details(
    reasons: list[str] | None,
    *,
    status: str,
    stage: str,
) -> list[dict[str, str]]:
    clean = sanitize_rejected_reasons(reasons)
    if status in {"rejected", "merged"} and not clean:
        clean = ["judge_unclassified_rejection"]
    return [
        {
            "code": reason,
            "message": JUDGE_REASON_MESSAGES.get(reason, f"Judge 决策原因：{reason}。"),
            "stage": stage,
        }
        for reason in clean
    ]


def _candidate_dedupe_hash(item: dict[str, Any], stage: str) -> str:
    dedupe_hash = str(item.get("dedupe_hash") or "").strip()
    if dedupe_hash:
        return dedupe_hash
    return sha1(
        "|".join(
            [
                str(item.get("agent_id") or item.get("tool_name") or "unknown"),
                str(item.get("file_path") or ""),
                str(item.get("line_start") or ""),
                str(item.get("title") or item.get("message") or ""),
                stage,
            ]
        )
    )


def _source_type(item: dict[str, Any]) -> str:
    if item.get("source_tool_observation") or item.get("tool_name") or item.get("tool_rule_id"):
        return "tool"
    if item.get("agent_id"):
        return "agent"
    return "unknown"


def upsert_candidate_finding(
    conn: Any,
    *,
    review_run_id: str,
    item: dict[str, Any],
    stage: str,
    status: str,
    rejected_reasons: list[str] | None = None,
    final_finding_id: str | None = None,
) -> None:
    if not _candidate_table_exists(conn):
        return
    dedupe_hash = _candidate_dedupe_hash(item, stage)
    rule_values = item.get("covered_rules") if isinstance(item.get("covered_rules"), list) else []
    rule_id = str(item.get("tool_rule_id") or item.get("rule_id") or (rule_values[0] if rule_values else "") or "")
    source_observations = item.get("source_observations") or item.get("source_observations_json") or []
    source_tool_observation = item.get("source_tool_observation")
    if source_tool_observation and not source_observations:
        source_observations = [source_tool_observation]
    clean_rejected_reasons = sanitize_rejected_reasons(rejected_reasons or item.get("rejected_reasons") or [])
    effective_status = decision_status_for_rejection(clean_rejected_reasons) if status == "rejected" else status
    decision_details = build_decision_reason_details(clean_rejected_reasons, status=effective_status, stage=stage)
    if effective_status in {"rejected", "merged"} and not clean_rejected_reasons:
        clean_rejected_reasons = ["judge_unclassified_rejection"]
    conn.execute(
        """
        INSERT INTO candidate_findings (
          id, review_run_id, dedupe_hash, stage, status, source_type,
          agent_id, tool_name, rule_id, severity, confidence, file_path, line_start, line_end,
          title, problem_description, evidence, rejected_reasons_json, source_observations_json,
          raw_json, final_finding_id, decision_reason_json, decision_stage, decided_at, merged_into_candidate_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s IN ('retained','final','rejected','merged') THEN CURRENT_TIMESTAMP ELSE NULL END, %s)
        ON CONFLICT(review_run_id, dedupe_hash, stage) DO UPDATE SET
          status = excluded.status,
          source_type = excluded.source_type,
          agent_id = excluded.agent_id,
          tool_name = excluded.tool_name,
          rule_id = excluded.rule_id,
          severity = excluded.severity,
          confidence = excluded.confidence,
          file_path = excluded.file_path,
          line_start = excluded.line_start,
          line_end = excluded.line_end,
          title = excluded.title,
          problem_description = excluded.problem_description,
          evidence = excluded.evidence,
          rejected_reasons_json = excluded.rejected_reasons_json,
          source_observations_json = excluded.source_observations_json,
          raw_json = excluded.raw_json,
          final_finding_id = COALESCE(excluded.final_finding_id, candidate_findings.final_finding_id),
          decision_reason_json = excluded.decision_reason_json,
          decision_stage = excluded.decision_stage,
          decided_at = excluded.decided_at,
          merged_into_candidate_id = COALESCE(excluded.merged_into_candidate_id, candidate_findings.merged_into_candidate_id),
          updated_at = CURRENT_TIMESTAMP
        """,
        (
            _candidate_id(review_run_id, dedupe_hash, stage),
            review_run_id,
            dedupe_hash,
            stage,
            effective_status,
            _source_type(item),
            str(item.get("agent_id") or item.get("adopted_by_agent") or "") or None,
            str(item.get("tool_name") or "") or None,
            rule_id or None,
            str(item.get("severity") or "") or None,
            float(item.get("confidence") or 0),
            str(item.get("file_path") or ""),
            item.get("line_start"),
            item.get("line_end"),
            str(item.get("title") or item.get("message") or "")[:300],
            str(item.get("problem_description") or item.get("message") or item.get("title") or "")[:4000],
            str(item.get("evidence") or item.get("message") or "")[:4000],
            _safe_json(clean_rejected_reasons, []),
            _safe_json(source_observations, []),
            _safe_json(item, {}),
            final_finding_id,
            _safe_json(decision_details, []),
            stage if effective_status in {"retained", "final", "rejected", "merged"} else None,
            effective_status,
            str(item.get("merged_into_candidate_id") or "") or None,
        ),
    )


def upsert_candidate_findings(
    conn: Any,
    *,
    review_run_id: str,
    items: list[dict[str, Any]],
    stage: str,
    status: str,
) -> None:
    for item in items:
        upsert_candidate_finding(
            conn,
            review_run_id=review_run_id,
            item=item,
            stage=stage,
            status=status,
            rejected_reasons=item.get("rejected_reasons") or [],
            final_finding_id=item.get("persisted_finding_id"),
        )
