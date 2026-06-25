import { route, type Route } from "../http.js";
import type { BackendRouteContext } from "./context.js";

interface EvaluationReportRow {
  id: string;
  project_id: string;
  report_json: string;
  created_at: string;
}

export function createQualityRoutes(ctx: BackendRouteContext): Route[] {
  const { all, get } = ctx;
  const routes: Route[] = [
    route("GET", "/api/projects/:projectId/review-quality/summary", ({ params }) => {
      const llmCalls = all(`
        SELECT COUNT(*) AS count, COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens
        FROM llm_call_records l
        JOIN agent_trace_spans s ON s.id = l.span_id
        JOIN review_runs rr ON rr.id = s.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
      `, [params.projectId])[0];
      const feedback = all<{ feedback_type: string; count: number }>(`
        SELECT uf.feedback_type, COUNT(*) AS count
        FROM user_feedback uf
        JOIN review_findings rf ON rf.id = uf.finding_id
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ?
        GROUP BY uf.feedback_type
      `, [params.projectId]);
      const accepted = Number(feedback.find((item) => item.feedback_type === "accepted")?.count ?? 0);
      const falsePositive = Number(feedback.find((item) => item.feedback_type === "false_positive")?.count ?? 0);
      const reviewedFeedback = accepted + falsePositive;
      return {
        project_id: params.projectId,
        llm_calls: llmCalls,
        findings_by_state: all(`
          SELECT rf.lifecycle_state, COUNT(*) AS count
          FROM review_findings rf
          JOIN review_runs rr ON rr.id = rf.review_run_id
          JOIN review_jobs rj ON rj.id = rr.review_job_id
          JOIN merge_requests mr ON mr.id = rj.merge_request_id
          JOIN repositories r ON r.id = mr.repository_id
          WHERE r.project_id = ?
          GROUP BY rf.lifecycle_state
        `, [params.projectId]),
        feedback,
        operational_feedback_metrics: {
          metric_type: "reviewer_feedback_precision_estimate",
          data_source: "user_feedback",
          confidence: "operational",
          accepted_findings: accepted,
          false_positive_findings: falsePositive,
          reviewed_feedback_count: reviewedFeedback,
          precision_estimate: reviewedFeedback ? accepted / reviewedFeedback : null
        }
      };
    }),

    route("GET", "/api/projects/:projectId/evaluation-reports", ({ params }) => {
      const accepted = Number(get<{ count: number }>(`
        SELECT COUNT(*) AS count
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ? AND rf.lifecycle_state = 'accepted'
      `, [params.projectId])?.count ?? 0);
      const falsePositive = Number(get<{ count: number }>(`
        SELECT COUNT(*) AS count
        FROM user_feedback uf
        JOIN review_findings rf ON rf.id = uf.finding_id
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        WHERE r.project_id = ? AND uf.feedback_type = 'false_positive'
      `, [params.projectId])?.count ?? 0);
      const goldSetCount = Number(get<{ count: number }>(
        "SELECT COUNT(*) AS count FROM evaluation_gold_set WHERE project_id = ?",
        [params.projectId]
      )?.count ?? 0);
      const storedReports = all<EvaluationReportRow>(
        "SELECT * FROM evaluation_reports WHERE project_id = ? ORDER BY created_at DESC",
        [params.projectId]
      ).map((row) => ({
        ...row,
        report: JSON.parse(row.report_json || "{}"),
        report_json: undefined
      }));
      const reviewedFeedback = accepted + falsePositive;
      const liveReport = {
        id: `operational_${params.projectId}`,
        project_id: params.projectId,
        report_type: "operational_feedback",
        data_source: "review_findings,user_feedback",
        accepted_findings: accepted,
        false_positive_findings: falsePositive,
        reviewed_feedback_count: reviewedFeedback,
        precision_estimate: reviewedFeedback ? accepted / reviewedFeedback : null,
        confidence: "operational",
        gold_set_count: goldSetCount
      };
      return { project_id: params.projectId, items: [liveReport, ...storedReports] };
    }),

    route("GET", "/api/projects/:projectId/rule-health", ({ params }) => ({
      project_id: params.projectId,
      items: all(`
        SELECT
          rf.agent_id,
          rf.title AS rule_or_title,
          COUNT(*) AS finding_count,
          SUM(CASE WHEN uf.feedback_type = 'false_positive' THEN 1 ELSE 0 END) AS false_positive_count,
          ROUND(CAST(1.0 * SUM(CASE WHEN uf.feedback_type = 'false_positive' THEN 1 ELSE 0 END) / COUNT(*) AS NUMERIC), 3) AS false_positive_rate
        FROM review_findings rf
        JOIN review_runs rr ON rr.id = rf.review_run_id
        JOIN review_jobs rj ON rj.id = rr.review_job_id
        JOIN merge_requests mr ON mr.id = rj.merge_request_id
        JOIN repositories r ON r.id = mr.repository_id
        LEFT JOIN user_feedback uf ON uf.finding_id = rf.id
        WHERE r.project_id = ?
        GROUP BY rf.agent_id, rf.title
        ORDER BY false_positive_rate DESC, finding_count DESC
        LIMIT 30
      `, [params.projectId])
    }))
  ];
  return routes;
}
