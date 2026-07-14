# Skill Counterexamples And Cross-file Evidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve review precision by requiring Skill checkpoints to carry counterexample constraints and requiring cross-file findings to include an explicit evidence path.

**Architecture:** Skill checkpoint compilation becomes the source of truth for required evidence, false-positive patterns, negative examples and skip conditions. Review prompts expose that contract to the LLM, while the evidence pack and judge policy enforce that cross-file findings without a structured evidence path cannot be confirmed or published as high-confidence issues.

**Tech Stack:** TypeScript checkpoint compiler, Python worker prompt/evidence-pack tests, existing npm verification gates.

---

### Task 1: Require Skill counterexample constraints

**Files:**
- Modify: `mr-backend/src/backend/services/SkillCheckpointCompiler.ts`
- Modify: `scripts/verify-skill-checkpoint-compiler.mjs`

**Steps:**
1. Add a failing compiler verification case where a checkpoint has `false_positive_patterns` but no `negative_examples` / `skip_conditions`; expect `missing_checkpoint_field`.
2. Add `skip_conditions` as a compiled checkpoint field and parse aliases such as `skip_conditions`, `跳过条件`, `不适用条件`.
3. Update required fields to include `negative_examples` and `skip_conditions`.
4. Update positive fixture checkpoints and table headers to include both fields.

### Task 2: Inject counterexample contract into prompts

**Files:**
- Modify: `mr-backend/worker/prompts/builder.py`
- Add/modify worker prompt verification as needed.

**Steps:**
1. Require prompt task text to mention `negative_examples` and `skip_conditions`.
2. Tell the model to skip Skill findings that match false-positive patterns, negative examples or skip conditions unless new source evidence clearly defeats the counterexample.

### Task 3: Require cross-file evidence_path

**Files:**
- Modify: `mr-backend/worker/orchestration/judging/evidence_pack.py`
- Modify: `mr-backend/worker/orchestration/judging/evidence_score.py`
- Modify: `mr-backend/worker/tests/test_evidence_pack.py`

**Steps:**
1. Add a failing test: `evidence_scope="cross_file"` with no `evidence_path` should return `needs_review` with reason `cross_file_evidence_path_missing`.
2. Add a passing test: cross-file finding with a 2+ step `evidence_path` from changed symbol to caller/impact can be confirmed when the rest of the evidence is strong.
3. Include `evidence_path` in `EvidencePack` output and in evidence score components.
4. Ensure high-severity cross-file findings without evidence_path are not confirmed.

### Task 4: Verify

Run:

```bash
npm --prefix mr-backend run build
node scripts/verify-skill-checkpoint-compiler.mjs
PYTHONPATH=mr-backend/worker python3 mr-backend/worker/tests/test_evidence_pack.py
npm run verify:review-quality-v2
npm run build
```
