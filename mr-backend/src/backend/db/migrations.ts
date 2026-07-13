import { createHash } from "node:crypto";
import type { Db } from "./connection.js";

export function migrate(db: Db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS audit_logs (
      id TEXT PRIMARY KEY,
      user_id TEXT,
      project_id TEXT,
      action TEXT NOT NULL,
      resource_type TEXT NOT NULL,
      resource_id TEXT,
      summary TEXT NOT NULL DEFAULT '',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS repositories (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      external_repo_id TEXT NOT NULL,
      name TEXT NOT NULL,
      default_branch TEXT NOT NULL,
      status TEXT NOT NULL,
      provider_config_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, provider, external_repo_id)
    );

    CREATE TABLE IF NOT EXISTS merge_requests (
      id TEXT PRIMARY KEY,
      repository_id TEXT NOT NULL,
      external_mr_id TEXT NOT NULL,
      number INTEGER NOT NULL,
      title TEXT NOT NULL,
      author TEXT NOT NULL,
      source_branch TEXT NOT NULL,
      target_branch TEXT NOT NULL,
      review_status TEXT NOT NULL,
      risk_score INTEGER NOT NULL DEFAULT 0,
      latest_head_sha TEXT NOT NULL,
      html_url TEXT NOT NULL,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(repository_id, external_mr_id)
    );

    CREATE TABLE IF NOT EXISTS review_jobs (
      id TEXT PRIMARY KEY,
      merge_request_id TEXT NOT NULL,
      head_sha TEXT NOT NULL,
      status TEXT NOT NULL,
      priority INTEGER NOT NULL DEFAULT 0,
      requested_effort_level TEXT NOT NULL DEFAULT 'standard',
      attempt INTEGER NOT NULL DEFAULT 0,
      locked_at TEXT,
      locked_by TEXT,
      heartbeat_at TEXT,
      requested_by TEXT,
      pr_summary TEXT NOT NULL DEFAULT '{}',
      debug_context_json TEXT NOT NULL DEFAULT '{}',
      execution_kind TEXT NOT NULL DEFAULT 'production_review',
      debug_session_id TEXT,
      debug_variant TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS skill_debug_sessions (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      repository_id TEXT NOT NULL,
      merge_request_id TEXT NOT NULL,
      head_sha TEXT NOT NULL,
      skill_key TEXT NOT NULL,
      skill_version TEXT NOT NULL,
      agent_key TEXT NOT NULL,
      mode TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      requested_effort_level TEXT NOT NULL DEFAULT 'standard',
      requested_by TEXT NOT NULL,
      snapshot_json TEXT NOT NULL DEFAULT '{}',
      snapshot_sha256 TEXT NOT NULL,
      baseline_job_id TEXT,
      candidate_job_id TEXT,
      comparison_json TEXT NOT NULL DEFAULT '{}',
      failure_reason TEXT,
      cancelled_at TEXT,
      expires_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_runs (
      id TEXT PRIMARY KEY,
      review_job_id TEXT NOT NULL,
      effort_level TEXT NOT NULL,
      risk_score INTEGER NOT NULL DEFAULT 0,
      rule_version_source TEXT NOT NULL DEFAULT 'target_branch',
      sandbox_uri TEXT,
      budget_json TEXT NOT NULL DEFAULT '{}',
      budget_used_json TEXT NOT NULL DEFAULT '{}',
      coverage_json TEXT NOT NULL DEFAULT '{}',
      toolchain_manifest TEXT NOT NULL DEFAULT '{}',
      data_policy_snapshot TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL,
      report_summary TEXT,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS review_findings (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      severity TEXT NOT NULL,
      confidence REAL NOT NULL,
      agent_id TEXT NOT NULL,
      head_sha TEXT NOT NULL,
      dedupe_hash TEXT NOT NULL,
      file_path TEXT NOT NULL,
      line_start INTEGER,
      line_end INTEGER,
      title TEXT NOT NULL,
      problem_description TEXT NOT NULL,
      recommendation TEXT NOT NULL,
      suggested_code TEXT NOT NULL DEFAULT '',
      evidence TEXT NOT NULL,
      tool_provenance_json TEXT NOT NULL DEFAULT '[]',
      source_observations_json TEXT NOT NULL DEFAULT '[]',
      quality_trace_json TEXT NOT NULL DEFAULT '{}',
      evidence_score_json TEXT NOT NULL DEFAULT '{}',
      publish_state TEXT NOT NULL DEFAULT 'pending',
      lifecycle_state TEXT NOT NULL DEFAULT 'pending',
      selected INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_finding_dedupe ON review_findings(dedupe_hash);

    CREATE TABLE IF NOT EXISTS candidate_findings (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      dedupe_hash TEXT NOT NULL,
      stage TEXT NOT NULL,
      status TEXT NOT NULL,
      source_type TEXT NOT NULL DEFAULT 'agent',
      agent_id TEXT,
      tool_name TEXT,
      rule_id TEXT,
      severity TEXT,
      confidence REAL NOT NULL DEFAULT 0,
      file_path TEXT NOT NULL DEFAULT '',
      line_start INTEGER,
      line_end INTEGER,
      title TEXT NOT NULL DEFAULT '',
      problem_description TEXT NOT NULL DEFAULT '',
      evidence TEXT NOT NULL DEFAULT '',
      rejected_reasons_json TEXT NOT NULL DEFAULT '[]',
      source_observations_json TEXT NOT NULL DEFAULT '[]',
      raw_json TEXT NOT NULL DEFAULT '{}',
      final_finding_id TEXT,
      decision_reason_json TEXT NOT NULL DEFAULT '[]',
      decision_stage TEXT,
      decided_at TEXT,
      merged_into_candidate_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(review_run_id, dedupe_hash, stage)
    );

    CREATE INDEX IF NOT EXISTS idx_candidate_findings_run_stage
      ON candidate_findings(review_run_id, stage, status);

    CREATE INDEX IF NOT EXISTS idx_candidate_findings_rule
      ON candidate_findings(rule_id, status);

    CREATE TABLE IF NOT EXISTS mr_finding_history (
      id TEXT PRIMARY KEY,
      merge_request_id TEXT NOT NULL,
      dedupe_hash TEXT NOT NULL,
      finding_id TEXT,
      first_seen_head_sha TEXT NOT NULL,
      last_seen_head_sha TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      resolved_in_commit TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(merge_request_id, dedupe_hash)
    );

    CREATE INDEX IF NOT EXISTS idx_mr_finding_history_mr_status
      ON mr_finding_history(merge_request_id, status);

    CREATE TABLE IF NOT EXISTS rule_precision_history (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      rule_id TEXT NOT NULL,
      accepted_count INTEGER NOT NULL DEFAULT 0,
      rejected_count INTEGER NOT NULL DEFAULT 0,
      recent_accepted_count INTEGER NOT NULL DEFAULT 0,
      recent_rejected_count INTEGER NOT NULL DEFAULT 0,
      auto_suppress INTEGER NOT NULL DEFAULT 0,
      last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, agent_id, rule_id)
    );

    CREATE INDEX IF NOT EXISTS idx_rule_precision_project_agent
      ON rule_precision_history(project_id, agent_id);

    CREATE TABLE IF NOT EXISTS agent_trace_spans (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      parent_span_id TEXT,
      span_key TEXT NOT NULL,
      agent_id TEXT,
      status TEXT NOT NULL,
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      ended_at TEXT
    );

    CREATE TABLE IF NOT EXISTS agent_trace_events (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      summary TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS agent_messages (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL,
      from_agent TEXT NOT NULL,
      to_agent TEXT NOT NULL,
      role TEXT NOT NULL,
      content_summary TEXT NOT NULL,
      artifact_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS llm_call_records (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      request_id TEXT,
      prompt_hash TEXT,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      operation TEXT NOT NULL DEFAULT '',
      agent_id TEXT NOT NULL DEFAULT '',
      context_unit_id TEXT NOT NULL DEFAULT '',
      context_hash TEXT NOT NULL DEFAULT '',
      checkpoint_id TEXT NOT NULL DEFAULT '',
      seed INTEGER,
      temperature DOUBLE PRECISION,
      request_hash TEXT NOT NULL DEFAULT '',
      response_hash TEXT NOT NULL DEFAULT '',
      cache_key TEXT NOT NULL DEFAULT '',
      replay_source TEXT NOT NULL DEFAULT '',
      response_artifact_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS llm_exchange_records (
      cache_key TEXT PRIMARY KEY,
      operation TEXT NOT NULL,
      agent_id TEXT NOT NULL DEFAULT '',
      context_unit_id TEXT NOT NULL DEFAULT '',
      context_hash TEXT NOT NULL DEFAULT '',
      checkpoint_id TEXT NOT NULL DEFAULT '',
      head_sha TEXT NOT NULL DEFAULT '',
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      seed INTEGER NOT NULL,
      temperature DOUBLE PRECISION NOT NULL DEFAULT 0,
      request_hash TEXT NOT NULL,
      response_hash TEXT NOT NULL,
      response_json TEXT NOT NULL,
      review_run_id TEXT NOT NULL DEFAULT '',
      expires_at TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS token_usage_reports (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      review_job_id TEXT NOT NULL,
      merge_request_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      repository_id TEXT NOT NULL,
      employee_no TEXT NOT NULL,
      reported_at TEXT NOT NULL,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      total_tokens INTEGER NOT NULL DEFAULT 0,
      llm_calls INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      endpoint TEXT NOT NULL DEFAULT '',
      response_status INTEGER,
      response_body TEXT NOT NULL DEFAULT '',
      error_message TEXT NOT NULL DEFAULT '',
      payload_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(review_run_id)
    );

    CREATE INDEX IF NOT EXISTS idx_token_usage_reports_project_created
      ON token_usage_reports(project_id, created_at);

    CREATE TABLE IF NOT EXISTS tool_call_records (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      tool_version TEXT,
      args_summary TEXT NOT NULL DEFAULT '',
      input_ref_json TEXT NOT NULL DEFAULT '{}',
      output_summary TEXT NOT NULL DEFAULT '',
      output_ref_json TEXT NOT NULL DEFAULT '{}',
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS mcp_call_records (
      id TEXT PRIMARY KEY,
      span_id TEXT NOT NULL,
      server_name TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      request_summary TEXT NOT NULL DEFAULT '',
      response_summary TEXT NOT NULL DEFAULT '',
      duration_ms INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_artifacts (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      artifact_type TEXT NOT NULL,
      name TEXT NOT NULL,
      storage_uri TEXT NOT NULL,
      sha256 TEXT NOT NULL,
      size_bytes INTEGER NOT NULL DEFAULT 0,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS code_index_snapshots (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      repository_id TEXT NOT NULL,
      commit_sha TEXT NOT NULL,
      index_kind TEXT NOT NULL,
      storage_uri TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS agent_configs (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      display_name TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      applies_to_json TEXT NOT NULL DEFAULT '{}',
      tools_json TEXT NOT NULL DEFAULT '[]',
      skills_json TEXT NOT NULL DEFAULT '[]',
      rule_sets_json TEXT NOT NULL DEFAULT '[]',
      requires_deepagents INTEGER NOT NULL DEFAULT 0,
      min_confidence REAL NOT NULL DEFAULT 0.75,
      max_findings_per_mr INTEGER NOT NULL DEFAULT 12,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, agent_id)
    );

    CREATE TABLE IF NOT EXISTS expert_profiles (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_key TEXT NOT NULL,
      display_name TEXT NOT NULL,
      role_profile TEXT NOT NULL,
      responsibility_scope TEXT NOT NULL,
      excluded_scope TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1,
      min_confidence REAL NOT NULL DEFAULT 0.75,
      max_findings INTEGER NOT NULL DEFAULT 12,
      max_llm_calls INTEGER NOT NULL DEFAULT 6,
      max_tool_calls INTEGER NOT NULL DEFAULT 12,
      output_schema_version TEXT NOT NULL DEFAULT 'finding_v1',
      UNIQUE(project_id, agent_key)
    );

    CREATE TABLE IF NOT EXISTS rule_sets (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      name TEXT NOT NULL,
      version TEXT NOT NULL,
      scope_json TEXT NOT NULL DEFAULT '{}',
      content TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS rule_documents (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      name TEXT NOT NULL,
      doc_type TEXT NOT NULL DEFAULT 'markdown',
      content TEXT NOT NULL,
      version TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'draft',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS expert_rule_bindings (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_key TEXT NOT NULL,
      rule_document_id TEXT NOT NULL,
      priority INTEGER NOT NULL DEFAULT 100,
      UNIQUE(project_id, agent_key, rule_document_id)
    );

    CREATE TABLE IF NOT EXISTS custom_skills (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      skill_key TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      content TEXT NOT NULL,
      version TEXT NOT NULL DEFAULT 'v1',
      status TEXT NOT NULL DEFAULT 'active',
      active_version_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, skill_key)
    );

    CREATE TABLE IF NOT EXISTS custom_skill_assets (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      skill_key TEXT NOT NULL,
      asset_path TEXT NOT NULL,
      asset_type TEXT NOT NULL DEFAULT 'reference',
      content TEXT NOT NULL,
      executable INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, skill_key, asset_path)
    );

    CREATE TABLE IF NOT EXISTS custom_skill_versions (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      skill_key TEXT NOT NULL,
      version TEXT NOT NULL,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      content TEXT NOT NULL,
      assets_json TEXT NOT NULL DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'draft',
      bundle_sha256 TEXT NOT NULL DEFAULT '',
      validation_json TEXT NOT NULL DEFAULT '{}',
      checkpoint_manifest_json TEXT NOT NULL DEFAULT '{}',
      checkpoint_compiler_version TEXT NOT NULL DEFAULT '',
      created_by TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, skill_key, version)
    );

    CREATE TABLE IF NOT EXISTS expert_skill_bindings (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_key TEXT NOT NULL,
      skill_key TEXT NOT NULL,
      priority INTEGER NOT NULL DEFAULT 100,
      enabled INTEGER NOT NULL DEFAULT 1,
      UNIQUE(project_id, agent_key, skill_key)
    );

    CREATE TABLE IF NOT EXISTS expert_tool_bindings (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      agent_key TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      permission_level TEXT NOT NULL DEFAULT 'read_only',
      max_calls INTEGER NOT NULL DEFAULT 5,
      enabled INTEGER NOT NULL DEFAULT 1,
      UNIQUE(project_id, agent_key, tool_name)
    );

    CREATE TABLE IF NOT EXISTS tool_observations (
      id TEXT PRIMARY KEY,
      review_run_id TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      rule_id TEXT,
      severity TEXT,
      confidence REAL NOT NULL DEFAULT 0.5,
      file_path TEXT NOT NULL,
      line_start INTEGER,
      line_end INTEGER,
      message TEXT NOT NULL,
      raw_artifact_id TEXT,
      adopted_by_agent TEXT,
      adoption_state TEXT NOT NULL DEFAULT 'candidate',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS external_review_reports (
      id TEXT PRIMARY KEY,
      merge_request_id TEXT NOT NULL,
      report_type TEXT NOT NULL,
      commit_sha TEXT NOT NULL,
      report_format TEXT NOT NULL,
      report_url TEXT,
      payload_json TEXT NOT NULL DEFAULT '{}',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'received',
      created_by TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_baseline_suppressions (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      tool_name TEXT NOT NULL,
      rule_id TEXT,
      normalized_rule_category TEXT,
      file_path TEXT NOT NULL,
      line_start INTEGER,
      fingerprint TEXT NOT NULL,
      reason TEXT,
      expires_at TEXT,
      created_by TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id, fingerprint)
    );

    CREATE TABLE IF NOT EXISTS review_policy (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      policy_json TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(project_id)
    );

    CREATE TABLE IF NOT EXISTS user_feedback (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      finding_id TEXT,
      dedupe_hash TEXT NOT NULL,
      feedback_type TEXT NOT NULL,
      scope TEXT NOT NULL,
      reason TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS rule_suppression_hints (
      project_id TEXT NOT NULL,
      rule_id TEXT NOT NULL,
      file_glob TEXT NOT NULL,
      snippet_hash TEXT NOT NULL,
      snippet_excerpt TEXT NOT NULL,
      count INTEGER NOT NULL DEFAULT 1,
      last_marked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (project_id, rule_id, file_glob, snippet_hash)
    );

    CREATE TABLE IF NOT EXISTS llm_response_cache (
      cache_key TEXT PRIMARY KEY,
      project_id TEXT NOT NULL DEFAULT 'project_default',
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      schema_name TEXT NOT NULL,
      seed INTEGER NOT NULL,
      prompt_hash TEXT NOT NULL,
      response_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS review_jobs_dead_letter (
      id TEXT PRIMARY KEY,
      review_job_id TEXT NOT NULL,
      failure_reason TEXT NOT NULL,
      final_attempt INTEGER NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS vcs_publish_records (
      id TEXT PRIMARY KEY,
      finding_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      external_comment_id TEXT,
      external_thread_id TEXT,
      publish_status TEXT NOT NULL,
      published_by TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS webhook_dead_letter (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      provider TEXT NOT NULL,
      event_type TEXT NOT NULL,
      payload_sha TEXT NOT NULL,
      failure_reason TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS evaluation_gold_set (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      finding_id TEXT,
      agent_id TEXT NOT NULL,
      severity TEXT NOT NULL,
      expected_title TEXT NOT NULL,
      expected_file_path TEXT NOT NULL,
      expected_line INTEGER,
      label TEXT NOT NULL,
      source TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS evaluation_reports (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      report_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS full_review_jobs (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      repository_id TEXT,
      commit_sha TEXT NOT NULL DEFAULT '',
      scope_json TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL,
      requested_by TEXT,
      attempt INTEGER NOT NULL DEFAULT 0,
      locked_at TEXT,
      locked_by TEXT,
      heartbeat_at TEXT,
      failure_reason TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_full_review_jobs_project_status
      ON full_review_jobs(project_id, status, created_at);

    CREATE TABLE IF NOT EXISTS full_review_snapshots (
      id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      repository_id TEXT NOT NULL,
      commit_sha TEXT NOT NULL,
      index_snapshot_id TEXT,
      summary_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_full_review_snapshots_job
      ON full_review_snapshots(job_id);

    CREATE TABLE IF NOT EXISTS full_review_findings (
      id TEXT PRIMARY KEY,
      snapshot_id TEXT NOT NULL,
      severity TEXT NOT NULL,
      confidence REAL NOT NULL,
      agent_id TEXT NOT NULL,
      file_path TEXT NOT NULL,
      line_start INTEGER,
      line_end INTEGER,
      title TEXT NOT NULL,
      problem_description TEXT NOT NULL,
      recommendation TEXT NOT NULL,
      suggested_code TEXT NOT NULL DEFAULT '',
      evidence TEXT NOT NULL,
      covered_rules_json TEXT NOT NULL DEFAULT '[]',
      tool_provenance_json TEXT NOT NULL DEFAULT '[]',
      source_observations_json TEXT NOT NULL DEFAULT '[]',
      quality_trace_json TEXT NOT NULL DEFAULT '{}',
      evidence_score_json TEXT NOT NULL DEFAULT '{}',
      lifecycle_state TEXT NOT NULL DEFAULT 'pending',
      selected INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_full_review_findings_snapshot
      ON full_review_findings(snapshot_id);

    CREATE INDEX IF NOT EXISTS idx_repositories_project_status_created
      ON repositories(project_id, status, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_merge_requests_repo_status_updated
      ON merge_requests(repository_id, review_status, updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_merge_requests_repo_risk_updated
      ON merge_requests(repository_id, risk_score DESC, updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_review_jobs_mr_updated_created
      ON review_jobs(merge_request_id, updated_at DESC, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_review_jobs_status_heartbeat
      ON review_jobs(status, heartbeat_at, locked_at, updated_at);

    CREATE INDEX IF NOT EXISTS idx_skill_debug_sessions_project_created
      ON skill_debug_sessions(project_id, created_at DESC);

    CREATE INDEX IF NOT EXISTS idx_skill_debug_sessions_status_created
      ON skill_debug_sessions(status, created_at);

    CREATE INDEX IF NOT EXISTS idx_review_runs_job_started
      ON review_runs(review_job_id, started_at DESC);

    CREATE INDEX IF NOT EXISTS idx_review_findings_run_severity_confidence
      ON review_findings(review_run_id, severity DESC, confidence DESC);

    CREATE INDEX IF NOT EXISTS idx_agent_trace_spans_run_started
      ON agent_trace_spans(review_run_id, started_at);

    CREATE INDEX IF NOT EXISTS idx_agent_trace_events_span_created
      ON agent_trace_events(span_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_agent_messages_span_created
      ON agent_messages(span_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_llm_call_records_span_created
      ON llm_call_records(span_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_tool_call_records_span_created
      ON tool_call_records(span_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_mcp_call_records_span_created
      ON mcp_call_records(span_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_tool_observations_run_created
      ON tool_observations(review_run_id, created_at);

    CREATE INDEX IF NOT EXISTS idx_review_artifacts_run_created
      ON review_artifacts(review_run_id, created_at);
  `);
  db.exec(`
    INSERT INTO custom_skill_versions (
      id, project_id, skill_key, version, name, description, content, assets_json, status, created_at, updated_at
    )
    SELECT
      'skill_version_' || cs.id,
      cs.project_id,
      cs.skill_key,
      cs.version,
      cs.name,
      cs.description,
      cs.content,
      COALESCE((
        SELECT json_agg(json_build_object(
          'id', csa.id,
          'skill_key', csa.skill_key,
          'asset_path', csa.asset_path,
          'asset_type', csa.asset_type,
          'content', csa.content,
          'executable', csa.executable
        ) ORDER BY csa.asset_path)::text
        FROM custom_skill_assets csa
        WHERE csa.project_id = cs.project_id AND csa.skill_key = cs.skill_key
      ), '[]'),
      cs.status,
      cs.created_at,
      cs.updated_at
    FROM custom_skills cs
    ON CONFLICT(project_id, skill_key, version) DO NOTHING;
  `);
  addColumnIfMissing(db, "review_findings", "covered_rules_json", "TEXT NOT NULL DEFAULT '[]'");
  addColumnIfMissing(db, "review_findings", "skipped_rules_json", "TEXT NOT NULL DEFAULT '[]'");
  addColumnIfMissing(db, "review_findings", "suggested_code", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "review_findings", "tool_provenance_json", "TEXT NOT NULL DEFAULT '[]'");
  addColumnIfMissing(db, "review_findings", "source_observations_json", "TEXT NOT NULL DEFAULT '[]'");
  addColumnIfMissing(db, "review_findings", "quality_trace_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "review_findings", "evidence_score_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "agent_configs", "requires_deepagents", "INTEGER NOT NULL DEFAULT 0");
  addColumnIfMissing(db, "review_jobs", "pr_summary", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "review_jobs", "debug_context_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "review_jobs", "requested_by", "TEXT");
  addColumnIfMissing(db, "review_jobs", "execution_kind", "TEXT NOT NULL DEFAULT 'production_review'");
  addColumnIfMissing(db, "review_jobs", "debug_session_id", "TEXT");
  addColumnIfMissing(db, "review_jobs", "debug_variant", "TEXT");
  replaceLegacyReviewJobUniqueness(db);
  addColumnIfMissing(db, "merge_requests", "created_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP");
  addColumnIfMissing(db, "rule_precision_history", "recent_accepted_count", "INTEGER NOT NULL DEFAULT 0");
  addColumnIfMissing(db, "rule_precision_history", "recent_rejected_count", "INTEGER NOT NULL DEFAULT 0");
  addColumnIfMissing(db, "review_runs", "coverage_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "candidate_findings", "decision_reason_json", "TEXT NOT NULL DEFAULT '[]'");
  addColumnIfMissing(db, "candidate_findings", "decision_stage", "TEXT");
  addColumnIfMissing(db, "candidate_findings", "decided_at", "TEXT");
  addColumnIfMissing(db, "candidate_findings", "merged_into_candidate_id", "TEXT");
  addColumnIfMissing(db, "full_review_jobs", "attempt", "INTEGER NOT NULL DEFAULT 0");
  addColumnIfMissing(db, "full_review_jobs", "locked_at", "TEXT");
  addColumnIfMissing(db, "full_review_jobs", "locked_by", "TEXT");
  addColumnIfMissing(db, "full_review_jobs", "heartbeat_at", "TEXT");
  addColumnIfMissing(db, "full_review_jobs", "failure_reason", "TEXT");
  addColumnIfMissing(db, "llm_response_cache", "project_id", "TEXT NOT NULL DEFAULT 'project_default'");
  addColumnIfMissing(db, "llm_call_records", "operation", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "agent_id", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "context_unit_id", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "context_hash", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "checkpoint_id", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "seed", "INTEGER");
  addColumnIfMissing(db, "llm_call_records", "temperature", "DOUBLE PRECISION");
  addColumnIfMissing(db, "llm_call_records", "request_hash", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "response_hash", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "cache_key", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "replay_source", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_call_records", "response_artifact_id", "TEXT");
  addColumnIfMissing(db, "llm_exchange_records", "review_run_id", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "llm_exchange_records", "expires_at", "TEXT");
  db.exec(`
    CREATE INDEX IF NOT EXISTS idx_llm_exchange_records_run
      ON llm_exchange_records(review_run_id);
    CREATE INDEX IF NOT EXISTS idx_llm_exchange_records_expires
      ON llm_exchange_records(expires_at);
  `);
  addColumnIfMissing(db, "custom_skills", "active_version_id", "TEXT");
  addColumnIfMissing(db, "custom_skill_versions", "bundle_sha256", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "custom_skill_versions", "validation_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "custom_skill_versions", "checkpoint_manifest_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "custom_skill_versions", "checkpoint_compiler_version", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "custom_skill_versions", "created_by", "TEXT");
  addColumnIfMissing(db, "skill_debug_sessions", "bundle_sha256", "TEXT NOT NULL DEFAULT ''");
  addColumnIfMissing(db, "skill_debug_sessions", "validity_contract", "TEXT NOT NULL DEFAULT 'skill_debug_validity_v1'");
  addColumnIfMissing(db, "skill_debug_sessions", "validity_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "skill_debug_sessions", "input_artifact_json", "TEXT NOT NULL DEFAULT '{}'");
  addColumnIfMissing(db, "skill_debug_sessions", "input_artifact_sha256", "TEXT NOT NULL DEFAULT ''");
  repairCanonicalSkillVersions(db);
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function normalizedAssets(value: unknown): Array<Record<string, unknown>> {
  const parsed = typeof value === "string" ? (() => { try { return JSON.parse(value); } catch { return []; } })() : value;
  if (!Array.isArray(parsed)) return [];
  return parsed
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      skill_key: String(item.skill_key || ""),
      asset_path: String(item.asset_path || ""),
      asset_type: String(item.asset_type || "reference"),
      content: String(item.content || ""),
      executable: Boolean(item.executable)
    }))
    .sort((left, right) => String(left.asset_path).localeCompare(String(right.asset_path)));
}

function skillBundleHash(skill: Record<string, unknown>, assets: Array<Record<string, unknown>>) {
  const canonical = {
    skill_key: String(skill.skill_key || ""),
    version: String(skill.version || ""),
    name: String(skill.name || ""),
    description: String(skill.description || ""),
    content: String(skill.content || ""),
    assets
  };
  return createHash("sha256").update(stableStringify(canonical)).digest("hex");
}

function repairCanonicalSkillVersions(db: Db) {
  const skills = db.prepare("SELECT * FROM custom_skills WHERE status = 'active'").all() as Array<Record<string, unknown>>;
  for (const skill of skills) {
    const version = db.prepare(`
      SELECT * FROM custom_skill_versions
      WHERE project_id = $1 AND skill_key = $2 AND version = $3
    `).get(skill.project_id, skill.skill_key, skill.version) as Record<string, unknown> | undefined;
    if (!version) continue;
    const liveAssets = db.prepare(`
      SELECT skill_key, asset_path, asset_type, content, executable
      FROM custom_skill_assets WHERE project_id = $1 AND skill_key = $2 ORDER BY asset_path
    `).all(skill.project_id, skill.skill_key) as Array<Record<string, unknown>>;
    const storedAssets = normalizedAssets(version.assets_json);
    const assets = liveAssets.length && storedAssets.length === 0 ? normalizedAssets(liveAssets) : storedAssets;
    const bundleSha256 = skillBundleHash(version, assets);
    db.prepare(`
      UPDATE custom_skill_versions
      SET assets_json = $1, bundle_sha256 = $2,
          validation_json = CASE WHEN validation_json = '{}' THEN $3 ELSE validation_json END
      WHERE id = $4
    `).run(JSON.stringify(assets), bundleSha256, JSON.stringify({ migrated: true, ok: true }), version.id);
    db.prepare("UPDATE custom_skills SET active_version_id = $1 WHERE id = $2").run(version.id, skill.id);
  }
}

function replaceLegacyReviewJobUniqueness(db: Db) {
  const constraints = db.prepare(`
    SELECT c.conname AS name
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname = 'review_jobs'
      AND c.contype = 'u'
      AND pg_get_constraintdef(c.oid) = 'UNIQUE (merge_request_id, head_sha)'
  `).all() as Array<{ name: string }>;
  for (const constraint of constraints) {
    const quoted = String(constraint.name).replaceAll('"', '""');
    db.exec(`ALTER TABLE review_jobs DROP CONSTRAINT "${quoted}"`);
  }
  db.exec(`
    CREATE UNIQUE INDEX IF NOT EXISTS ux_review_jobs_production_mr_head
    ON review_jobs(merge_request_id, head_sha)
    WHERE execution_kind = 'production_review';
  `);
}

function addColumnIfMissing(db: Db, table: string, column: string, definition: string) {
  const rows = db.prepare(`
    SELECT column_name AS name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = $1
      AND column_name = $2
  `).all(table, column) as Array<{ name: string }>;
  if (!rows.length) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
  }
}
