# Plan 0022: Flux change verification and scheduled kagent tasks

- Status: Completed 2026-10-28
- Owner: Jayadeep KM
- Related: [plan 0020](0020-kagent-sre-agent.md), [plan 0021](0021-kagent-gitops-agent.md), [ADR 0002](../adrs/0002-autonomous-repository-agent.md)

## Goal and scope

Move four chores that dominate the operator's interactive agent sessions (mined from the Codex, pi and Claude Code transcripts on 2026-10-28) onto the agents that already run in the cluster, without a new ingress or a second notification path:

1. **Post-merge verification** ("merged, is reconcile done, all good?"): Flux notification-controller sends its events to the existing Alertmanager through the `alertmanager` Provider; a dedicated route delivers them to the Telegram bot's new `POST /flux` webhook, which asks `homelab-sre` for a short verdict on the changed namespace.
2. **Renovate pre-review**: every six hours `homelab-gitops` reviews open Renovate PRs that it has not commented on yet (changelog, chart values diff, risk) and leaves one marked comment with a merge/hold/needs-human verdict. It never merges.
3. **Daily summary** at 07:30 Europe/Zurich from `homelab-sre`, hard-capped at 600 characters.
4. **Daily repository review**: `homelab-gitops` opens at most one small `kagent/review-*` PR per day; if one is open, it does nothing.

Out of scope (operator decision 2026-10-28): GPU metrics export, homelab-iac templated changes, any write access for agents.

## Starting state and prerequisites

- Alertmanager routes `severity =~ "warning|critical"` to the bot's `/alertmanager` webhook; default routes fan out to email and the operator's other Telegram receiver. Flux events (severity `info`/`error`) would reach those default receivers unless matched first.
- Flux Alert `eventSources` accept `name: "*"` but not a namespace wildcard; Kustomizations live in 30 namespaces and HelmReleases in 15.
- kustomize-controller emits `ReconciliationSucceeded` ("Reconciliation finished in …") every interval; only `Progressing` (resources created/configured/deleted) and failure events signal a change.
- The bot's webhook has no authentication and is reachable only from Alertmanager pods (NetworkPolicy).
- GitHub MCP server runs with `--toolsets=repos,pull_requests`; PR conversation comments need `add_issue_comment` from the `issues` toolset. The GitHub App has Contents and Pull requests write; commenting on PRs through the issues API may additionally need Issues write (verify at first run).

## Steps and gates

1. Alertmanager config in Vault (`platform/monitoring/alertmanager`, edited file-to-file with `yq` in a container, validated with `amtool check-config` v0.34.1, written with `vault kv patch`): receiver `kagent-flux` (`webhook_configs` → `http://kagent-telegram-bot.kagent.svc.cluster.local:8080/flux`, `send_resolved: false`) and a first route `alertname =~ "^Flux.*"`, `continue: false`, `group_by: [namespace]`, `group_wait: 2m`, `repeat_interval: 12h`. Gate: `amtool config routes test alertname=FluxKustomizationProgressing` resolves to `kagent-flux` only.
2. Bot image: `POST /flux` (wait `FLUX_VERIFY_DELAY_SECONDS`, one verification per namespace per `FLUX_DEDUP_SECONDS`, ≤500-character verdict) and `POST /task` (`{agent, prompt, title}`, posts the answer to the alert chat). Gate: container smoke test of both endpoints.
3. Manifests (this PR): `infra/flux-notifications/` (Provider `alertmanager`, Alert `flux-changes` with every namespace listed and an `exclusionList` for periodic chatter) plus its bootstrap Kustomization; `apps/kagent/scheduled-tasks.yaml` (ConfigMap of prompts, three CronJobs with `timeZone: Europe/Zurich`, `concurrencyPolicy: Forbid`); bot NetworkPolicy admits the CronJob pods; GitHub MCP gains the `issues` toolset with `issue_write` and `sub_issue_write` excluded; `homelab-gitops` gets the Renovate review and scheduled review prompt sections and the comment tools; `homelab-sre` honours request-level format limits.
4. After merge: trigger each CronJob once by hand (`kubectl create job --from=cronjob/...`), confirm the Telegram posts and, for the Renovate review, the comment on an open Renovate PR; merge a trivial change and confirm one `🔁 Flux change in <ns>` verdict arrives about two minutes later and nothing reaches the other receivers.

## Validation and rollback

- `kustomize build` + client dry-run for `apps/kagent` and `infra/flux-notifications`; the validation workflow runs on the PR.
- Rollback: revert the PR (Flux prunes the Provider, Alert and CronJobs); remove the `kagent-flux` route and receiver from the Vault document the same file-to-file way. The bot image is backward compatible.
- Risks: a chatty Flux event not covered by the exclusion list produces one verification per namespace per 10 minutes at most (bot dedupe) and never reaches the operator's other receivers (route has `continue: false`). The Renovate comment is advice; merging stays manual. The daily review PR is capped at one open at a time by prompt and by the branch-prefix check.

## Outcome

2026-10-28, all four paths verified after PR #481 merged (bot image `20261028125041`):

- Alertmanager config version 3 in Vault; `amtool config routes test` sends `FluxKustomizationProgressing` to `kagent-flux` only and a warning alert still to `kagent-sre` and `homelab-telegram`. The ExternalSecret needed a `force-sync` annotation to pick the new document up before its refresh interval.
- Flux path: the real `Progressing` events of the merge itself were discarded ("no alerts found for the involved object") because the Alert was created in the same reconcile; a synthetic event POSTed to notification-controller from a pod in `flux-system` was dispatched, became `FluxKustomizationProgressing` in Alertmanager, reached the bot's `/flux` 2 minutes later (group wait) and produced a 475-character `OK` verdict from `homelab-sre` after the 120 s delay.
- Daily summary (manual job): 406 characters, five lines, verdict first.
- Renovate review: the first run reported "no tool to post PR comments" although the Agent spec listed `add_issue_comment`; the agent runtime loads its tool list from the MCP server at pod start, and `homelab-gitops` had started before the re-configured `github-mcp` pod was serving. After `rollout restart deploy/homelab-gitops` the second run commented on PR #482 (wallabag 2.6.15, verdict merge, with the CVE context and the custom-entrypoint check) and PR #483 (curl 8.23.0, verdict merge), both carrying the `<!-- kagent-renovate-review -->` marker.
- Repository review: PR #484 (`kagent/review-vault-tls-readme`) fixes the stale "Vault internal TLS is still follow-up work" sentence in the root README.

Lessons: restart agents after changing an MCPServer's toolsets; add new namespaces to Alert `flux-changes`; the Alert is not evaluated for events emitted while it is being created.

Follow-up 2026-10-28 (evening): the first day produced 60 Flux verifications instead of a handful. Two Flux Kustomizations (`flux-system` via the bootstrap file and `metallb` via the upstream MetalLB base) both applied `Namespace/metallb-system`, flipping the owner label and emitting a "configured" event every 15 minutes since April 2025; the 10-minute bot dedupe cannot catch a 15-minute cycle. Fixed in three steps because both Kustomizations apply the Namespace with the same field manager and the owner label flips, so dropping it from an inventory with `prune: true` could garbage-collect the live Namespace: (1) `prune: false` on the `metallb` Kustomization and the pod-security labels on the bootstrap Namespace, (2) `$patch: delete` the Namespace from the upstream base once the live spec shows `prune: false`, (3) `prune: true` again once the inventory no longer lists the Namespace. The merge burst "Dependencies do not meet ready condition, retrying in 30s" (12 Kustomizations at once) was added to the exclusion list. Watch the `homelab-sre` session count after a change: a noisy source shows up there first.
