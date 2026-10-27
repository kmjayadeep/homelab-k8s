# Plan 0020: Homelab SRE agent on kagent

- Status: Active (phases 1–2 in progress 2026-10-26)
- Owner: Jayadeep KM
- Related: [plan 0019](0019-kagent-deployment.md) (kagent deployment), [ADR 0001](../adrs/0001-vault-external-secrets.md)

## Goal and scope

Turn the kagent installation from plan 0019 into a useful, read-only SRE assistant for titania, then add the layers that make it proactive:

1. **Observability tools.** A Grafana MCP server in the `kagent` namespace with a Viewer service-account token, exposing Prometheus, Loki, dashboard and alert-rule tools to agents. A Loki datasource is provisioned in Grafana for it.
2. **The `homelab-sre` agent.** A Git-managed `Agent` with a cluster-specific prompt, the read-only Kubernetes tools and the Grafana tools, and an A2A skill card.
3. **Durable storage and memory.** Move kagent's database to Helios PostgreSQL (`kagent` database with pgvector) and enable long-term memory once an embedding model is available through LiteLLM.
4. **Alert-driven triage.** Alertmanager fires a webhook, an adapter sends the alert to the agent over A2A and posts the diagnosis to a chat channel.
5. **Scoped write access** for a separate agent, if wanted, through per-agent ServiceAccounts and the tool server's token passthrough.

Deliberately **not** done:

- `kagent-tools.rbac.allowSecrets: true` and the bundled Helm agent. Reading Secrets cluster-wide would let the model forward secret values to the provider. Helm release state is read from the Flux `HelmRelease` objects instead.
- The bundled `promql-agent`, `observability-agent` and `grafana-mcp` subcharts. The subchart takes the Grafana token as a plain Helm value, which would put a secret in Git; the standalone Deployment below takes it from an ExternalSecret.
- Agent Substrate / AgentHarness (see plan 0019 outcome).

## Starting state and prerequisites

Verified 2026-10-26:

- kagent `0.10.4` is running per plan 0019 with `k8s-agent` and the operator-created `my-first-k8s-agent`; the ModelConfig uses LiteLLM `deepseek-v4-flash`.
- Grafana datasources were "Prometheus" (default, Thanos query) and "Alertmanager" only; Loki runs in `monitoring` with `auth_enabled: false` behind Service `loki-gateway:80`.
- `grafana/mcp-grafana` publishes versioned multi-arch images on Docker Hub (`2.1.1`, 2026-10-20); the streamable-HTTP transport serves `/mcp` on port 8000. 2.1.1 rejects requests whose `Host` header is not in `--allowed-hosts` (default: loopback), logs a security error when bound to a non-loopback address without a caller token, and supports `--healthz-address` for a side listener that skips Host validation and `--enabled-tools` to pick categories. Grafana datasource UIDs on titania are `prometheus` and `alertmanager`; `loki` is added by this plan.
- Agent memory requires `memory.modelConfig` pointing at a `ModelConfig` whose provider supports **embeddings**. LiteLLM currently has no embedding model (DeepSeek and the local llama.cpp chat models do not embed).
- Helios PostgreSQL (`postgres.cosmos.cboxlab.com:5432`, PostgreSQL 16) hosts other app databases and already has the `vector` extension (Immich, BookOrbit). Onboarding is through the catalog in `../homelab-iac/nixos-images/postgres/modules/postgres-catalog.nix` followed by a Helios rebuild.
- Vault: the `kagent` ESO role now reads `apps/litellm/kagent`, `services/grafana/kagent` and `services/postgresql/kagent` (homelab-iac commit `b2bd85b`, applied). `services/grafana/kagent` holds the token of the Grafana service account `kagent-mcp` (Viewer), created on 2026-10-26 from a temporary in-cluster pod and piped straight into Vault. `services/postgresql/kagent` is empty until the database exists.
- Reloader is scoped by namespace list; `kagent` was not in it.

Approvals: Terraform apply and the Grafana service account were covered by the operator's "build it all" on 2026-10-26. The Helios rebuild (phase 3) and the choice of chat channel (phase 4) still need the operator. Any write access (phase 5) needs explicit approval per agent.

## Steps and gates

### Phase 1: Grafana MCP and Loki datasource (this repo, PR)

