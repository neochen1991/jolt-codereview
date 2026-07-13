export type VcsProviderName = "github" | "codehub";

export interface AppConfig {
  llm?: {
    default_provider?: string;
    default_base_url?: string;
    default_model?: string;
    default_api_key_env?: string | null;
    default_api_key?: string | null;
    request_timeout_seconds?: number;
    max_output_tokens?: number;
    enable_stream?: boolean;
  };
  github?: {
    default_token_env?: string;
    default_token?: string | null;
    default_endpoint?: string;
    webhook_secret?: string;
  };
  codehub?: {
    default_token_env?: string;
    default_token?: string | null;
    default_endpoint?: string;
    webhook_secret?: string;
  };
  server?: {
    host?: string;
    port?: number;
    common_port?: number;
    mr_port?: number;
    database_driver?: "postgres";
    postgres_url?: string;
    postgres_user?: string;
    postgres_password?: string;
    postgres_query_timeout_seconds?: number;
  };
  logging?: {
    enabled?: boolean;
    dir?: string;
    api_file?: string;
    worker_file?: string;
    review_run_dir?: string;
  };
  cleanup_policy?: {
    enabled?: boolean;
    run_on_startup?: boolean;
    interval_seconds?: number;
    max_age_days?: number;
    max_total_mb?: number;
    max_log_file_mb?: number;
  };
  budget_policy?: Record<string, unknown>;
  token_usage?: {
    enabled?: boolean;
    endpoint?: string;
    method?: string;
    timeout_seconds?: number;
    auth_header?: string;
    auth_token_env?: string | null;
    auth_token?: string | null;
    employee_no_env?: string | null;
    default_employee_no?: string | null;
    service_name?: string;
  };
  runtime?: {
    python_bin?: string | null;
  };
  review_policy?: Record<string, unknown>;
  agent_policy?: Record<string, unknown>;
  tool_policy?: Record<string, unknown>;
  queue_policy?: Record<string, unknown>;
  skill_debug_policy?: {
    project_max_concurrency?: number;
    user_max_concurrency?: number;
    daily_session_limit?: number;
    daily_token_limit?: number;
    max_duration_seconds?: number;
    retention_days?: number;
  };
  publish_policy?: Record<string, unknown>;
  data_policy?: Record<string, unknown>;
}

export interface RepositoryConfig {
  endpoint?: string;
  git_url?: string;
  git_host?: string;
  full_name?: string;
  owner?: string;
  repo?: string;
  project_key?: string;
  repo_id?: string;
  token_env?: string;
  token?: string;
  token_ref?: string;
  list_mrs_path?: string;
  mr_path_template?: string;
  diff_path_template?: string;
  files_path_template?: string;
  file_path_template?: string;
  comment_path_template?: string;
  status_path_template?: string;
  webhook_secret?: string;
}

export interface MergeRequestRow {
  id: string;
  repository_id: string;
  external_mr_id: string;
  number: number;
  title: string;
  author: string;
  source_branch: string;
  target_branch: string;
  review_status: string;
  risk_score: number;
  latest_head_sha: string;
  html_url: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
}

export interface FindingRow {
  id: string;
  review_run_id: string;
  severity: string;
  confidence: number;
  agent_id: string;
  head_sha: string;
  dedupe_hash: string;
  file_path: string;
  line_start: number | null;
  line_end: number | null;
  title: string;
  problem_description: string;
  recommendation: string;
  suggested_code: string;
  evidence: string;
  covered_rules_json?: string;
  skipped_rules_json?: string;
  tool_provenance_json?: string;
  source_observations_json?: string;
  quality_trace_json?: string;
  evidence_score_json?: string;
  publish_state: string;
  lifecycle_state: string;
  selected: number;
}
