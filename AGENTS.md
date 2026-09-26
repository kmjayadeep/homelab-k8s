# AGENTS.md

## Repository

Kubernetes homelab managed through FluxCD GitOps. Cluster manifests live under `clusters/titania/`; Kustomize manages manifests. Vault with External Secrets is the active architecture for application and infrastructure secrets. The Sealed Secrets controller is temporarily retained, but no SealedSecret manifests remain.

## Where to start

- Read [the documentation map](docs/README.md) and [repository map](docs/repository-map.md) to locate the affected Flux and Kustomize paths. For changes, follow [the change workflow](docs/change-workflow.md).
- `AGENTS.md` is the safety and validation contract; `docs/` explains current behavior, `adrs/` records durable decisions, and `plans/` tracks work in progress or retained historical evidence. Read relevant pages, not every plan in the repository. Manifests are desired state; do not assume they prove live cluster state.
- Keep docs and their indexes current when behavior or decisions change. Use an ADR for a consequential long-lived trade-off, a plan for multi-step or risky work, and neither for a routine manifest edit. See the templates and lifecycle rules in the change workflow.

## Safety rules

- **Never read plaintext secrets into agent context.** Do not use `read`, `cat`, `grep`, decode commands, logs, Terraform output, or `kubectl get` to display values. For debugging, extract only key names, hashes/equality results, readiness conditions, or other non-secret metadata.
- Store canonical values in Vault under the taxonomy in `homelab-iac/vault-config/PATHS.md`; Git contains only ServiceAccounts, stores, paths, property mappings, policies, and roles.
- Do not create `*-decrypted.yaml`, `*-sealed.yaml`, or new SealedSecret resources. A bootstrap exception requires explicit approval and an ADR update.
- When importing or rotating a value, use stdin or another non-logging file-to-file workflow, suppress command output, and never place values in command arguments, shell history, plans, or agent messages.
- **Never perform destructive operations without explicit human approval.** This includes `rm`, `kubectl delete`, pruning/removing Flux resources, force operations, database/data deletion, and destructive rewrites. Explain the impact and wait for approval.
- Do not apply or reconcile changes to the cluster unless explicitly requested.

## Vault and External Secrets

- Before changing Vault, ESO, `SecretStore`/`ClusterSecretStore`, `ExternalSecret`, Reloader, or secret paths, read `adrs/0001-vault-external-secrets.md`, `plans/0001-sealed-secrets-to-vault.md`, and the sibling repository's `../homelab-iac/plans/0001-vault-secret-migration.md` and `../homelab-iac/vault-config/PATHS.md`. If the sibling repo is unavailable, stop and request the missing context instead of guessing paths or policy.
- Store application secret values in Vault, never in Git. Git may contain only non-secret references, policies, roles, and External Secrets manifests.
- Use Vault Kubernetes authentication and least-privilege namespaced stores by default; do not introduce static Vault tokens or a broad `ClusterSecretStore` without explicit approval.
- Keep Vault recovery/unseal material and the initial root token outside both Git and the cluster.
- Use a namespaced `SecretStore` and dedicated ServiceAccount per trust boundary. Shared values remain at one owner-based Vault path and are authorized to each consumer separately.
- ESO updates Kubernetes Secrets but does not restart pods using environment variables. Add the namespace to the scoped Reloader release and annotate the workload for automatic rollout, or document a GitOps restart procedure.
- Vault internal TLS remains follow-up work. Existing stores temporarily use `http://vault.vault.svc.cluster.local:8200`; do not treat HTTP as the final design.

## Conventions

- Use 2-space YAML indentation. Put `apiVersion` and `kind` first.
- Keep app-specific manifests in `clusters/titania/apps/<app>/` with a `kustomization.yaml`.
- Define resource requests and limits, plus readiness and liveness probes, for workloads.
- Use standard Kubernetes labels, including `app.kubernetes.io/name` and `app.kubernetes.io/instance`.
- Use TLS for ingresses where certificates are available.

## Validation

```bash
# Build and validate an app or infrastructure kustomization
kustomize build clusters/titania/apps/<app> | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/infra/<component> | kubectl apply --dry-run=client -f -

# Inspect Flux state when requested
flux get all -n flux-system
```

Run the relevant Kustomize build and client dry-run after manifest changes. Report validation results and any remaining risks.
