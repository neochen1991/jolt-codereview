import assert from "node:assert/strict";
import { authenticatedRequest } from "./api-auth.mjs";

const projectId = process.env.JOLT_TEST_PROJECT_ID || "project_default";
const agentKey = process.env.JOLT_TEST_AGENT_KEY || "security_agent";
const suffix = `${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`;
const skillKey = `binding_editor_skill_${suffix}`;
const toolName = `binding-editor-tool-${suffix}`;

const document = await authenticatedRequest(`/api/projects/${projectId}/rule-documents`, {
  method: "POST",
  body: JSON.stringify({
    name: `Binding Editor Rule ${suffix}`,
    doc_type: "markdown",
    content: `# Binding Editor Rule ${suffix}\n\n用于验证专家绑定编辑。`,
    version: "v1",
    status: "active"
  })
});
assert.ok(document.id, "rule document should be created");

let ruleBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-rule-bindings`, {
  method: "POST",
  body: JSON.stringify({ agent_key: agentKey, rule_document_id: document.id, priority: 77 })
});
assert.ok((ruleBindings.items || []).some((item) => item.agent_key === agentKey && item.rule_document_id === document.id), "rule binding should be present");

const createdBinding = (ruleBindings.items || []).find((item) => item.agent_key === agentKey && item.rule_document_id === document.id);
assert.ok(createdBinding?.id, "created rule binding id should be returned");
await authenticatedRequest(`/api/projects/${projectId}/expert-rule-bindings/${encodeURIComponent(createdBinding.id)}`, { method: "DELETE" });
ruleBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-rule-bindings`);
assert.ok(!(ruleBindings || []).some((item) => item.agent_key === agentKey && item.rule_document_id === document.id), "rule binding should be deleted");

const skill = await authenticatedRequest(`/api/projects/${projectId}/custom-skills`, {
  method: "POST",
  body: JSON.stringify({
    skill_key: skillKey,
    name: `Binding Editor Skill ${suffix}`,
    description: "verify binding editor skill switch",
    content: "# Binding Editor Skill\n\nverify",
    version: "v1",
    status: "active"
  })
});
assert.equal(skill.skill_key, skillKey, "skill should be upserted");

const skillAsset = await authenticatedRequest(`/api/projects/${projectId}/custom-skill-assets`, {
  method: "POST",
  body: JSON.stringify({
    skill_key: skillKey,
    asset_path: "SKILL.md",
    asset_type: "skill",
    content: "# Binding Editor Skill\n\nverify",
    executable: false
  })
});
assert.equal(skillAsset.skill_key, skillKey, "skill asset should be created for uploaded skill content");
assert.equal(skillAsset.asset_path, "SKILL.md", "skill asset path should be preserved");

let skillBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-skill-bindings`, {
  method: "POST",
  body: JSON.stringify({ agent_key: agentKey, skill_key: skillKey, priority: 88, enabled: true })
});
assert.ok((skillBindings.items || []).some((item) => item.agent_key === agentKey && item.skill_key === skillKey && Number(item.enabled) === 1), "skill should be enabled");
skillBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-skill-bindings`, {
  method: "POST",
  body: JSON.stringify({ agent_key: agentKey, skill_key: skillKey, priority: 88, enabled: false })
});
assert.ok((skillBindings.items || []).some((item) => item.agent_key === agentKey && item.skill_key === skillKey && Number(item.enabled) === 0), "skill should be disabled");

let toolBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-tool-bindings`, {
  method: "POST",
  body: JSON.stringify({ agent_key: agentKey, tool_name: toolName, permission_level: "read_only", max_calls: 3, enabled: true })
});
assert.ok((toolBindings.items || []).some((item) => item.agent_key === agentKey && item.tool_name === toolName && Number(item.enabled) === 1), "tool should be enabled");
toolBindings = await authenticatedRequest(`/api/projects/${projectId}/expert-tool-bindings`, {
  method: "POST",
  body: JSON.stringify({ agent_key: agentKey, tool_name: toolName, permission_level: "read_only", max_calls: 3, enabled: false })
});
assert.ok((toolBindings.items || []).some((item) => item.agent_key === agentKey && item.tool_name === toolName && Number(item.enabled) === 0), "tool should be disabled");

console.log("Agent binding editor API checks passed.");
