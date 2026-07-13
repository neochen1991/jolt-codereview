export const QUALITY_GATE_VERSION = "review_quality_uplift_v1";

function number(report, key) {
  const value = Number(report?.[key]);
  return Number.isFinite(value) ? value : null;
}

export function evaluateReviewQualityUplift(baseline, candidate) {
  const checks = [];
  const add = (metric, passed, actual, required) => checks.push({ metric, passed, actual, required });
  const sampleCount = number(candidate, "sample_count") ?? 0;
  const distinctMrCount = number(candidate, "distinct_mr_count") ?? 0;
  const recall = number(candidate, "recall");
  const baselineRecall = number(baseline, "recall");
  const crossRecall = number(candidate, "cross_file_recall");
  const baselineCrossRecall = number(baseline, "cross_file_recall");
  const precision = number(candidate, "precision");
  const baselinePrecision = number(baseline, "precision");
  const criticalHighRecall = number(candidate, "critical_high_recall");
  const negativeFp = number(candidate, "negative_false_positive_count");
  const baselineNegativeFp = number(baseline, "negative_false_positive_count");
  const tokenP95 = number(candidate, "p95_tokens");
  const baselineTokenP95 = number(baseline, "p95_tokens");
  const durationP95 = number(candidate, "p95_duration_ms");
  const baselineDurationP95 = number(baseline, "p95_duration_ms");
  add("sample_count", sampleCount >= 30, sampleCount, ">=30");
  add("distinct_mr_count", distinctMrCount >= 30, distinctMrCount, ">=30");
  add("recall_uplift", recall !== null && baselineRecall !== null && recall - baselineRecall >= 0.10, recall !== null && baselineRecall !== null ? recall - baselineRecall : null, ">=0.10");
  add("cross_file_recall_uplift", crossRecall !== null && baselineCrossRecall !== null && crossRecall - baselineCrossRecall >= 0.15, crossRecall !== null && baselineCrossRecall !== null ? crossRecall - baselineCrossRecall : null, ">=0.15");
  add("critical_high_recall", criticalHighRecall !== null && criticalHighRecall >= 0.95, criticalHighRecall, ">=0.95");
  add("precision_regression", precision !== null && baselinePrecision !== null && precision - baselinePrecision >= -0.02, precision !== null && baselinePrecision !== null ? precision - baselinePrecision : null, ">=-0.02");
  add("negative_false_positive_count", negativeFp !== null && baselineNegativeFp !== null && negativeFp <= baselineNegativeFp, negativeFp, `<=${baselineNegativeFp}`);
  add("p95_tokens_ratio", tokenP95 !== null && baselineTokenP95 !== null && baselineTokenP95 > 0 && tokenP95 / baselineTokenP95 <= 1.5, tokenP95 !== null && baselineTokenP95 ? tokenP95 / baselineTokenP95 : null, "<=1.5");
  add("p95_duration_ratio", durationP95 !== null && baselineDurationP95 !== null && baselineDurationP95 > 0 && durationP95 / baselineDurationP95 <= 1.5, durationP95 !== null && baselineDurationP95 ? durationP95 / baselineDurationP95 : null, "<=1.5");
  return { version: QUALITY_GATE_VERSION, passed: checks.every((item) => item.passed), checks };
}
