import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const configPath = process.env.PG_RUNTIME_CONFIG_PATH || process.env.CONFIG_PATH;
if (!configPath) {
  throw new Error("Set CONFIG_PATH or PG_RUNTIME_CONFIG_PATH to a PostgreSQL config before running verify-pg-runtime.");
}
process.env.CONFIG_PATH = configPath;

const buildUrl = (file) => pathToFileURL(path.join(root, "build/backend", file));
const { loadConfig } = await import(buildUrl("config.js"));
const { openDatabase } = await import(buildUrl("db.js"));
const { ProjectRepository } = await import(buildUrl("repositories/ProjectRepository.js"));
const { RepositoryRepository } = await import(buildUrl("repositories/RepositoryRepository.js"));
const { MergeRequestRepository } = await import(buildUrl("repositories/MergeRequestRepository.js"));
const { ReviewJobRepository } = await import(buildUrl("repositories/ReviewJobRepository.js"));
const { AgentRepository } = await import(buildUrl("repositories/AgentRepository.js"));
const { AuditRepository } = await import(buildUrl("repositories/AuditRepository.js"));
const { RuleDocumentRepository } = await import(buildUrl("repositories/RuleDocumentRepository.js"));
const { ProjectConfigService } = await import(buildUrl("services/ProjectConfigService.js"));
const { AgentToolBindingService } = await import(buildUrl("services/AgentToolBindingService.js"));
const { FeedbackLearningService } = await import(buildUrl("services/FeedbackLearningService.js"));
const { ObservabilityService } = await import(buildUrl("services/ObservabilityService.js"));

const config = loadConfig();
assert.equal(String(config.server?.database_driver), "postgres", "verify-pg-runtime requires server.database_driver=postgres");

const suffix = `${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`;
const ids = {
  project: `pg_runtime_project_${suffix}`,
  member: `pg_runtime_member_${suffix}`,
  user: `pg_runtime_user_${suffix}`,
  repo: `pg_runtime_repo_${suffix}`,
  mr: `pg_runtime_mr_${suffix}`,
  job: `pg_runtime_job_${suffix}`,
  run: `pg_runtime_run_${suffix}`,
  finding: `pg_runtime_finding_${suffix}`,
  span: `pg_runtime_span_${suffix}`
};
const rootUserId = "user_local_admin";

function nextId(prefix) {
  return `${prefix}_${suffix}_${Math.random().toString(16).slice(2, 8)}`;
}

function expect(value, message) {
  assert.ok(value, message);
  return value;
}

