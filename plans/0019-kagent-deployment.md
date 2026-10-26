# Plan 0019: Deploy kagent behind LiteLLM

- Status: Completed 2026-10-26 (follow-ups listed below remain open)
- Owner: Jayadeep KM
- Related ADR: none yet; [ADR 0001](../adrs/0001-vault-external-secrets.md) (secrets) and [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md) (LiteLLM as the only model entry point) apply

## Goal and scope

Deploy [kagent](https://kagent.dev/) (Kubernetes-native AI agent framework, chart `0.10.4`) into a new `kagent` namespace on titania through Flux, with:

- **LiteLLM as the only model endpoint.** kagent's `ModelConfig` uses `provider: OpenAI` with `baseUrl` set to the in-cluster LiteLLM service and authenticates with a LiteLLM virtual key dedicated to kagent, exactly like Open WebUI does today. kagent never holds an upstream provider key.
- **DeepSeek first, local llama.cpp later.** LiteLLM already serves `deepseek-v4-flash` and `deepseek-v4-pro` as database-managed models (configured in its Admin UI, credential in its database, not in Git or Vault). The `ModelConfig` starts with `model: deepseek-v4-flash`. Switching kagent to the local backend is a one-line change of that `model` field to `qwen-intel`; every `Agent` references the `ModelConfig`, not the model name, so agents do not change.
- **Minimal footprint.** Only the core (controller, UI, kmcp controller, tool server, bundled PostgreSQL) plus the `k8s-agent`. The Istio, kgateway, Argo Rollouts, Cilium, Helm, PromQL, observability agents and the Grafana MCP server are disabled. No Istio, Knative, Gateway API, agentgateway or substrate components are installed.
- **Read-only cluster tools to start.** The kagent tool server's RBAC is set to the chart's read-only rule set (no Secrets). Widening to write access is a separate, explicitly approved step.

Out of scope: agent memory / pgvector, oauth2-proxy SSO, external PostgreSQL on Helios, custom agents and MCP servers beyond the defaults. These are listed as follow-ups.

Why a plan: the change spans two repositories (Vault roles in `homelab-iac`, manifests here), adds CRDs and cluster-scoped RBAC, and needs a staged rollout with gates.

Design note: a LiteLLM-side stable name (`model_group_alias` or a Git `model_list` entry) was considered and rejected. Aliases drift to the database value after Helm upgrades (LiteLLM README, "Alias drift"), and a Git `model_list` entry cannot reference the database-managed DeepSeek credential without copying the key into Vault. Changing the `ModelConfig` in Git is equally one line and has no drift.

## Starting state and prerequisites

Verified in this repository on 2026-10-26:

- Apps follow the pattern in `clusters/titania/apps/open-webui/`: a Flux `Kustomization` in `clusters/titania/bootstrap/apps/<app>.yaml`, a Kustomize entry point with `HelmRepository` + `HelmRelease`, and an `external-secret.yaml` holding the `ServiceAccount` `external-secrets-vault`, a namespaced `SecretStore` (Vault Kubernetes auth, role named after the app, CA from the `vault-ca-cert` ConfigMap) and an `ExternalSecret`.
- `actions-runner.yaml` shows the two-stage pattern (one Flux Kustomization depending on another). kagent needs it because its CRDs ship in a separate chart and the `ModelConfig` CR must be applied after the CRDs exist.
- Open WebUI consumes LiteLLM at `http://litellm.litellm.svc.cluster.local:4000/v1` with the virtual key at Vault path `apps/litellm/open-webui` (property `api_key`).
- The wildcard TLS Secret `cosmos-cboxlab-cert` is auto-reflected into every namespace (Reflector annotations on the Certificate in `cert-manager-clusterissuer/`), so a new namespace needs no cert work.
- external-dns creates Cloudflare records from Ingress objects; ingress-nginx is on a MetalLB LAN pool (`192.168.1.180-199`), so a new hostname is LAN/VPN-reachable, not public.
- Renovate's `flux` manager tracks `HelmRelease` chart versions, including OCI sources.

Verified on the live LiteLLM on 2026-10-26 (from inside the pod, model names and key metadata only):

- Database-managed models `deepseek-v4-flash`, `deepseek-v4-pro`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, all with `supports_function_calling: true`; Git-managed `swift-qwen3.8-27b-q3km-intel` and `tiel-coder-35b-a3b-intel`; alias `qwen-intel` → Swift.
- A virtual key with alias `kagent` was created on 2026-10-26 with no model restriction (`models: []`, like most existing keys). Restricting it to `deepseek-v4-flash` and `qwen-intel` in the Admin UI is recommended but optional.

Verified upstream (chart `oci://ghcr.io/kagent-dev/kagent/helm/kagent:0.10.4`, pulled and templated locally on 2026-10-26):

- `kagent-crds` `0.10.4` is a separate chart; its CRDs are ordinary templates (not a `crds/` directory), so Helm upgrades them. It also installs the kmcp `MCPServer` CRD when `kmcp.enabled: true`.
- `providers: null` suppresses the chart-generated `ModelConfig` and Secret. Default agents reference the `ModelConfig` named `default-model-config` in the release namespace when their `modelConfigRef` is empty.
- `ModelConfig` for an OpenAI-compatible endpoint: `provider: OpenAI`, `model`, `apiKeySecret`, `apiKeySecretKey`, `openAI.baseUrl`.
- SQLite is gone; PostgreSQL is the only backend. `database.postgres.bundled.enabled: true` deploys `postgres:18.6-alpine3.23` with a 500Mi PVC on the default StorageClass unless `storageClassName` is set. The chart calls this "development and evaluation only".
- `rbac.namespaces: []` (default) gives the controller a cluster-wide `ClusterRole`; a non-empty list that includes the install namespace gives per-namespace `Role`s and limits watched namespaces.
- The `kagent-tools` subchart defaults to a `ClusterRole` with `apiGroups/resources/verbs: *` (cluster-admin) plus `nonResourceURLs: *`. `rbac.readOnly: true` switches to a get/list/watch rule set over core, apps, batch, networking and autoscaling resources, Secrets only with `rbac.allowSecrets: true`.
- Every default agent subchart (`k8s-agent`, `kgateway-agent`, `istio-agent`, `promql-agent`, `observability-agent`, `argo-rollouts-agent`, `helm-agent`, `cilium-policy-agent`, `cilium-manager-agent`, `cilium-debug-agent`) and `grafana-mcp` are `enabled: true` by default and each creates an `Agent` CR and a Deployment (50m/128Mi requests, 256Mi limit).
- The chart has no Ingress template. UI exposure is an OpenShift `Route` (no-op here), an optional Gateway API `HTTPRoute` (disabled), or your own Ingress to Service `kagent-ui:8080`. The UI streams over SSE; the chart's own nginx uses 1800s read/send timeouts, so the Ingress must match.
- `controller.auth.mode: unsecure` by default: the UI has no authentication. `oauth2-proxy` is an optional subchart (OIDC).
- Resources: controller 100m/128Mi–2/512Mi, UI 100m/256Mi–1/1Gi, tools 50m/128Mi–256Mi, kmcp 10m/64Mi–500m/128Mi, bundled Postgres 250m/256Mi–500m/512Mi. Probes are defined by the chart.

Verified for DeepSeek (api-docs.deepseek.com, 2026-10-26): current models are `deepseek-v4-flash` and `deepseek-v4-pro` (1M context, function calling). `deepseek-chat` and `deepseek-reasoner` were retired on 2026-07-24.

Not verified (cluster state): nothing kagent-related exists on titania; no `kagent.dev` CRDs are installed.

Approvals needed before live action:

1. ~~Applying the `homelab-iac` Vault role change and importing the key.~~ Done (step 1).
2. Merging the kagent manifests (Flux reconciles; new CRDs and cluster-scoped RBAC objects are created).
3. Any later widening of tool RBAC beyond read-only, or exposing the UI beyond the LAN.

## Steps and gates

### Step 1: Vault path and role (`homelab-iac`) — done 2026-10-26

| Logical path | Property | Owner / meaning | Consumers |
| --- | --- | --- | --- |
| `apps/litellm/kagent` | `api_key` | LiteLLM virtual key (alias `kagent`) used only by kagent | `kagent` role only |

Done: `external_secrets_roles.kagent` (namespace `kagent`, ServiceAccount `external-secrets-vault`, path `apps/litellm/kagent`) added to `vault-config/external-secrets.tf`, PATHS.md inventory row added, stdin-only `import-litellm-kagent-key.sh` added. Terraform applied (policy `external-secrets-kagent` and Kubernetes auth role `kagent` created). The value was imported from the operator's password store through the script; `vault kv metadata get` shows version 1 with the required custom metadata.

A `services/deepseek/litellm` path was added and then removed the same day once it was confirmed that LiteLLM already holds the DeepSeek credential in its database. The `litellm` policy is back to its previous two paths.

### Step 2: LiteLLM — no manifest change (README done in PR #416)

LiteLLM needs no Git change: `deepseek-v4-flash` already exists and the kagent key already exists. Remaining items:

- Optional, Admin UI: restrict the `kagent` key to models `deepseek-v4-flash` and `qwen-intel`.
- `clusters/titania/apps/litellm/README.md`: add kagent to the client list and note that kagent's model is chosen in `clusters/titania/apps/kagent/model-config.yaml`. Done together with step 3.

Gate: one benign chat request to `deepseek-v4-flash` through `https://litellm.cosmos.cboxlab.com` with the kagent key succeeds (check the response status and LiteLLM spend log, do not print the key).

### Step 3: kagent manifests (this repo, PR #416)

New files:

`clusters/titania/bootstrap/apps/kagent.yaml`

- `Namespace` `kagent` with standard labels.
- Flux `Kustomization` `kagent-crds` (namespace `kagent`): path `clusters/titania/apps/kagent-crds`, `prune: true`, `wait: true`, `timeout: 5m`, health check on `HelmRelease` `kagent-crds`.
- Flux `Kustomization` `kagent` (namespace `kagent`): path `clusters/titania/apps/kagent`, `dependsOn` `kagent-crds` (ns `kagent`), `external-secrets` (ns `external-secrets`), `litellm` (ns `flux-system`); `prune: true`, `wait: true`, `timeout: 15m` (above the HelmRelease's own 10m; the controller restarts a few times while bundled Postgres starts), health check on `HelmRelease` `kagent`.
- The `Namespace` carries `kustomize.toolkit.fluxcd.io/prune: disabled` like `vault`: a namespace deletion would uninstall `kagent-crds` through the HelmRelease finalizer and remove every Agent, so protecting only the HelmRelease is not enough.

`clusters/titania/apps/kagent-crds/`

- `kustomization.yaml` (namespace `kagent`), `helm-repo.yaml` (`HelmRepository` `kagent`, `type: oci`, `url: oci://ghcr.io/kagent-dev/kagent/helm`, prune disabled because both HelmReleases depend on it), `helm-release.yaml` (`HelmRelease` `kagent-crds`, chart `kagent-crds` `0.10.4`, values `kmcp.enabled: true`, `substrate.enabled: false`). Annotate the HelmRelease `kustomize.toolkit.fluxcd.io/prune: disabled`, matching the stateful anchors in the repository map: pruning the CRDs would delete every `Agent`, `ModelConfig` and `RemoteMCPServer` instantly.

`clusters/titania/apps/kagent/`

- `kustomization.yaml` (namespace `kagent`) listing the files below.
- `network-policy.yaml`: ingress to the bundled PostgreSQL pod only from the controller pod on 5432. The chart renders a fixed `kagent` password, so without this any pod in the cluster could read the session store.
- `README.md`: layout, model switch, key rotation and restart procedure, risks.
- `external-secret.yaml`: `ServiceAccount` `external-secrets-vault`, `SecretStore` `vault` (role `kagent`, same server/CA/mount as the other apps), `ExternalSecret` `kagent-litellm` → Secret `kagent-litellm` with key `LITELLM_API_KEY` from `apps/litellm/kagent` / `api_key`; `deletionPolicy: Retain`.
- `model-config.yaml`: `ModelConfig` `default-model-config` (`kagent.dev/v1alpha2`) with `provider: OpenAI`, `model: deepseek-v4-flash`, `apiKeySecret: kagent-litellm`, `apiKeySecretKey: LITELLM_API_KEY`, `openAI.baseUrl: http://litellm.litellm.svc.cluster.local:4000/v1`. The name must stay `default-model-config` because the default agents reference it implicitly. A comment records that `qwen-intel` is the local alternative.
- `ingress.yaml`: `Ingress` `kagent`, class `nginx`, host `kagent.cosmos.cboxlab.com`, TLS secret `cosmos-cboxlab-cert`, backend Service `kagent-ui` port `8080`, annotations `proxy-read-timeout`/`proxy-send-timeout: "1800"` and `proxy-buffering: "off"` for SSE.
- `helm-release.yaml`: `HelmRelease` `kagent`, chart `kagent` `0.10.4` from `HelmRepository` `kagent`, `dependsOn` `kagent-crds`, install/upgrade remediation like the other apps. Values:

```yaml
providers: null                 # ModelConfig is managed in Git (model-config.yaml)
rbac:
  namespaces: [kagent]          # controller watches only this namespace, Role instead of ClusterRole
controller:
  auth:
    mode: unsecure              # no UI auth yet; LAN-only exposure, see risks
database:
  postgres:
    bundled:
      enabled: true
      storageClassName: longhorn
      storage: 2Gi
ui:
  externalUrl: https://kagent.cosmos.cboxlab.com
  route:
    enabled: false
kmcp:
  enabled: true
kagent-tools:
  enabled: true
  rbac:
    readOnly: true
    allowSecrets: false
  tools:
    loglevel: info
k8s-agent:
  enabled: true
kgateway-agent: {enabled: false}
istio-agent: {enabled: false}
promql-agent: {enabled: false}
observability-agent: {enabled: false}
argo-rollouts-agent: {enabled: false}
helm-agent: {enabled: false}
cilium-policy-agent: {enabled: false}
cilium-manager-agent: {enabled: false}
cilium-debug-agent: {enabled: false}
grafana-mcp: {enabled: false}
oauth2-proxy: {enabled: false}
substrate: {enabled: false}
```

Confirm during implementation that the `ui.externalUrl` and nested `{enabled: false}` forms render (run `helm template` with these values before committing). Also confirm whether the bundled PostgreSQL PVC should carry `kustomize.toolkit.fluxcd.io/prune: disabled`; it is evaluation data, so the default is to leave it prunable.

Secret rotation: the LiteLLM key is injected into agent Deployments created by the kagent controller, which Helm does not annotate for Reloader. Document the GitOps restart procedure instead of adding `kagent` to Reloader: after a key rotation, `kubectl -n kagent rollout restart deployment -l app.kubernetes.io/name=k8s-agent` (adjust the selector to the rendered labels) with operator approval.

Validation before merge:

```bash
kustomize build clusters/titania/apps/kagent-crds | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/kagent | kubectl apply --dry-run=client -f -
```

The second command fails on the `ModelConfig` until the `kagent.dev` CRDs exist in the cluster (client dry-run needs the kind registered). Report that explicitly and validate the CR separately with `helm template kagent-crds ... | kubectl apply --dry-run=client -f -` plus a schema check of the `ModelConfig` against the CRD (`kubeconform` with the CRD schema, or a dry-run after the CRD Kustomization has reconciled).

Gate: after merge and Flux reconciliation (only when the operator asks to reconcile), `flux get kustomizations -n kagent` shows both Ready; all pods in `kagent` Running (controller, ui, kmcp, tools, postgres, k8s-agent); `kubectl get modelconfig,agent -n kagent` shows Accepted/Ready conditions; the Ingress resolves and serves the UI; a chat with `k8s-agent` ("list pods in litellm") returns a tool-backed answer through LiteLLM (check LiteLLM spend logs for the `kagent` key, not the model response text).

### Step 4: Documentation (PR #416)

- `plans/README.md`: keep this plan's status current.
- `docs/README.md`: add a row "Run or extend kagent" pointing at this plan and `clusters/titania/apps/kagent/`.
- `clusters/titania/apps/litellm/README.md`: client list and the kagent model note (step 2).

### Follow-ups (not in this plan)

- Switch kagent to local inference once the B60 model is judged good enough for agentic tool use: change `model` in `model-config.yaml` to `qwen-intel`.
- Widen tool RBAC (`allowSecrets`, write verbs, or `readOnly: false`) per agent, with explicit approval and an ADR if it becomes durable.
- UI authentication: nginx basic-auth annotation as a quick guard, or `oauth2-proxy` with an OIDC provider.
- External PostgreSQL on Helios (`services/postgresql/kagent`, `urlFile` via a mounted ESO Secret, `vectorEnabled` if pgvector is wanted for memory), following `../homelab-iac/docs/platform/postgres.md` onboarding.
- `promql-agent` against the in-cluster Prometheus (`kagent-tools.tools.prometheus.url` → the `kube-prometheus-stack` service in `monitoring`; verify the Service name first) and the Grafana MCP with a Grafana service-account token in Vault.
- Custom agents and MCP servers as further `Agent`/`RemoteMCPServer`/`MCPServer` manifests under `clusters/titania/apps/kagent/`.

## Validation and rollback

Reproducible checks are listed per step above. Rollback, each with explicit approval:

- **kagent**: revert the manifests PR. Flux prunes the app Kustomization's contents (HelmRelease `kagent`, ModelConfig, Ingress, ExternalSecret, NetworkPolicy) but leaves the `kagent` Namespace, the `HelmRepository` and the `kagent-crds` HelmRelease (all prune disabled); removing those and the CRDs is a manual, approved step. Bundled Postgres data is lost with the PVC; that is acceptable for evaluation.
- **LiteLLM**: revoke the `kagent` virtual key in the Admin UI.
- **Vault**: remove the `kagent` role in `homelab-iac`; delete `apps/litellm/kagent` only after the consumer is gone.

Risks to carry in the PR description:

- The kagent UI has no authentication and gives anyone on the LAN/VPN an agent with cluster-wide read access (pods, logs, configmaps, events). Logs and ConfigMaps can contain sensitive data even though Secrets are excluded.
- DeepSeek receives cluster metadata returned by the tools (resource names, log excerpts) until the `ModelConfig` is pointed at `qwen-intel`.
- The bundled PostgreSQL is a single pod on Longhorn with no backups and the chart's fixed credentials; sessions are disposable and a NetworkPolicy limits access to the controller.
- Chart `0.x`: breaking changes between minors are common (SQLite removal, `rbac.clusterScoped` removal in `0.9`). Read release notes on each Renovate PR before merging.

## Outcome

- 2026-10-26: step 1 complete (`homelab-iac` commits `d6727c4`, `ed6a0bb`, `6322102`). Steps 2–4 merged in PR #416 after a review with nine findings; the Namespace/HelmRepository prune protection, the Postgres NetworkPolicy, the Kustomization timeout, the stale Vault key metadata and the rotation README were fixed before merge. UI authentication stays an accepted follow-up.
- 2026-10-26 post-merge validation (revision `2319f9c1`, later `47b95e5a`): both Flux Kustomizations Ready within about two minutes of the source reconcile; HelmReleases `kagent-crds` and `kagent` at `0.10.4` installed; pods `kagent-controller` (3 restarts during the cold start, none after), `kagent-ui`, `kagent-kmcp-controller-manager`, `kagent-tools`, `kagent-postgresql` and `k8s-agent` all Running; `ModelConfig` Accepted; `Agent` Accepted and Ready; `SecretStore` Valid and `ExternalSecret` SecretSynced (key name only checked); PVC Bound on Longhorn (2Gi); Ingress served the UI with HTTP 200 over TLS. The agent log shows the OpenAI model `deepseek-v4-flash` initialized against the LiteLLM Service with the tool server's 18 tools attached, and sessions stored through the controller (so the Postgres NetworkPolicy is sufficient).
- **Open blocker:** an A2A `message/send` to `k8s-agent` ("list the pods in the litellm namespace") returned a `failed` task: LiteLLM accepted the kagent key and forwarded to DeepSeek, which answered 401 "Authentication Fails (governor)". The same 401 occurs for `deepseek-v4-flash` and `deepseek-v4-pro` when called inside the LiteLLM pod with the master key, and LiteLLM's spend logs hold no DeepSeek request for the last 7 days, so the DeepSeek credential stored in LiteLLM's database (referenced by `litellm_credential_name`) is invalid or revoked. This is a LiteLLM-side fix in the Admin UI (Credentials), outside Git. `qwen-intel` answered HTTP 200 through LiteLLM in the same check, so switching `model-config.yaml` to `qwen-intel` is a working alternative. The end-to-end gate in step 3 stays open until one of the two is done.
- 2026-10-26, later: the operator repaired the DeepSeek credential in the LiteLLM Admin UI and confirmed a chat in the kagent UI. The same A2A `message/send` then returned a `completed` task naming the running LiteLLM pod through `deepseek-v4-flash`, closing the step 3 gate. Plan complete; the follow-ups (UI auth, tool RBAC widening, Helios PostgreSQL, PromQL/Grafana agents, local model switch) are tracked above and need their own approval.
- Incidental: the LiteLLM chart was bumped twice by Renovate during the rollout (PRs #411, #412), which briefly left the `litellm` Kustomization not Ready and delayed the `kagent` Kustomization through its `dependsOn`; both recovered on their own.