- `clusters/titania/apps/kagent/grafana-mcp.yaml`: `ExternalSecret` `kagent-grafana` (key `GRAFANA_SERVICE_ACCOUNT_TOKEN` from `services/grafana/kagent`/`token`), `Deployment` `grafana-mcp` (`docker.io/grafana/mcp-grafana:2.1.1`, `--transport=streamable-http`, `--allowed-hosts` set to the Service names because 2.1.1 validates the Host header, `--healthz-address=:8080` for probes, `--enabled-tools=datasource,prometheus,loki,alerting,dashboard,search`, `--disable-write`; non-root, read-only root filesystem, 50m/64Mi–500m/256Mi; a NetworkPolicy limits callers to pods in `kagent`), `Service` `grafana-mcp:8000`, `RemoteMCPServer` `grafana-mcp` → `http://grafana-mcp.kagent.svc.cluster.local:8000/mcp`.
- `clusters/titania/infra/monitoring/helmrelease-prometheus.yaml`: `grafana.additionalDataSources` with `Loki` → `http://loki-gateway.monitoring.svc.cluster.local`.
- `clusters/titania/infra/reloader/helm-release.yaml`: add `kagent` so the Deployment restarts on token rotation.

Gate: `grafana-mcp` pod Ready; `RemoteMCPServer` Accepted with discovered tools; Grafana shows the Loki datasource; a Loki query from Grafana Explore returns lines.

### Phase 2: `homelab-sre` agent (same PR)

- `clusters/titania/apps/kagent/agent-homelab-sre.yaml`: `Agent` with `stream: true`, resources, tools limited to the read-only Kubernetes set (`k8s_get_resources`, `k8s_get_resource_yaml`, `k8s_describe_resource`, `k8s_get_pod_logs`, `k8s_get_events`, `k8s_check_service_connectivity`, `k8s_get_available_api_resources`, `datetime_get_current_time`) plus the 20 Grafana read tools registered by 2.1.1 for Prometheus, Loki, alerting and dashboards (names verified with `tools/list` against the image); A2A skills `investigate` and `health-report`; a prompt describing the cluster (nodes, Flux ownership, Cilium/MetalLB/ingress, Longhorn, Vault/ESO, the LLM stack, observability, known pitfalls) and a fixed investigation method ending in a Git change recommendation.

Gate: `Agent` Accepted and Ready; in the UI, "Is anything in the cluster not Ready right now?" produces a Flux-first answer with evidence; "show error logs from litellm in the last hour" uses `query_loki_logs`; an A2A `message/send` completes. Record the model used.

### Phase 3: Helios PostgreSQL and memory (operator gate, then PR)

1. Operator: rebuild Helios so the `kagent` database and owner exist (`make rebuild` in `nixos-images/postgres/`), set the owner password, and import it with `../homelab-iac/vault-config/import-kagent-postgres-password.sh` (stdin only).
2. PR: `ExternalSecret` `kagent-postgres` with a `target.template` that builds `DATABASE_URL` from the password and the non-secret parts (`postgres://kagent:<password>@postgres.cosmos.cboxlab.com:5432/kagent`), mounted into the controller via `controller.volumes`/`volumeMounts`; HelmRelease values `database.postgres.urlFile`, `vectorEnabled: true`, `bundled.enabled: false`. Remove the Postgres `NetworkPolicy` and note that sessions in the bundled database are discarded.
3. Memory needs an embedding `ModelConfig`. Options, operator decision: (a) a small CPU llama-server in `llm-serving` serving an embedding GGUF (for example nomic-embed-text) behind a LiteLLM `embedding` entry, fully local; (b) a cloud embedding model through a LiteLLM database credential. Then `ModelConfig` `embeddings` and `memory.modelConfig` on `homelab-sre`.

Gate: controller Ready against Helios; the UI Memory page no longer returns 500; a memory survives a controller restart.

### Phase 4: Telegram chat and alert-driven triage (PR in progress 2026-10-26)

Channel decision: **Telegram** (operator, 2026-10-26). Token at Vault `services/telegram/kagent-bot` (`token`) with the operator chat id as `chat_id` on the same path; both granted to the `kagent` role (homelab-iac `f61480d`, `cd8d0d0`).

- Service `kagent-telegram-bot` (source `docker-images/kagent-telegram-bot`, image `ghcr.io/kmjayadeep/kagent-telegram-bot:<timestamp>`, aiohttp only, non-root): Telegram long polling for the allow-listed chat with one A2A session per chat and `/new`; `POST /alertmanager` posts every firing/resolved alert to the chat and runs one `homelab-sre` investigation per Alertmanager group key per hour (`ALERT_DEDUP_SECONDS`), at most two concurrently, result posted to the chat. Unauthorized chats get only their chat id back.
- Manifests in `clusters/titania/apps/kagent/telegram-bot.yaml`: ExternalSecret (token, chat id), Deployment (Recreate strategy so two pollers never overlap, Reloader annotation, probes on `/healthz`, 20m/64Mi–500m/256Mi), Service `kagent-telegram-bot:8080`, NetworkPolicy admitting only Alertmanager pods from `monitoring`.
- Operator step: add to the Vault-held Alertmanager config (`platform/monitoring/alertmanager`) a receiver `kagent-sre` with `webhook_configs: [{url: "http://kagent-telegram-bot.kagent.svc.cluster.local:8080/alertmanager", send_resolved: true}]` and a route to it (for example `severity=~"warning|critical"`, `group_wait: 30s`, `repeat_interval: 4h`). The existing receivers keep working; this one adds the investigation.

