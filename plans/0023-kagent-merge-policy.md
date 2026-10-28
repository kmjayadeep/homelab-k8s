# Plan 0023: Trusted auto-merge and Telegram merge approval

- Status: In progress 2026-10-28 (live test of the Telegram path pending)
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

- 2026-10-28, PR #486 merged: bot image `20261028135638` live with `merge policy=True`. The first pass found no open PR because the operator had merged #482, #483 and #484 by hand minutes earlier, so the automatic path is verified by the container test only until the next Renovate patch PR appears.
- Gap found while preparing the live test: docs-only PRs have no check runs (the validation workflow runs on `clusters/**` only), and the first image required green checks before offering an agent PR, so a PR like #484 would never have been asked. Image `20261028140315` offers `kagent/*` PRs whose checks are green or absent and keeps "at least one green check" mandatory for automatic merges. This PR, opened on a `kagent/` branch on purpose, is the live test of the Telegram offer and the Merge button.
