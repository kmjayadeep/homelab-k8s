# Documentation map

Start with [the repository overview](../README.md). Agents must also follow [AGENTS.md](../AGENTS.md); it contains the safety and validation rules, not just navigation.

| Need | Read |
| --- | --- |
| Find the deployment path and ownership of a manifest | [Repository map](repository-map.md) |
| Make or review a change safely | [Change workflow](change-workflow.md) |
| Understand an enduring architectural choice | [ADR index](../adrs/README.md) |
| Track a rollout, investigation, or evaluation | [Plan index](../plans/README.md) |
| Change Vault/ESO resources or secret paths | [Vault decision](../adrs/0001-vault-external-secrets.md), [migration plan](../plans/0001-sealed-secrets-to-vault.md), and the Vault-side plan and path taxonomy in `../homelab-iac/` |
| Upgrade Longhorn (chart minors, volume engines) | [plan 0016](../plans/0016-longhorn-1.9-to-1.13-upgrade.md) and the [restore runbook](../plans/0006-longhorn-restore-runbook.md) |
| Upgrade Vault server version | [plan 0017](../plans/0017-vault-1.18-to-2.0-upgrade.md); image tag pinned in `clusters/titania/apps/vault/helm-release.yaml` |
| Work on local LLM serving | [B60 serving decision](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md), [current served baseline](../plans/0018-b60-model-switch-baseline.md), [LiteLLM model switching](../clusters/titania/apps/litellm/README.md), [evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md), [Swift concurrency/vision baseline](../plans/0010-swift-qwen38-concurrency.md), and [Empero 256K trial](../plans/0011-empero-qwen38-distill-b60-trial.md) |
| Compare local model throughput | [Performance plan](../plans/0007-local-llm-performance-comparison.md), [runner](../automation/llm-performance/README.md), and [standalone HTML report](../automation/llm-performance/report.html) |
| Tune the B60 llama-server flags (autoresearch loop) | [Program](../automation/llm-autoresearch/program.md), [README](../automation/llm-autoresearch/README.md), [plan 0014](../plans/0014-b60-autoresearch.md), [ADR 0006](../adrs/0006-local-b60-autoresearch.md) |
| Run or extend kagent (Kubernetes AI agents behind LiteLLM) | [plan 0019](../plans/0019-kagent-deployment.md), manifests in `clusters/titania/apps/kagent/` and `clusters/titania/apps/kagent-crds/`; the model is chosen in `model-config.yaml` |

`docs/` holds maintained explanations of **how the repository works today**. `adrs/` records **why durable choices were made**. `plans/` holds **temporary work and evidence**, including completed historical plans that are still cited. The manifests, not these documents, define desired cluster state. If a document contradicts the manifests, verify the discrepancy rather than silently choosing one; update the appropriate document in the same change.
