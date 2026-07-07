---
name: refund-risk-review-skill
description: Review Java Spring refund approval changes for business consistency, audit integrity, and refund cache TTL risks.
---

# Refund Risk Review Skill

Use this Skill only for Java Spring refund, compensation, approval, and refund cache changes.

The reviewer must inspect each checkpoint from `references/refund-review-rules.md` independently. When a checkpoint is hit, the finding must use the checkpoint id exactly as defined in the reference document. Do not replace a Skill checkpoint id with a nearby platform rule, expert-profile rule, or free-form category.

Priority order for conflicting guidance is:

1. Skill checkpoint
2. Bound project standard
3. Expert persona

If the source does not satisfy a checkpoint's required evidence, return no finding for that checkpoint. If the source matches a checkpoint's false positive pattern, return no finding for that checkpoint.
