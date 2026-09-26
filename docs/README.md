# Documentation map

Start with [the repository overview](../README.md). Agents must also follow [AGENTS.md](../AGENTS.md); it contains the safety and validation rules, not just navigation.

| Need | Read |
| --- | --- |
| Find the deployment path and ownership of a manifest | [Repository map](repository-map.md) |
| Make or review a change safely | [Change workflow](change-workflow.md) |
| Understand an enduring architectural choice | [ADR index](../adrs/README.md) |
| Track a rollout, investigation, or evaluation | [Plan index](../plans/README.md) |
| Change Vault/ESO resources or secret paths | [Vault decision](../adrs/0001-vault-external-secrets.md), [migration plan](../plans/0001-sealed-secrets-to-vault.md), and the Vault-side plan and path taxonomy in `../homelab-iac/` |
| Work on local LLM serving | [B60 decision](../adrs/0003-intel-b60-llm-serving.md) and [evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md) |

`docs/` holds maintained explanations of **how the repository works today**. `adrs/` records **why durable choices were made**. `plans/` holds **temporary work and evidence**, including completed historical plans that are still cited. The manifests, not these documents, define desired cluster state. If a document contradicts the manifests, verify the discrepancy rather than silently choosing one; update the appropriate document in the same change.
