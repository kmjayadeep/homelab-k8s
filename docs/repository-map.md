# Repository map

The active GitOps tree is `clusters/titania/`. Older cluster names in the root README are history, not additional trees in this repository.

## Reconciliation path

1. `clusters/titania/bootstrap/flux-system/gotk-sync.yaml` points Flux at `clusters/titania/bootstrap/` on `main`. This file is Flux-generated; do not hand-edit it.
2. `clusters/titania/bootstrap/apps/` and `clusters/titania/bootstrap/infra/` contain Flux `Kustomization` resources: they select a path, namespace, source, ordering, and pruning behavior. These are **not** the same as Kustomize `kustomization.yaml` files.
3. `clusters/titania/apps/<app>/` and `clusters/titania/infra/<component>/` contain the workloads and Kustomize entry points built by those Flux resources. Some apps have nested directories; inspect their `kustomization.yaml` before editing.
4. A directory existing under `apps/` or `infra/` does not prove it is reconciled. Check its bootstrap Flux Kustomization, Kustomize resources, and any replica count before asserting that a workload is live.

A new app typically needs a namespace and Flux Kustomization in `bootstrap/apps/`, an app Kustomize entry point, and its manifests. Infrastructure components follow the corresponding `bootstrap/infra/` pattern. Check dependencies and health checks in nearby examples; never assume adding a file to a directory makes Flux deploy it. `prune: true` is common: removing or renaming a referenced resource can delete live resources on reconciliation. Treat such changes as destructive and seek approval per [AGENTS.md](../AGENTS.md).

## Other paths

- `adrs/`: accepted and superseded long-term decisions; [index](../adrs/README.md).
- `plans/`: rollout steps, experiments, and historical evidence; [index](../plans/README.md).
- `docs/`: current explanatory material, including this map and [change workflow](change-workflow.md).
- `automation/`: repository automation; do not assume a proposed runner exists just because it is described in a plan or ADR.
- `kubeseal/`: legacy public keys retained while the Sealed Secrets controller is decommissioned; do not create new SealedSecret resources.
- `../homelab-iac/vault-config/PATHS.md`: canonical Vault path taxonomy in a **sibling repository**; check that it exists before work that depends on it.

For secrets and deployment safeguards, read [AGENTS.md](../AGENTS.md) and [ADR 0001](../adrs/0001-vault-external-secrets.md). Never inspect secret values to learn the repository layout.
