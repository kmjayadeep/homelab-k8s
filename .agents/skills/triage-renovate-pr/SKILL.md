---
name: triage-renovate-pr
description: Triage and merge Renovate pull requests in a repository safely and sequentially. Use when Codex needs to process PRs opened by renovate[bot], review each dependency update, confirm CI and post-merge default-branch pipeline health, merge only safe PRs one by one, and produce a completion report with merged, skipped, and failed items.
---

# Triage Renovate PR

## Overview

Process Renovate PRs serially to minimize blast radius: review one PR, merge if safe, wait for the default branch pipeline to be green, then continue.

## Preconditions

- Confirm `gh` CLI is installed and authenticated for this repository.
- Confirm merge permissions and visibility of Actions/CI status checks.
- Use the repository default branch as the pipeline gate branch.

## Workflow

1. Identify open Renovate PRs.
2. Sort by risk, then by dependency scope.
3. Triage and decide merge/skip for the next PR only.
4. Merge PR when safe and checks are green.
5. Wait for default branch pipeline to complete green.
6. Continue with the next PR.
7. Publish a final report.

## Commands

Use `gh` for all state reads and mutations.

```bash
# List open Renovate PRs (JSON for deterministic processing)
gh pr list \
  --state open \
  --search "author:app/renovate" \
  --json number,title,url,headRefName,baseRefName,isDraft,mergeStateStatus,statusCheckRollup
```

```bash
# Inspect a PR in detail
gh pr view <pr_number> \
  --json number,title,url,files,commits,reviews,reviewDecision,mergeStateStatus,statusCheckRollup
```

```bash
# Merge with squash after checks are green
gh pr merge <pr_number> --squash --delete-branch
```

```bash
# Watch default branch workflow health (adjust workflow if needed)
gh run list --branch <default_branch> --limit 1
gh run watch <run_id>
```

```bash
# Verify merged commit SHA and map to the matching default-branch run
gh pr view <pr_number> --json mergeCommit,mergedAt
gh run list --branch <default_branch> --limit 10 --json databaseId,headSha,status,conclusion,createdAt,url
```

```bash
# Optional: retry helper for transient GitHub API/network errors
for i in 1 2 3; do gh <command> && break || sleep $((i * 2)); done
```

## Risk Ordering Guidance

Prefer this order when multiple Renovate PRs are open:

1. Container image tag bumps (single-service tag updates).
2. Terraform provider/module patch or minor updates with clear lockfile diffs.
3. CI/action updates, especially majors, after reviewing diff scope.

## Merge Decision Rules

Merge only when all are true:

- PR author is Renovate app/bot.
- PR is not draft and has no unresolved review blockers.
- Required PR checks are green.
- Change scope is low-to-moderate risk (for example: patch/minor dependency bumps, no broad refactors).
- No Terraform/Ansible/Nix behavior change is implied beyond dependency update expectations.

Skip and report when any are true:

- Major version bump with unclear migration impact.
- Failing or flaky checks.
- Large dependency fan-out or lockfile churn that obscures review.
- Security or runtime implications requiring human approval.

Major bump exception:

- A major bump may still be merged when the diff is trivially scoped (for example, a one-line GitHub Action version bump), checks are green, and the merge rationale is explicitly documented in the report.

## Sequential Safety Gate

After each merge:

1. Read the PR `mergeCommit.oid`.
2. Find the newest default-branch run whose `headSha` matches that merge commit (or wait briefly until it appears).
3. Wait until completion with `gh run watch <run_id>`.
4. Continue only if conclusion is `success`.
5. Stop loop on `failure` or `cancelled` and mark remaining PRs as blocked.

If GitHub API calls fail transiently (for example, `error connecting to api.github.com`), retry with short exponential backoff before treating the step as failed.

## Reporting Format

Return a concise report with these sections:

- `summary`: total PRs, merged, skipped, blocked.
- `merged`: PR number, title, reason it was considered safe.
- `skipped`: PR number, title, explicit risk reason.
- `blocked`: PRs not processed because default-branch pipeline failed.
- `notes`: follow-up actions (for example, manual review needed for majors).

## Execution Notes

- Prefer smallest-risk PRs first to keep throughput high.
- Keep decisions explicit and auditable in the report.
- Do not batch-merge Renovate PRs in this workflow.
