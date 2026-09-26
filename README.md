# Homelab K8s

FluxCD GitOps manifests for the active `titania` homelab cluster. Flux watches `main` and reconciles the bootstrap tree under `clusters/titania/`. Earlier clusters (Andromeda, Milkyway, Cosmos) are historical and do not have manifest trees here.

![Homer dashboard](assets/homer.png)

## Start here

- [Documentation map](docs/README.md): where to find current behavior, decisions, and plans.
- [Repository map](docs/repository-map.md): how Flux bootstrap and Kustomize fit together.
- [Change workflow](docs/change-workflow.md): how to propose, validate, and document changes.
- [Agent instructions](AGENTS.md): mandatory safety and validation rules for agents and useful guardrails for humans.
- [ADR index](adrs/README.md) and [plan index](plans/README.md): architectural decisions and rollout/evaluation history.

## Layout

- `clusters/titania/bootstrap/`: Flux source and per-app/infrastructure Kustomizations. This is the live reconciliation entry point; pruning can remove resources.
- `clusters/titania/apps/`: application manifests and Kustomize entry points.
- `clusters/titania/infra/`: infrastructure manifests and Kustomize entry points.
- `docs/`: current explanations and working conventions.
- `adrs/`: durable architectural decisions, including superseded history.
- `plans/`: implementation plans and evaluations, including retained completed plans.
- `kubeseal/`: legacy public keys, not a source for new secrets.

## Secrets

Vault is the source of truth for application and infrastructure secret values. External Secrets Operator uses namespaced stores and Kubernetes ServiceAccounts to create Kubernetes Secrets. Git stores only non-secret references and configuration. No SealedSecret manifests remain; the controller is temporarily retained. See [ADR 0001](adrs/0001-vault-external-secrets.md), [the migration plan](plans/0001-sealed-secrets-to-vault.md), and [AGENTS.md](AGENTS.md) before touching secrets. Vault internal TLS is still follow-up work.

## Repository automation

[ADR 0002](adrs/0002-autonomous-repository-agent.md) and [plan 0002](plans/0002-autonomous-ai-agent.md) describe a proposed/approved local agent workflow. Do not assume the runner is available: verify the implementation in `automation/` first. Agents editing this repository must follow [AGENTS.md](AGENTS.md) regardless of which harness runs them.
