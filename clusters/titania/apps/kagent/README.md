# kagent

[kagent](https://kagent.dev/) runs Kubernetes-aware AI agents. Deployed per [plan 0019](../../../../plans/0019-kagent-deployment.md). UI: `https://kagent.cosmos.cboxlab.com` (LAN/VPN only, no authentication yet).

## Layout

- `../kagent-crds/`: CRD chart (`kagent-crds`), prune disabled together with the shared `HelmRepository`. The Namespace in `bootstrap/apps/kagent.yaml` is prune disabled too; removing kagent is a deliberate manual action.
- `helm-release.yaml`: chart values. Only `k8s-agent` is enabled; the tool server has read-only cluster RBAC without Secrets; the controller is scoped to this namespace.
- `model-config.yaml`: the single `ModelConfig` every default agent uses. `model` is a LiteLLM model name.
- `external-secret.yaml`: LiteLLM virtual key (alias `kagent`) from Vault `apps/litellm/kagent`.
- `network-policy.yaml`: only the controller may reach the bundled PostgreSQL, which uses the chart's fixed credentials.

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