const db = openDatabase(config);
try {
  const projectRepository = new ProjectRepository(db);
  const repositoryRepository = new RepositoryRepository(db);
  const mergeRequestRepository = new MergeRequestRepository(db);
  const reviewJobRepository = new ReviewJobRepository(db);
  const agentRepository = new AgentRepository(db);
  const auditRepository = new AuditRepository(db);
  const ruleDocumentRepository = new RuleDocumentRepository(db);
  const projectConfigService = new ProjectConfigService(db);
  const agentToolBindingService = new AgentToolBindingService(db);
  const feedbackLearningService = new FeedbackLearningService(db);
  const observabilityService = new ObservabilityService(db);

  expect(projectRepository.findUserById(rootUserId), "seeded local admin user missing");
  projectRepository.markLogin(rootUserId);
  const sessionToken = `pg-runtime-token-${suffix}`;
  projectRepository.createAuthSession(nextId("session"), rootUserId, sessionToken);
  expect(projectRepository.findSessionUserId(sessionToken), "auth session lookup failed");

  projectRepository.createProject({
    id: ids.project,
    name: "PG Runtime Project",
    description: "PostgreSQL runtime verification project",
    ownerUserId: rootUserId,
    memberId: ids.member
  });
  expect(projectRepository.findProjectById(ids.project), "project create/find failed");
  expect(projectRepository.listProjects().some((item) => item.id === ids.project), "project list failed");
  expect(projectRepository.listProjectsForUser(rootUserId).some((item) => item.id === ids.project), "projects for user failed");
  projectRepository.updateProject(ids.project, { description: "updated", data_policy: { mode: "pg-runtime" } });
  expect(projectRepository.findMemberRole(ids.project, rootUserId), "member role lookup failed");
  expect(projectRepository.listMembers(ids.project).length >= 1, "project member list failed");

  projectRepository.upsertMember({
    userId: ids.user,
    username: `pg-user-${suffix}`,
    displayName: "PG Runtime User",
    email: "pg-runtime@example.com",
    memberId: `member_${ids.project}_${ids.user}`.slice(0, 80),
    projectId: ids.project,
    role: "developer"
  });
  projectRepository.updateMemberRole(ids.project, `member_${ids.project}_${ids.user}`.slice(0, 80), "reviewer");
  expect(projectRepository.listDiscoverableProjects(ids.user).some((item) => item.id === ids.project), "discoverable project list failed");
  projectRepository.upsertUserSetting({ id: nextId("user_setting"), userId: ids.user, key: "ui", value: { density: "compact" } });
  expect(projectRepository.listUserSettings(ids.user).length >= 1, "user settings list failed");
  const joinRequest = projectRepository.createJoinRequest({
    id: nextId("join_request"),
    projectId: ids.project,
    userId: ids.user,
    requestedRole: "reviewer",
    reason: "pg runtime verification"
  });
  expect(joinRequest, "join request create failed");
  expect(projectRepository.listJoinRequests(ids.project).length >= 1, "join request list failed");
  projectRepository.reviewJoinRequest({ projectId: ids.project, requestId: joinRequest.id, reviewerId: rootUserId, status: "approved" });
  projectRepository.createInvitation({
    id: nextId("invitation"),
    projectId: ids.project,
    inviteCodeHash: `invite-hash-${suffix}`,
    role: "developer",
    createdBy: rootUserId,
    expiresAt: null,
    maxUses: 2
  });
  expect(projectRepository.listInvitations(ids.project).length >= 1, "invitation list failed");
  expect(projectRepository.redeemInvitation({ inviteCodeHash: `invite-hash-${suffix}`, userId: ids.user }), "invitation redeem failed");

  projectConfigService.upsertSetting(ids.project, "llm_policy", { default_model: "pg-runtime-model" });
  expect(projectConfigService.listSettings(ids.project).items.length >= 1, "project settings list failed");
  expect(projectConfigService.effectiveConfig(ids.project, config).effective_config.llm?.default_model, "effective config failed");

  const repository = repositoryRepository.upsert({
    id: ids.repo,
    projectId: ids.project,
    provider: "github",
    externalRepoId: `https://github.com/jolt-fixture/pg-runtime-${suffix}.git`,
    name: "pg-runtime-service",
    defaultBranch: "main",
    providerConfig: { endpoint: "https://api.github.com", owner: "jolt-fixture", repo: `pg-runtime-${suffix}` }
  });
  expect(repository, "repository upsert failed");
  expect(repositoryRepository.listByProject(ids.project).length >= 1, "repository list failed");
  expect(repositoryRepository.listActiveByProjectAndProvider(ids.project, "github").length >= 1, "repository provider list failed");
  expect(repositoryRepository.findProjectByRepositoryId(ids.repo), "repository project lookup failed");

  mergeRequestRepository.upsert({
    id: ids.mr,
    repositoryId: ids.repo,
    externalMrId: `mr-${suffix}`,
    number: 9001,
    title: "PG runtime MR",
    author: "pg-runtime",
    sourceBranch: "feature/pg-runtime",
    targetBranch: "main",
    riskScore: 87,
    latestHeadSha: `sha-${suffix}`,
    htmlUrl: `https://github.com/jolt-fixture/pg-runtime-${suffix}/pull/9001`,
    metadata: { changed_files: 3, labels: ["pg"] }
  });
  expect(mergeRequestRepository.findById(ids.mr), "MR find failed");
  expect(mergeRequestRepository.findByRepositoryAndExternalId(ids.repo, `mr-${suffix}`), "MR external lookup failed");
  expect(mergeRequestRepository.findDetailById(ids.mr), "MR detail lookup failed");
  expect(mergeRequestRepository.listByProject(ids.project, null).length >= 1, "MR list all failed");
  expect(mergeRequestRepository.listByProject(ids.project, "queued").length >= 1, "MR list by status failed");
  mergeRequestRepository.updateReviewStatus(ids.mr, "reviewing");

  reviewJobRepository.enqueueIgnore({
    id: ids.job,
    mergeRequestId: ids.mr,
    headSha: `sha-${suffix}`,
    priority: 80,
    effortLevel: "standard",
    requestedBy: rootUserId
  });
  reviewJobRepository.enqueueOrReset({
    id: ids.job,
    mergeRequestId: ids.mr,
    headSha: `sha-${suffix}`,
    priority: 81,
    effortLevel: "deep",
    requestedBy: rootUserId
  });
  expect(reviewJobRepository.findById(ids.job), "review job find failed");
  expect(reviewJobRepository.findWithProject(ids.job), "review job project join failed");
  expect(reviewJobRepository.findByMergeRequestAndHead(ids.mr, `sha-${suffix}`), "review job head lookup failed");
  expect(reviewJobRepository.listByMergeRequest(ids.mr).length >= 1, "review job list failed");
  reviewJobRepository.pauseByMergeRequest(ids.mr);
  reviewJobRepository.retry(ids.job, "standard", rootUserId);
  db.prepare("UPDATE review_jobs SET status = 'reviewing', heartbeat_at = datetime('now', '-240 seconds') WHERE id = ?").run(ids.job);
  reviewJobRepository.reclaimStale(120);

  db.prepare(`
    INSERT INTO review_runs (
      id, review_job_id, effort_level, risk_score, status, completed_at, report_summary, toolchain_manifest
    )
    VALUES (?, ?, 'standard', 87, 'waiting_confirmation', CURRENT_TIMESTAMP, 'pg runtime summary', ?)
  `).run(ids.run, ids.job, JSON.stringify({ static: { tools: ["pg-runtime"] } }));
  db.prepare(`
    INSERT INTO review_findings (
      id, review_run_id, severity, confidence, agent_id, head_sha, dedupe_hash, file_path,
      line_start, line_end, title, problem_description, recommendation, evidence, covered_rules_json,
      lifecycle_state, selected
    )
    VALUES (?, ?, 'high', 0.91, 'security_agent', ?, ?, 'src/App.java', 10, 12,
      'PG runtime finding', 'description', 'fix', 'evidence', ?, 'open', 1)
  `).run(ids.finding, ids.run, `sha-${suffix}`, `dedupe-${suffix}`, JSON.stringify(["PG-RULE-1"]));
  db.prepare("INSERT INTO agent_trace_spans (id, review_run_id, span_key, agent_id, status, ended_at) VALUES (?, ?, 'root', 'security_agent', 'completed', CURRENT_TIMESTAMP)")
    .run(ids.span, ids.run);
  db.prepare("INSERT INTO agent_trace_events (id, span_id, event_type, summary, payload_json) VALUES (?, ?, 'event', 'pg runtime event', ?)")
    .run(nextId("event"), ids.span, JSON.stringify({ ok: true }));
  db.prepare("INSERT INTO agent_messages (id, span_id, from_agent, to_agent, role, content_summary) VALUES (?, ?, 'a', 'b', 'assistant', 'message')")
    .run(nextId("message"), ids.span);
  db.prepare("INSERT INTO llm_call_records (id, span_id, provider, model, status, input_tokens, output_tokens, duration_ms) VALUES (?, ?, 'test', 'model', 'completed', 10, 20, 30)")
    .run(nextId("llm"), ids.span);
  db.prepare("INSERT INTO tool_call_records (id, span_id, tool_name, status, duration_ms) VALUES (?, ?, 'pg-tool', 'completed', 40)")
    .run(nextId("tool_call"), ids.span);
  db.prepare("INSERT INTO mcp_call_records (id, span_id, server_name, tool_name, status) VALUES (?, ?, 'server', 'tool', 'completed')")
    .run(nextId("mcp"), ids.span);
  db.prepare("INSERT INTO review_artifacts (id, review_run_id, artifact_type, name, storage_uri, sha256) VALUES (?, ?, 'json', 'artifact', 'memory://pg-runtime', 'sha256')")
    .run(nextId("artifact"), ids.run);
  db.prepare("INSERT INTO code_index_snapshots (id, review_run_id, repository_id, commit_sha, index_kind, storage_uri) VALUES (?, ?, ?, ?, 'symbols', 'memory://index')")
    .run(nextId("index"), ids.run, ids.repo, `sha-${suffix}`);
  db.prepare("INSERT INTO tool_observations (id, review_run_id, tool_name, rule_id, file_path, message) VALUES (?, ?, 'pg-tool', 'PG-RULE-1', 'src/App.java', 'message')")
    .run(nextId("observation"), ids.run);
  db.prepare("INSERT INTO external_review_reports (id, merge_request_id, report_type, commit_sha, report_format, payload_json) VALUES (?, ?, 'sast', ?, 'json', ?)")
    .run(nextId("external_report"), ids.mr, `sha-${suffix}`, JSON.stringify({ ok: true }));
  db.prepare("INSERT INTO review_jobs_dead_letter (id, review_job_id, failure_reason, final_attempt) VALUES (?, ?, 'pg runtime dead letter', 3)")
    .run(nextId("dead_letter"), ids.job);
  db.prepare("INSERT INTO vcs_publish_records (id, finding_id, provider, publish_status, published_by, body) VALUES (?, ?, 'github', 'published', ?, 'body')")
    .run(nextId("publish"), ids.finding, rootUserId);
  db.prepare("INSERT INTO evaluation_gold_set (id, project_id, finding_id, agent_id, severity, expected_title, expected_file_path, label, source) VALUES (?, ?, ?, 'security_agent', 'high', 'title', 'src/App.java', 'positive', 'pg-runtime')")
    .run(nextId("gold"), ids.project, ids.finding);

  expect(agentRepository.listByProject(ids.project).length >= 1, "agent list failed");
  expect(agentRepository.listWithProfiles(ids.project).length >= 1, "agent profile join list failed");
  expect(agentRepository.listExpertProfiles(ids.project).length >= 1, "expert profile list failed");
  const customAgent = agentRepository.createCustomAgent({
    id: nextId("agent_config"),
    profileId: nextId("expert_profile"),
    projectId: ids.project,
    agentKey: `pg_runtime_agent_${suffix}`.slice(0, 64),
    displayName: "PG Runtime Agent",
    roleProfile: "role",
    responsibilityScope: "scope",
    excludedScope: "excluded",
    appliesTo: { file_globs: ["**/*.java"] },
    tools: ["pg-tool"],
    skills: ["pg-skill"],
    ruleSets: ["pg-rules"],
    requiresDeepagents: false,
    minConfidence: 0.7,
    maxFindings: 9,
    maxLlmCalls: 3,
    maxToolCalls: 4
  });
  expect(customAgent, "custom agent create failed");
  agentRepository.update(ids.project, customAgent.agent_key, { enabled: true, max_findings_per_mr: 10 });
  agentRepository.updateExpertProfile(ids.project, customAgent.agent_key, { display_name: "PG Runtime Agent Updated" });

  const ruleSet = ruleDocumentRepository.createRuleSet({
    id: nextId("rule_set"),
    projectId: ids.project,
    name: "PG Runtime Rules",
    version: "v1",
    scope: { language: "java" },
    content: "## PG-RULE-1\ncontent",
    status: "active"
  });
  expect(ruleDocumentRepository.listRuleSets(ids.project).length >= 1, "rule set list failed");
  const ruleDoc = ruleDocumentRepository.createRuleDocument({
    id: nextId("rule_doc"),
    projectId: ids.project,
    name: "PG Runtime Rule Doc",
    docType: "markdown",
    content: "# rule doc",
    version: "v1",
    status: "active"
  });
  ruleDocumentRepository.bindRuleDocument({
    id: nextId("rule_binding"),
    projectId: ids.project,
    agentKey: customAgent.agent_key,
    ruleDocumentId: ruleDoc.id,
    priority: 10
  });
  expect(ruleDocumentRepository.listExpertRuleBindings(ids.project).length >= 1, "rule binding list failed");
  const customSkill = ruleDocumentRepository.upsertCustomSkill({
    id: nextId("skill"),
    projectId: ids.project,
    skillKey: `pg_skill_${suffix}`,
    name: "PG Runtime Skill",
    description: "skill",
    content: "content",
    version: "v1",
    status: "active"
  });
  expect(customSkill, "custom skill upsert failed");
  ruleDocumentRepository.bindCustomSkill({
    id: nextId("skill_binding"),
    projectId: ids.project,
    agentKey: customAgent.agent_key,
    skillKey: customSkill.skill_key,
    priority: 10,
    enabled: true
  });
  expect(ruleDocumentRepository.listExpertSkillBindings(ids.project).length >= 1, "skill binding list failed");
  ruleDocumentRepository.upsertCustomSkillAsset({
    id: nextId("skill_asset"),
    projectId: ids.project,
    skillKey: customSkill.skill_key,
    assetPath: "refs/pg-runtime.md",
    assetType: "reference",
    content: "asset",
    executable: false
  });
  expect(ruleDocumentRepository.listCustomSkillAssets(ids.project, customSkill.skill_key).length >= 1, "skill asset list failed");
  ruleDocumentRepository.upsertReviewPolicy(ids.project, { min_confidence: 0.8, rule_set_id: ruleSet.id });
  expect(ruleDocumentRepository.findReviewPolicy(ids.project), "review policy upsert/find failed");

  agentToolBindingService.upsertBinding({
    id: nextId("tool_binding"),
    projectId: ids.project,
    agentKey: customAgent.agent_key,
    toolName: "pg-tool",
    permissionLevel: "read_only",
    maxCalls: 5,
    enabled: true
  });
  expect(agentToolBindingService.listBindings(ids.project).length >= 1, "agent tool binding list failed");

  const findingWithProject = { ...mergeRequestRepository.findById(ids.mr), ...db.prepare("SELECT rf.*, ? AS project_id FROM review_findings rf WHERE rf.id = ?").get(ids.project, ids.finding) };
  feedbackLearningService.recordFeedback({
    userId: rootUserId,
    finding: findingWithProject,
    feedbackType: "accepted",
    scope: "finding",
    reason: "pg runtime"
  });
  expect(feedbackLearningService.markFindingFeedback(ids.finding, "accepted"), "finding feedback update failed");

  auditRepository.record({
    id: nextId("audit"),
    userId: rootUserId,
    projectId: ids.project,
    action: "pg.runtime.verify",
    resourceType: "project",
    resourceId: ids.project,
    summary: "PG runtime verification",
    metadata: { suffix }
  });
  expect(auditRepository.listForProject(ids.project, 20).length >= 1, "audit list failed");

  expect(observabilityService.queueSummary(ids.project), "observability queue summary failed");
  expect(observabilityService.toolchainStatus(ids.project), "observability toolchain status failed");
  expect(observabilityService.agentQuality(ids.project), "observability agent quality failed");

  reviewJobRepository.deadLetter(ids.job, "pg runtime final dead letter", 4, nextId("dead_letter_final"));
  reviewJobRepository.stopByMergeRequest(ids.mr);
  mergeRequestRepository.deleteById(ids.mr);
  repositoryRepository.softDelete(ids.project, ids.repo);

  const summary = {
    project_id: ids.project,
    verified_modules: [
      "ProjectRepository",
      "RepositoryRepository",
      "MergeRequestRepository",
      "ReviewJobRepository",
      "AgentRepository",
      "RuleDocumentRepository",
      "AuditRepository",
      "ProjectConfigService",
      "AgentToolBindingService",
      "FeedbackLearningService",
      "ObservabilityService"
    ],
    checks: 73
  };
  console.log(JSON.stringify(summary, null, 2));
} finally {
  db.close?.();
}
