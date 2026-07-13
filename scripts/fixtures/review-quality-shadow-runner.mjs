let input = "";
for await (const chunk of process.stdin) input += chunk;
const snapshot = JSON.parse(input || "{}");
const v2 = snapshot.context_engine === "v2";
console.log(JSON.stringify({
  case_id: snapshot.case_id,
  expected_count: 2,
  true_positive_count: v2 ? 2 : 1,
  finding_count: 2,
  cross_file_expected_count: 1,
  cross_file_true_positive_count: v2 ? 1 : 0,
  critical_high_expected_count: 1,
  critical_high_true_positive_count: 1,
  negative_false_positive_count: 0,
  tokens: v2 ? 1200 : 1000,
  duration_ms: v2 ? 120 : 100,
  publish_attempt_count: 0
}));
