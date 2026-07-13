import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { evaluateReviewQualityUplift } from "./lib/review-quality-gate.mjs";

function option(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : "";
}

const fixturePath = option("--fixture");
let baseline;
let candidate;
if (fixturePath) {
  const fixture = JSON.parse(readFileSync(resolve(fixturePath), "utf8"));
  baseline = fixture.baseline;
  candidate = fixture.candidate;
} else {
  const baselinePath = option("--baseline");
  const candidatePath = option("--candidate");
  if (!baselinePath || !candidatePath) throw new Error("usage: --fixture report.json or --baseline v1.json --candidate v2.json");
  baseline = JSON.parse(readFileSync(resolve(baselinePath), "utf8"));
  candidate = JSON.parse(readFileSync(resolve(candidatePath), "utf8"));
}
const result = evaluateReviewQualityUplift(baseline, candidate);
console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