Gate: bot pod Ready; `/start` in the operator chat answered; a synthetic Alertmanager payload POSTed to the webhook yields the one-line alert and an investigation message in the chat; after the Alertmanager change, a real or test alert (`amtool alert add`) does the same end to end.

### Phase 5: Scoped write access (explicit approval per agent)

Design, not yet implemented: set `kagent-tools.tools.k8s.tokenPassthrough: true` so the tool server uses the **calling agent's** ServiceAccount token, give each agent its own ServiceAccount (`deployment.serviceAccountName`) with a `Role`/`RoleBinding` listing exactly the verbs and namespaces it may touch, and keep `homelab-sre` read-only. The existing `k8s-agent` keeps the shared read-only ClusterRole. Each such agent is its own PR with its RBAC reviewed.

## Validation and rollback

- Per phase gates above. Manifests: `kustomize build clusters/titania/apps/kagent | kubectl apply --dry-run=client -f -` (CRDs now exist, so the Agent and RemoteMCPServer validate) plus `--dry-run=server` for schema; `kustomize build clusters/titania/infra/monitoring` and `.../reloader` client dry-runs.
- Rollback phase 1–2: revert the PR; Flux prunes the Deployment, Service, ExternalSecret, RemoteMCPServer and Agent. Revoke the Grafana service-account token in Grafana and delete `services/grafana/kagent` after the consumer is gone. Phase 3: switch `bundled.enabled` back and drop `urlFile`; the Helios database stays until removed from the catalog.

Risks:

- The Grafana token is Viewer-only and the server runs with `--disable-write`, but Loki and Prometheus contents (log lines, label values) are sent to the model provider. Until the ModelConfig points at `qwen-intel`, DeepSeek sees them.
- The UI is still unauthenticated (plan 0019 follow-up). The new agent widens what an anonymous LAN user can read: logs and metrics, not just resources.
- Provider spend: long investigations chain many tool calls. Watch the `kagent` key spend in LiteLLM.

## Outcome

- 2026-10-26, phases 1–2 merged in PR #427 (reviewed: six findings; the Host allowlist blocker, the `--enabled-tools` form, a NetworkPolicy on the MCP endpoint, the CPU limit and datasource UIDs were fixed before merge; all flags verified against the pinned image with `docker run`). Post-merge: `grafana-mcp` Ready, `RemoteMCPServer` Accepted after a startup race, Loki datasource present in Grafana (`uid: loki`), `homelab-sre` Accepted and Ready. `list_datasources` works with the Viewer token, so no extra Grafana role was needed.
- PR #428: the first agent run got Forbidden on Flux objects and nodes because the chart's read-only rule set covers core workloads only; `rbac.additionalRules` added read access to nodes, cluster storage and the cluster's CRDs (Secrets still excluded). After it, the agent listed Kustomization and HelmRelease status and queried Loki through the UI proxy A2A endpoint (completed task in 26s).
- Finding: Grafana MCP `query_prometheus` is an MCP App (`_meta.ui.resourceUri: ui://grafana/metrics.html`); kagent's runtime logs "Wiring MCP App model result callback" and gives the rendered result to the UI, so the model never sees the numbers. Numeric PromQL therefore uses the kagent tool server's `prometheus_query_tool`/`prometheus_query_range_tool` against Thanos Query (`kagent-tools.tools.prometheus.url`); the Grafana tools stay for Loki, metric discovery, alert rules and dashboards.
- 2026-10-27, phase 4 merged in PR #433 (bot image `ghcr.io/kmjayadeep/kagent-telegram-bot:20261026195419` from docker-images `c8e0ddf`). Verified: pod Ready, ExternalSecret synced (token and chat id), a synthetic firing alert POSTed from an Alertmanager-labelled pod in `monitoring` returned `investigated: true` and the agent investigation ran; a pod without that label is blocked by the NetworkPolicy. Telegram delivery returned "chat not found" because the operator chat has not yet opened the new bot; `/start` from the operator's account is the remaining gate, then the Alertmanager receiver in Vault.
- Pending: phase 3 (Helios rebuild and the embedding model decision), phase 4 operator steps (`/start`, Alertmanager receiver), phase 5 (write access).
