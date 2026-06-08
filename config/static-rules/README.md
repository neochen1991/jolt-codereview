# Static Rule Bundles

This directory stores open-source static-analysis rules bundled with Jolt CodeReview.

Run:

```bash
npm run sync:static-rules
```

The sync script downloads rule bundles from official upstream repositories into this directory:

- `semgrep/java`, `semgrep/generic`, `semgrep/yaml`, `semgrep/secrets`: Semgrep community rules.
- `pmd/category/java`: PMD Java category rules.
- `checkstyle/google_checks.xml` and `checkstyle/sun_checks.xml`: Checkstyle built-in style rules.
- `gitleaks/gitleaks.toml`: Gitleaks default open-source config for inspection.
- `kics/queries`: KICS IaC query rules.

The worker loads these rules by default where the underlying tool supports local rule paths. Project admins can append custom rules with `tool_policy.static_runners`.
