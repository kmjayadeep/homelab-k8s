# kagent

[kagent](https://kagent.dev/) runs Kubernetes-aware AI agents. Deployed per [plan 0019](../../../../plans/0019-kagent-deployment.md). UI: `https://kagent.cosmos.cboxlab.com` (LAN/VPN only, HTTP basic auth since 2026-10-28).

## Layout

- `../kagent-crds/`: CRD chart (`kagent-crds`), prune disabled together with the shared `HelmRepository`. The Namespace in `bootstrap/apps/kagent.yaml` is prune disabled too; removing kagent is a deliberate manual action.
- `helm-release.yaml`: chart values. All chart-default agents are disabled (`homelab-sre` replaces `k8s-agent`); the tool server has read-only cluster RBAC without Secrets; the controller is scoped to this namespace.
- `model-config.yaml`: one `ModelConfig` per LiteLLM router ([LiteLLM README](../litellm/README.md#routers)): `default-model-config` → `local-first` (local llama.cpp, DeepSeek when the single local slot is busy, the first streamed token takes over 120 s or the backend is down), `sensitive` → local only, `frontier` → DeepSeek only. Both agents use the default.
- `external-secret.yaml`: LiteLLM virtual key (alias `kagent`) from Vault `apps/litellm/kagent`.
- `postgres.yaml`: kagent's database is `kagent` on Helios PostgreSQL (`postgres.cosmos.cboxlab.com`, pgvector enabled). The ExternalSecret builds `DATABASE_URL` from the Vault password (`services/postgresql/kagent`) and the controller reads it from a mounted file; the bundled PostgreSQL is disabled. `ModelConfig` `embeddings` points at LiteLLM's `gemini-embedding-2` for agent memory.
- `grafana-mcp.yaml`: Grafana MCP server (`grafana/mcp-grafana`, read-only flags) with a Viewer service-account token from Vault `services/grafana/kagent`, plus its `RemoteMCPServer`. Gives agents Prometheus, Loki, alert-rule and dashboard tools ([plan 0020](../../../../plans/0020-kagent-sre-agent.md)).
- `agent-homelab-sre.yaml`: the read-only `homelab-sre` agent: cluster-specific prompt, Kubernetes read tools and the Grafana tools, A2A skills `investigate` and `health-report`.
- `scheduled-tasks.yaml`: ConfigMap of prompts and three CronJobs (`timeZone: Europe/Zurich`) that POST to the bot's `/task` endpoint: daily summary 07:30 (`homelab-sre`, 600 characters), daily repository review 07:00 (`homelab-gitops`, at most one open `kagent/review-*` PR), Renovate pre-review every six hours (`homelab-gitops`, one marked comment per PR). See [plan 0022](../../../../plans/0022-kagent-scheduled-tasks.md).
- `github-mcp.yaml` and `agent-homelab-gitops.yaml`: the GitHub MCP server (kmcp `MCPServer`, stdio, authenticated as a GitHub App whose id, installation id and private key come from Vault `services/github/kagent-gitops`; merge/delete/fork/review tools excluded at the server; NetworkPolicy limits callers to this namespace) and the `homelab-gitops` agent that opens pull requests. Since [plan 0024](../../../../plans/0024-kagent-gitops-coding-agent.md) it is a coding agent: the `gitops-coder` skill (`automation/kagent-skills/gitops-coder/`, loaded through `spec.skills.gitRefs` at pod start) gives it a local workspace copy of the repository, the built-in `bash`/`read_file`/`edit_file` tools of the full Go ADK image, and CI-equivalent `kustomize`/`kubeconform` validation; branches, pushes and PRs still go through the GitHub MCP tools, so the agent pod holds no credentials. Every PR it opens runs the repository's validation workflow; a human merges. A GitHub ruleset on `main` (pull requests only; bypass for repository admins and deploy keys) means the App cannot push to `main` even if asked. kmcp renders the Deployment without readiness or liveness probes (the CRD has no probe fields); a hung server shows up as agent tool timeouts, not restarts.

## Agents

| Agent | Purpose | Tools |
| --- | --- | --- |
| `homelab-sre` | Investigate and explain titania; concrete recommendations in either repository become pull requests via `homelab-gitops`; saves durable facts to memory | read-only `k8s_*`, Thanos PromQL, Grafana Loki/alerting/dashboards, `homelab-gitops` as a delegate |
| `homelab-gitops` | Turn a requested change into a pull request on `kmjayadeep/homelab-k8s` or `kmjayadeep/homelab-iac` (GitHub App installed on both; both `main` branches have a pull-requests-only ruleset) | `gitops-coder` skill: local workspace, `bash` (skill scripts, validators, find/grep), `read_file`/`edit_file`/`write_file`; GitHub MCP (`github-mcp.yaml`): create `kagent/*` branch, push files, open PR, comment; no merge, no delete; read-only `k8s_*` for live names ([plan 0021](../../../../plans/0021-kagent-gitops-agent.md), [plan 0024](../../../../plans/0024-kagent-gitops-coding-agent.md)) |

Ask `homelab-sre` through the UI or A2A. The canonical A2A endpoint is the controller Service, `http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/homelab-sre/`; the UI Ingress proxies the same path (`https://kagent.cosmos.cboxlab.com/api/a2a/kagent/homelab-sre/`, a JSON-RPC `message/send` through it was verified on 2026-10-26 in plan 0019).

## Telegram bot and alert triage

`telegram-bot.yaml` runs `ghcr.io/kmjayadeep/kagent-telegram-bot` (source in the `docker-images` repository). It long-polls Telegram and forwards messages from the operator chat to `homelab-sre` over A2A (one session per chat, `/new` resets), and serves `POST /alertmanager` for Alertmanager: every firing or resolved alert is posted to the chat, and a firing group triggers one agent investigation per hour whose result is posted too (repeat notifications whose alerts all started more than an hour ago are never investigated again, so a bot restart cannot re-trigger one). Token and chat id come from Vault `services/telegram/kagent-bot`; a NetworkPolicy admits only Alertmanager pods to the webhook. Alertmanager's receiver `kagent-sre` (`webhook_configs` → `http://kagent-telegram-bot.kagent.svc.cluster.local:8080/alertmanager`, `send_resolved: true`) and its `severity =~ "warning|critical"` route with `continue: true` live in the Vault-held Alertmanager config (`platform/monitoring/alertmanager`), not in Git; edit that document file-to-file and validate with `amtool check-config` before writing it back.

## Flux change verification and scheduled tasks

Flux notification-controller sends events to the existing Alertmanager through the `alertmanager` Provider in `clusters/titania/infra/flux-notifications/` (Alert `flux-changes`, `eventSeverity: error`: every namespace with Kustomizations or HelmReleases listed explicitly, dependency waits excluded). Only failures are sent; a healthy change is not an event for the agent, and a workload broken by a change surfaces through the Prometheus alerts instead. The Vault-held Alertmanager config routes `alertname =~ "^Flux.*"` first and only to receiver `kagent-flux` (`POST /flux` on the bot, `send_resolved: false`, grouped by namespace, 2m group wait), so Flux events never reach the e-mail or operator Telegram receivers. The bot waits `FLUX_VERIFY_DELAY_SECONDS` (120) so transient errors can heal, then asks `homelab-sre` to investigate the failing namespace (at most 600 characters, may hand a fix to `homelab-gitops`), once per `FLUX_DEDUP_SECONDS` (600). An answer starting with `OK` (healed) is logged, not posted. When a new app namespace is bootstrapped, add it to the Alert's `eventSources`.

Scheduled tasks are CronJobs in `scheduled-tasks.yaml` that POST a JSON body `{agent, prompt, title}` to the bot's `/task` endpoint; the bot calls that agent over A2A and posts the answer to the alert chat with the title. Run one by hand with `kubectl -n kagent create job --from=cronjob/kagent-daily-report manual-report`. The NetworkPolicy admits only Alertmanager pods and the CronJob pods (label `app.kubernetes.io/component: scheduled-task`) to the bot's port.

## Merge policy (ADR 0007)

The bot, not an agent, decides merges, authenticated as the same GitHub App. Renovate PRs whose body table lists only `patch`, `digest`, `pin` or `pinDigest` updates, with no `critical-infra` label, green check runs, a clean mergeable state and a `Verdict: merge` review comment from the App are merged automatically and announced in Telegram. Every other reviewed Renovate PR and every `kagent/*` PR with green checks is posted once per head SHA with Merge and Skip buttons; the bot re-reads the PR before merging on the button press. Decisions leave marker comments on the PR. `/prs` in the chat runs a pass immediately; otherwise a pass runs every 30 minutes and after each gitops scheduled task. Widening the policy means editing the `AUTOMERGE_*` or `GITHUB_REPOS` environment in `telegram-bot.yaml` and amending the ADR.

## UI credentials

The Ingress requires HTTP basic auth (`ui-basic-auth.yaml`). Username and password live in Vault at `apps/kagent/ui-basic-auth`; External Secrets renders the bcrypt htpasswd line into Secret `kagent-ui-basic-auth`. Read them (never paste the password into chat or commits):

```bash
cd ~/workspace/homelab/homelab-iac/vault-config
direnv exec . vault kv get -field=username -mount=homelab/kv apps/kagent/ui-basic-auth
direnv exec . vault kv get -field=password -mount=homelab/kv apps/kagent/ui-basic-auth
```

Rotate: `printf '%s\n' "<new password>" | direnv exec . ./import-kagent-ui-basic-auth.sh <username>` (or pipe from `pass`), then wait for the ExternalSecret refresh or force-sync it; ingress-nginx picks the Secret up without a restart. Browsers may need the credentials re-entered. A2A calls through the Ingress need `-u` as well; the Telegram bot and the agents use the controller Service in-cluster and are not affected.

- Risk removed: the UI is no longer open to anyone on the LAN/VPN.

## Rotate the GitHub App key

Generate a new private key on the App, run `../homelab-iac/vault-config/import-github-kagent-gitops-app.sh <app_id> <installation_id> < new.pem`, wait for the `ExternalSecret` refresh (or force-sync), then restart the kmcp-managed Deployment by hand, because Reloader cannot annotate it from Git: `kubectl -n kagent rollout restart deploy/github-mcp`. Delete the old key on the App afterwards.

## Rotate the Grafana token

Create a new token for the Grafana service account `kagent-mcp` (Viewer), import it with `../homelab-iac/vault-config/import-grafana-kagent-token.sh`, wait for the `ExternalSecret` refresh (or force-sync), and Reloader restarts `grafana-mcp`. Delete the old token in Grafana.

## Change the model

To change one agent's policy, set its `spec.modelConfig` (in `agent-*.yaml`) to `sensitive` or `frontier`; the default is `local-first`. To change what a router means for everyone, edit the LiteLLM HelmRelease (`local-first`/`sensitive` entries, `router_settings.fallbacks`, `frontier` alias), see [the LiteLLM README](../litellm/README.md#routers). Pinning a raw LiteLLM name such as `qwen-intel` or `deepseek-v4-pro` in a `ModelConfig` also works. Confirm with a chat in the UI and the LiteLLM spend log for the `kagent` key, which also shows whether a call was answered locally or by the fallback.

## Rotate the LiteLLM key

1. Create a new virtual key in the LiteLLM Admin UI and import it with `../homelab-iac/vault-config/import-litellm-kagent-key.sh` (stdin only).
2. Wait for the `ExternalSecret` to refresh (1h) or annotate it with `force-sync`.
3. Agent pods are created by the controller and are not watched by Reloader. Restart them with operator approval:

   ```bash
   kubectl -n kagent rollout restart deployment/k8s-agent
   ```

   The Deployment is named after the `Agent`; check with `kubectl -n kagent get deploy`.
4. Revoke the old key in LiteLLM.

## Risks

- Tool output is sent to the configured model provider. With `local-first` that is the local backend most of the time, but any call can fall back to DeepSeek (busy slot, late first token, backend down), so treat every tool result as leaving the cluster. Use the `sensitive` ModelConfig to keep an agent local.
- Sessions and memory live in the `kagent` database on Helios, which is in the hourly Restic backup set.

## Calling an agent from inside the cluster

The A2A endpoint in-cluster is `http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/<agent>/` (JSON-RPC 2.0, `message/send`, with the query as a text part in `params.message.parts`); it needs no basic auth, whereas the same path through the Ingress requires the UI credentials. Only the agent's final message is returned as the task artifact, and the earlier messages are available in the session history.
