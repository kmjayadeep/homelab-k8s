# kagent

[kagent](https://kagent.dev/) runs Kubernetes-aware AI agents. Deployed per [plan 0019](../../../../plans/0019-kagent-deployment.md). UI: `https://kagent.cosmos.cboxlab.com` (LAN/VPN only, no authentication yet).

## Layout

- `../kagent-crds/`: CRD chart (`kagent-crds`), prune disabled together with the shared `HelmRepository`. The Namespace in `bootstrap/apps/kagent.yaml` is prune disabled too; removing kagent is a deliberate manual action.
- `helm-release.yaml`: chart values. Only `k8s-agent` is enabled; the tool server has read-only cluster RBAC without Secrets; the controller is scoped to this namespace.
- `model-config.yaml`: the single `ModelConfig` every default agent uses. `model` is a LiteLLM model name.
- `external-secret.yaml`: LiteLLM virtual key (alias `kagent`) from Vault `apps/litellm/kagent`.
- `network-policy.yaml`: only the controller may reach the bundled PostgreSQL, which uses the chart's fixed credentials.
- `grafana-mcp.yaml`: Grafana MCP server (`grafana/mcp-grafana`, read-only flags) with a Viewer service-account token from Vault `services/grafana/kagent`, plus its `RemoteMCPServer`. Gives agents Prometheus, Loki, alert-rule and dashboard tools ([plan 0020](../../../../plans/0020-kagent-sre-agent.md)).
- `agent-homelab-sre.yaml`: the read-only `homelab-sre` agent: cluster-specific prompt, Kubernetes read tools and the Grafana tools, A2A skills `investigate` and `health-report`.

## Agents

| Agent | Purpose | Tools |
| --- | --- | --- |
| `k8s-agent` | Chart default, generic Kubernetes assistant | all `k8s_*` tools (writes fail: tool RBAC is read-only) |
| `homelab-sre` | Investigate and explain titania, propose Git changes | read-only `k8s_*`, Grafana Prometheus/Loki/alerting/dashboards |

Ask `homelab-sre` through the UI or A2A. The canonical A2A endpoint is the controller Service, `http://kagent-controller.kagent.svc.cluster.local:8083/api/a2a/kagent/homelab-sre/`; the UI Ingress proxies the same path (`https://kagent.cosmos.cboxlab.com/api/a2a/kagent/homelab-sre/`, a JSON-RPC `message/send` through it was verified on 2026-10-26 in plan 0019).

## Telegram bot and alert triage

`telegram-bot.yaml` runs `ghcr.io/kmjayadeep/kagent-telegram-bot` (source in the `docker-images` repository). It long-polls Telegram and forwards messages from the operator chat to `homelab-sre` over A2A (one session per chat, `/new` resets), and serves `POST /alertmanager` for Alertmanager: every firing or resolved alert is posted to the chat, and a firing group triggers one agent investigation per hour whose result is posted too. Token and chat id come from Vault `services/telegram/kagent-bot`; a NetworkPolicy admits only Alertmanager pods to the webhook. Alertmanager's receiver (`webhook_configs` → `http://kagent-telegram-bot.kagent.svc.cluster.local:8080/alertmanager`, `send_resolved: true`) is configured in the Vault-held Alertmanager config, not in Git.

## Rotate the Grafana token

Create a new token for the Grafana service account `kagent-mcp` (Viewer), import it with `../homelab-iac/vault-config/import-grafana-kagent-token.sh`, wait for the `ExternalSecret` refresh (or force-sync), and Reloader restarts `grafana-mcp`. Delete the old token in Grafana.

## Change the model

Edit `spec.model` in `model-config.yaml` and merge. `deepseek-v4-flash` and `deepseek-v4-pro` are database-managed in LiteLLM; `qwen-intel` is the local llama.cpp alias. Agents reference the `ModelConfig`, so nothing else changes. Confirm with a chat in the UI and the LiteLLM spend log for the `kagent` key.

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

- No UI authentication; anyone on the LAN/VPN gets read access to pods, logs, ConfigMaps and events through the agent.
- Tool output is sent to the configured model provider (DeepSeek until the model is switched to `qwen-intel`).
- The bundled PostgreSQL is evaluation-grade, single pod, no backups.
