# Real PR Review Quality Report

## Summary

| metric | value |
| --- | --- |
| precision | 1.0000 |
| recall | 1.0000 |
| high_severity_accuracy | 1.0000 |
| gold_count | 10 |
| finding_count | 10 |
| mr_count | 1 |
| negative_mr_count | 0 |
| negative_false_positive_count | 0 |

## Evidence Quality

| metric | value |
| --- | --- |
| evidence_score_min | 0.4400 |
| evidence_score_avg | 0.6440 |
| evidence_score_max | 0.7000 |
| evidence_score_below_0_35 | 0 |
| evidence_score_below_0_50 | 2 |
| missing_evidence_score_count | 0 |
| missing_consensus_agents_count | 0 |
| missing_critic_verdict_count | 0 |

## Action Items

| type | target | priority | message |
| --- | --- | --- | --- |
| weak_evidence | finding_13677286ee914cfa | 1 | finding has weak or incomplete quality evidence |
| weak_evidence | finding_b516460a479349de | 1 | finding has weak or incomplete quality evidence |

## Rule Gaps

No rule-level recall or precision gaps.

## MR Gaps

No MR-level recall or precision gaps.

## Weak Evidence Findings

| finding_id | mr_id | file | line | score | rules | missing_fields |
| --- | --- | --- | --- | --- | --- | --- |
| finding_13677286ee914cfa | mr_repo_github_java_complex_10file_9301 | pom.xml | 18 | 0.4400 | DEP-CVE-001 |  |
| finding_b516460a479349de | mr_repo_github_java_complex_10file_9301 | src/main/resources/application-prod.yml | 7 | 0.4751 | SEC-SECRET-004 |  |
