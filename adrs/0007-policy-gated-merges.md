# ADR 0007: Policy-gated automatic merges and Telegram approval for agent-reviewed pull requests

- Status: Accepted
- Date: 2026-10-28
- Related: [ADR 0002](0002-autonomous-repository-agent.md), [plan 0021](../plans/0021-kagent-gitops-agent.md), [plan 0022](../plans/0022-kagent-scheduled-tasks.md), [plan 0023](../plans/0023-kagent-merge-policy.md)

## Context

Since plan 0021 the agents open pull requests but never merge; since plan 0022 `homelab-gitops` reviews every Renovate PR and leaves a verdict comment. The operator still merges each PR by hand, and the transcript analysis of 2026-10-28 showed the triage-merge-wait loop to be the single most repeated chore. Letting the model merge is not acceptable: the reviewing agent reads untrusted upstream changelogs, so a prompt injection could turn into a merge, and a model that can merge during an alert investigation has no natural boundary.

## Decision

Merging is a deterministic function of the Telegram bot, never a model tool. The bot authenticates as the same GitHub App the MCP server uses (short-lived installation tokens, key from Vault `services/github/kagent-gitops` through External Secrets) and applies this policy to the repositories in `GITHUB_REPOS` (today `kmjayadeep/homelab-k8s` only):

- **Automatic merge** only when all of these hold: the PR author is Renovate; every update type in Renovate's body table is `patch`, `digest`, `pin` or `pinDigest`; no `critical-infra` label; every check run on the head commit is green; GitHub reports the PR as mergeable (`clean`); and a comment written by our own App carrying `<!-- kagent-renovate-review -->` says `Verdict: merge`. The bot merges with the merge commit method, pinned to the head SHA it evaluated, and announces it in Telegram.
- **Human in the loop for everything else**: reviewed Renovate PRs of any other kind (minor, major, blocked labels, hold or needs-human verdicts) and every `kagent/*` PR with green checks are posted once per head SHA to the operator chat with Merge and Skip buttons. The bot merges only on a button press from an allow-listed chat and only after re-reading the PR (same SHA, still mergeable, checks not pending). Decisions are recorded as PR comments with a marker and the SHA, so restarts never ask twice and a new push re-opens the question.
- The GitHub ruleset on `main` stays: pull requests only, no force pushes. The App has no bypass, so even the bot can merge only through a PR.
- Prompt-level rules remain the only guard on what the agents write; this ADR adds nothing to their capabilities. The merge tool stays excluded from the MCP server.

## Alternatives considered

- Renovate `automerge` or GitHub auto-merge: cannot take the agent's verdict into account, and GitHub auto-merge would need a required status check that no tool of ours can set.
- A GitHub Actions workflow reacting to the review comment: works for the automatic part but has no channel back to the operator for the human-gated part, and gives the workflow token merge rights on every event.
- Giving `homelab-gitops` the `merge_pull_request` tool behind a prompt rule: rejected for the injection reason above.

## Consequences

- Patch-level image and chart bumps land within one review cycle (at most six hours after Renovate opens them) without the operator.
- A wrong `merge` verdict on a patch bump merges a patch bump; the blast radius is the same as Renovate's own automerge, with the review comment as the audit trail and `git revert` as the rollback.
- Minor and major bumps, critical infrastructure and all agent-authored changes still wait for a human, now as a one-tap decision instead of a terminal session.
- Widening `AUTOMERGE_UPDATE_TYPES` (for example to `minor`) or adding `homelab-iac` to `GITHUB_REPOS` is a Git change to the bot Deployment and a conscious trust step; record it here when it happens.
