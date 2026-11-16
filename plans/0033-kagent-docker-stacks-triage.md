# Plan 0033: kagent triage of homelab-docker-stacks and docker-images pull requests

- Status: Draft 2026-11-16 (nothing applied yet)
- Owner: Jayadeep KM
- Related: [ADR 0007](../adrs/0007-policy-gated-merges.md) (amended), [plan 0022](0022-kagent-scheduled-tasks.md), [plan 0023](0023-kagent-merge-policy.md)

## Goal and scope

Bring `kmjayadeep/homelab-docker-stacks` (Docker Compose stacks of the `jailmaker-docker` host) under the review and merge flow that already serves `homelab-k8s`:

- `homelab-gitops` reviews every open pull request there (Renovate, the operator's own, outside contributions) and leaves one verdict comment.
- The Telegram bot offers each reviewed pull request with Merge and Skip buttons, merges one at a time, and reports the deploy run of the merge commit.

`kmjayadeep/docker-images` (the homelab's own images) gets the same review and Merge/Skip buttons, added on the operator's request the same day. It needs none of the deploy handling: a merge there rebuilds images and deploys nothing.

Out of scope: automatic merges in that repository, the agent opening branches or pull requests there, and any rollback by the bot. A plan is needed because the change spans two repositories (this one and `docker-images` for the bot) and widens what the bot may merge.

## Starting state and prerequisites

- A merge to `main` of `homelab-docker-stacks` triggers its `Deploy Multiple Stacks` workflow, which runs `docker compose up -d --wait` for every changed stack. Pull requests have no checks.
- Its `main` ruleset requires pull requests, linear history and signed commits; only the repository admin bypasses it.
- The bot merged with a merge commit only, required at least one green check for automatic merges, could merge several pull requests in one pass and never looked at the result of a merge.
- Hand-run triage on 2026-11-16 (ten open pull requests, merged one by one): `redis` patch bump gave a red deploy because `tubearchivist` needs about 6.5 minutes to start against a healthcheck that allows about 6; the Immich 3.4.1 bump gave a real outage because the restart made Immich try `ALTER EXTENSION vector UPDATE` without superuser rights (Helios ships pgvector 0.8.2, the database was on 0.8.0), fixed by running the update as `postgres`; an outside pull request replaced `bitnami/minio` with an image from an unknown publisher.
- Operator actions: GitHub App installed on `homelab-docker-stacks` and given Actions read and write (done 2026-11-16). The App must also be installed on `docker-images`; unverified from this repository.
- Unverified: whether GitHub reports reviewed pull requests there as `clean` to the App (the bot skips anything else), and whether a squash merge by the App satisfies the signed-commits rule. PR #122 there was reported `blocked` to the operator on 2026-11-16 for a reason not yet found.

## Steps and gates

1. Agent and schedule (this repository): `agent-homelab-gitops.yaml` gets a "homelab-docker-stacks review" section and the `docker-stacks-review` skill; `scheduled-tasks.yaml` gets the prompt and the CronJob `kagent-docker-stacks-review` (every six hours at :45). Safe on its own: comments only. Gate: a run reviews the open pull requests and each gets exactly one marked comment.
2. Bot image (`docker-images` PR #25, image `20261116060144`): `SQUASH_MERGE_REPOS`, `DEPLOY_ON_MERGE_REPOS`, `DEPLOY_WATCH_TIMEOUT_SECONDS`; no automatic merge and no merge during a running workflow for deploy-on-merge repositories; deploy run of the merge commit followed and posted; pull requests from forks reported without a Merge button; repository name in the Telegram messages.
3. Bot Deployment (this repository): `GITHUB_REPOS` gains both repositories, plus the two new variables and the image tag from step 2 (with the old image a Merge press in `homelab-docker-stacks` fails on the linear-history rule). `docker-images` also gets its review section, prompt and CronJob `kagent-docker-images-review`.
4. Verify live: a reviewed Renovate pull request arrives with buttons; Merge squashes it, the message says the deploy started, and a success or failure message follows; a second Merge press during the deploy is refused.

## Validation and rollback

- `kustomize build clusters/titania/apps/kagent | kubectl apply --dry-run=client -f -`.
- Rollback: remove the repository from `GITHUB_REPOS` (merging stops) and delete the CronJob and prompt section (reviews stop), or revert the pull requests. State lives only in GitHub comments.
- Risks: a `merge` verdict there still restarts a service on the button press, and the review cannot see `.env` files or database state, which is exactly what broke Immich; the comment must be read, not only the verdict. A failed deploy is reported, not rolled back.

## Outcome

In progress. 2026-11-16: a one-off A2A request to the live `homelab-gitops` (review section passed in the request) reviewed the three open `homelab-docker-stacks` pull requests: #122 merge, #115 and #116 hold as a pair needing an Elasticsearch snapshot. The verdicts matched the hand triage; the #115 comment did not mention the breaking changes in the Tube Archivist 0.6.0 release notes. Steps 3 and 4 remain to be verified live.

Later on 2026-11-16: steps 3 and 4 verified. The bot offered five reviewed pull requests; Merge presses merged `docker-images` #16 and #18 and `homelab-docker-stacks` #115 (squash, accepted under the signed-commits rule), and a Merge press on #116 during the running deploy was not merged. Lesson from #115: it carried a `hold` verdict that named the pairing with #116 but not the removed `HOST_UID`/`HOST_GID` variables, and Tube Archivist 0.6.0 refused to start until they were removed by hand (docker-stacks #126, with Elasticsearch 9.5.5 after a snapshot). The review prompt now requires a "Breaking changes" part that quotes upstream and marks unreadable settings as hold, and the docker-stacks deploy script lets a stack settle before reporting failure (docker-stacks `fix/deploy-wait-for-settle`).
