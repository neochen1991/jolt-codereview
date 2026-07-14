import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const routesSource = readFileSync("mr-backend/src/backend/routes/rules.routes.ts", "utf8");
const repositorySource = readFileSync("mr-backend/src/backend/repositories/RuleDocumentRepository.ts", "utf8");

const { compileStoredSkillVersion } = await import("../mr-backend/build/backend/routes/rules.routes.js");
const { assertSkillVersionCompilationReady } = await import("../mr-backend/build/backend/services/SkillDebugSnapshotService.js");

const selected = {
  skill_key: "draft-review",
  name: "Draft Review",
  content: "legacy content",
  assets_json: JSON.stringify([
    {
      asset_path: "SKILL.md",
      asset_type: "skill",
      content: "---\nname: draft-review\ndescription: draft compiler\n---\n"
    },
    {
      asset_path: "references/rules.md",
      asset_type: "reference",
      content: "## OLD-001 Old checkpoint\n- check: old\n- required_evidence: old\n- false_positive_patterns: old\n- negative_examples: old\n- skip_conditions: old\n- fix_guidance: old\n"
    }
  ])
};

const validation = compileStoredSkillVersion(selected, {
  asset_path: "references/rules.md",
  asset_type: "reference",
  content: "## NEW-001 New checkpoint\n- check: new\n- required_evidence: new\n- false_positive_patterns: new\n- negative_examples: new\n- skip_conditions: new\n- fix_guidance: new\n"
});

assert.equal(validation.ok, true, JSON.stringify(validation.failures));
assert.deepEqual(validation.checkpoints.map((item) => item.checkpoint_id), ["NEW-001"]);
assert.equal(validation.normalized_assets.length, 2);

assert.doesNotThrow(() => assertSkillVersionCompilationReady({
  validation_json: JSON.stringify({ ok: true }),
  checkpoint_manifest_json: JSON.stringify({ ok: true, checkpoints: [{ checkpoint_id: "NEW-001" }] })
}));
assert.throws(() => assertSkillVersionCompilationReady({
  validation_json: JSON.stringify({ ok: false, failures: [{ message: "no checkpoints compiled" }] }),
  checkpoint_manifest_json: JSON.stringify({ ok: false, checkpoints: [] })
}), /latest checkpoint compilation failed/i);

for (const [source, snippet, label] of [
  [routesSource, "compileStoredSkillVersion(selected,", "versioned asset save recompiles the complete updated bundle"],
  [routesSource, "updateCustomSkillVersionCompilation", "save route persists the refreshed compilation"],
  [repositorySource, "transaction(() =>", "asset and compilation persistence is transactional"],
  [repositorySource, "content = CASE", "saving SKILL.md also refreshes the version content column"],
  [repositorySource, "checkpoint_manifest_json", "checkpoint manifest remains a persisted version field"],
  [repositorySource, "refreshCustomSkillVersionHash", "save-time compilation refreshes the canonical bundle hash"]
]) {
  assert.ok(source.includes(snippet), label);
}

console.log(JSON.stringify({ ok: true, verified: "skill_draft_save_compilation" }, null, 2));
