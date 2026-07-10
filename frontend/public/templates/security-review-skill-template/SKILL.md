---
name: security-review-skill-template
description: Review backend merge requests for authentication, sensitive data, and Redis cache safety risks.
---

# Security Review Skill Template

Use this Skill for backend Java or TypeScript service changes involving APIs, authorization, sensitive data, or cache writes.

The reviewer must inspect every checkpoint from `references/security-review-rules.md` independently. When a checkpoint is hit, the finding must use the checkpoint id exactly as defined in the reference document. Do not replace a Skill checkpoint id with a nearby platform rule, bound standard, expert persona rule, or free-form category.

Priority order for conflicting guidance:

1. Skill checkpoint
2. Bound project standard
3. Expert persona

If the source does not satisfy a checkpoint's required evidence, return no finding for that checkpoint. If the source matches a false positive pattern, return no finding for that checkpoint.
