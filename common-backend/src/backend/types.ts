export interface AppConfig {
  [key: string]: unknown;
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
}
