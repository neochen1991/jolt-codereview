import { execFileSync } from "node:child_process";

const steps = [
  ["node", ["scripts/run-python.mjs", "scripts/verify_quality_rule_registry.py"]],
  ["node", ["scripts/run-python.mjs", "scripts/verify_quality_symbol_context.py"]],
  ["node", ["scripts/run-python.mjs", "scripts/verify_quality_evidence_contract.py"]],
  ["node", ["scripts/evaluate-java-5mr-demo.mjs"]],
  ["node", ["scripts/evaluate-java-complex-mr.mjs"]],
];

const results = [];
for (const [command, args] of steps) {
  const label = [command, ...args].join(" ");
  const started = Date.now();
  execFileSync(command, args, { stdio: "inherit" });
  results.push({ command: label, duration_ms: Date.now() - started });
}

console.log(JSON.stringify({ ok: true, steps: results }, null, 2));
