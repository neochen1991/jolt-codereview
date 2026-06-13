import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const source = readFileSync(path.join(root, "src/frontend/main.tsx"), "utf8");

assert.match(source, /const SOURCE_CONTEXT_RADIUS = 5;/, "finding detail should use five surrounding source lines");
assert.match(source, /startLine - SOURCE_CONTEXT_RADIUS/, "source window should include context before the finding line");
assert.match(source, /Math\.max\(endLine, startLine\) \+ SOURCE_CONTEXT_RADIUS/, "source window should include context after the finding line");
assert.match(source, /sourceCode\s*\?\s*sourceCodeWindow\(sourceCode/, "finding detail should prefer full source over patch snippets");
assert.match(source, /if \(source\) return sourceCodeWindow\(source/, "tool evidence should prefer full source over patch snippets");
assert.doesNotMatch(source, /startLine - 4/, "source window should not be limited to four previous lines");

console.log("Finding source context checks passed.");
