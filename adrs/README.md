# Architecture decision records

An ADR captures the context, decision, alternatives, and consequences of a durable choice. It is not a rollout checklist or a claim that the choice has been fully implemented. See [the documentation workflow](../docs/change-workflow.md) and [template](TEMPLATE.md). Allocate the next available ADR number; link a replacement ADR instead of deleting a superseded decision.

| ADR | Status / scope |
| --- | --- |
| [0001: Vault with External Secrets](0001-vault-external-secrets.md) | Accepted; internal Vault TLS remains follow-up work |
| [0002: Local Pi runner for reviewed repository changes](0002-autonomous-repository-agent.md) | Accepted design; verify implementation against the tree before claiming the runner is available |
| [0003: Intel B60 LLM serving](0003-intel-b60-llm-serving.md) | Superseded by ADR 0004 |
| [0004: llama.cpp SYCL on the B60 behind LiteLLM](0004-llamacpp-sycl-b60-behind-litellm.md) | Accepted; one B60 LLM runs at a time, Ornith by default; amended by ADR 0006, ADR 0008 and ADR 0009 |
| [0006: Local B60 autoresearch](0006-local-b60-autoresearch.md) | Accepted; operator-started sessions may tune production llama-server args through LiteLLM |
| [0007: Policy-gated merges and Telegram approval](0007-policy-gated-merges.md) | Accepted 2026-10-28; the bot merges Renovate patch/digest/pin PRs with a green review and asks the operator for everything else; models never merge |
| [0008: Time-share the B60 between the LLM and ComfyUI](0008-comfyui-b60-timeshare.md) | Proposed 2026-11-09; ComfyUI (Intel omni image) and Ornith switch GPU ownership through `replicas` PRs; GPU sharing rejected; switching amended by ADR 0009 |
| [0009: Runtime GPU selection through a portal](0009-gpu-portal-runtime-selection.md) | Proposed 2026-11-09; the GPU portal writes a per-namespace `gpu-active` ConfigMap that Flux substitutes into `replicas`; Git holds the catalog, the cluster holds the active choice |
