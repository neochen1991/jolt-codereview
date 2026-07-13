import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { evaluateReviewQualityUplift } from "./lib/review-quality-gate.mjs";

const load = (name) => JSON.parse(readFileSync(resolve(import.meta.dirname, "fixtures", name), "utf8"));
const failed = load("review-quality-gate-fail.json");
const passed = load("review-quality-gate-pass.json");
const failResult = evaluateReviewQualityUplift(failed.baseline, failed.candidate);
const passResult = evaluateReviewQualityUplift(passed.baseline, passed.candidate);
if (failResult.passed) throw new Error("precision -5pp fixture must fail");
if (!failResult.checks.some((item) => item.metric === "precision_regression" && !item.passed)) throw new Error("precision failure reason missing");
if (!passResult.passed) throw new Error(`uplift fixture should pass: ${JSON.stringify(passResult.checks)}`);
console.log(JSON.stringify({ ok: true, verified: "review_quality_uplift_gate", checks: passResult.checks.length }));
