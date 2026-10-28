# Plan 0023: Trusted auto-merge and Telegram merge approval

- Status: In progress 2026-10-28
- Owner: Jayadeep KM
- Related: [ADR 0007](../adrs/0007-policy-gated-merges.md), [plan 0022](0022-kagent-scheduled-tasks.md)

## Goal and scope

Close the loop after the Renovate pre-review from plan 0022: the bot merges Renovate patch, digest and pin updates that have a `merge` verdict and green checks, and offers every other reviewed Renovate PR and every `kagent/*` PR to the operator in Telegram with Merge and Skip buttons. Decision logic lives in the bot (deterministic Python), not in an agent; see ADR 0007 for the reasoning. Scope is `kmjayadeep/homelab-k8s`; homelab-iac stays manual (operator decision 2026-10-28).

## Starting state and prerequisites

- Renovate PR bodies carry a table with an `Update` column (`patch`, `minor`, `digest`, …); the bot parses it instead of relying on labels.
- The GitHub App (`services/github/kagent-gitops`, Secret `kagent-github` in `kagent`) has Contents and Pull requests write, which is enough to merge and to comment; it has no ruleset bypass.
- The bot already polls Telegram and holds the alert chat id; Telegram inline keyboards and `callback_query` updates are available to it.
- `homelab-gitops` posts the verdict comment with the marker `<!-- kagent-renovate-review -->` (plan 0022).

## Steps and gates

1. Bot image: GitHub App client (PyJWT, installation tokens cached until five minutes before expiry), `parse_renovate_update_types`, a policy pass every `MERGE_POLICY_INTERVAL_SECONDS` (30 min), after every gitops `/task` and on `/prs`; inline buttons and `callback_query` handling; decision markers as PR comments. Gate: container test of the table parser and JWT minting with a throwaway key; deployment only after the image exists.
2. Manifests (this PR): bot Deployment gets `envFrom` the `kagent-github` Secret plus `GITHUB_REPOS`, `AUTOMERGE_UPDATE_TYPES`, `AUTOMERGE_BLOCK_LABELS`; README, ADR 0007 and indexes.
3. After merge: with PRs #482 (wallabag, patch, verdict merge) and #483 (curl, minor, verdict merge) open, expect #482 to auto-merge on the first pass and #483 plus the agent PR #484 to arrive in Telegram with buttons. Press Skip on one and confirm the marker comment and that it is not asked again; press Merge on another and confirm the merge and the message edit.

## Validation and rollback

- `kustomize build clusters/titania/apps/kagent | kubectl apply --dry-run=client -f -`; validation workflow on the PR.
- Rollback: remove the `GITHUB_*` environment from the bot Deployment (policy disables itself when the credentials are absent) or revert the PR. No state outside GitHub comments.
- Risks: the merge happens on the SHA the bot evaluated, so a push between evaluation and merge fails safely; a `merge` verdict produced from a malicious changelog can only merge the patch bump it reviewed; Telegram callbacks are accepted only from allow-listed chats.

## Outcome

Pending.
