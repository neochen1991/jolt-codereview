# Reviewer Finding Compact Layout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Compress reviewer finding cards while preserving the original fields and giving long descriptions an explicit full-text expansion path.

**Architecture:** Keep `FindingRow` as the sole rendering component and add local expansion state plus overflow detection for its description. CSS keeps the existing card structure but reduces spacing, removes added labels, clamps collapsed text to three lines, and restores full flow when expanded.

**Tech Stack:** React, TypeScript, CSS, Node.js assertion scripts, Playwright CLI

---

### Task 1: Add the compact-card regression contract

**Files:**
- Modify: `scripts/verify-reviewer-detail-ui.mjs`

**Step 1: Write the failing test**

Assert that `FindingRow` contains expansion state, an `aria-expanded` button, a compact class, and CSS for a three-line collapsed description plus an expanded override.

**Step 2: Run test to verify it fails**

Run: `npm run verify:reviewer-detail-ui`

Expected: FAIL because the component does not yet expose compact or expandable description behavior.

### Task 2: Implement minimal compact rendering

**Files:**
- Modify: `frontend/src/frontend/components/ReviewViews.tsx`
- Modify: `frontend/src/frontend/styles.css`

**Step 1: Implement the component behavior**

- Add per-row expanded state.
- Restore the original short labels: confidence as the numeric value and `标误报`/`已误报`.
- Measure whether the three-line description actually overflows.
- Render `展开全文` only for overflow; render `收起` while expanded.

**Step 2: Implement compact styles**

- Reduce card padding, gaps, and minimum height.
- Keep metadata in one wrapping line.
- Clamp collapsed descriptions to three lines.
- Remove the clamp in expanded state.
- Keep path/title wrapping and responsive behavior.

**Step 3: Run focused tests**

Run: `npm run verify:reviewer-detail-ui && npm --prefix frontend run build`

Expected: PASS.

### Task 3: Verify permissions and real-browser layout

**Files:**
- Test only; no production file changes expected.

**Step 1: Run permission regression**

Run: `npm run verify:review-visibility-policy`

Expected: PASS.

**Step 2: Test the real reviewer page**

Open the 24-finding fixture as `ux-reviewer` at 1971×1280. Verify compact default card heights, visible original fields, an expansion button for long content, complete text after expansion, and zero diagnostic/coverage/quality UI elements.

**Step 3: Commit**

```bash
git add frontend/src/frontend/components/ReviewViews.tsx frontend/src/frontend/styles.css scripts/verify-reviewer-detail-ui.mjs docs/plans/2026-08-03-reviewer-finding-compact-layout.md
git commit -m "refine reviewer finding card density"
```
