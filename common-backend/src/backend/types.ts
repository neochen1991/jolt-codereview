export interface AppConfig {
  [key: string]: unknown;
  github?: {
    default_endpoint?: string;
    default_token_env?: string;
  };
  codehub?: {
    default_endpoint?: string;
    default_token_env?: string;
  };
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
  };
  cleanup_policy?: {
    enabled?: boolean;
    run_on_startup?: boolean;
    interval_seconds?: number;
    max_age_days?: number;
    max_total_mb?: number;
    max_log_file_mb?: number;
  };
}

export type VcsProviderName = "github" | "codehub";

export interface RepositoryConfig {
  endpoint?: string;
  owner?: string;
  repo?: string;
  git_url?: string;
  git_host?: string;
  full_name?: string;
  project_key?: string;
  repo_id?: string;
  token_env?: string;
  [key: string]: unknown;
}
