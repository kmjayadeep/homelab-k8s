# Architecture decision records

An ADR captures the context, decision, alternatives, and consequences of a durable choice. It is not a rollout checklist or a claim that the choice has been fully implemented. See [the documentation workflow](../docs/change-workflow.md) and [template](TEMPLATE.md). Allocate the next available ADR number; link a replacement ADR instead of deleting a superseded decision.

| ADR | Status / scope |
| --- | --- |
| [0001: Vault with External Secrets](0001-vault-external-secrets.md) | Accepted; internal Vault TLS remains follow-up work |
| [0002: Local Pi runner for reviewed repository changes](0002-autonomous-repository-agent.md) | Accepted design; verify implementation against the tree before claiming the runner is available |
| [0003: Intel B60 LLM serving](0003-intel-b60-llm-serving.md) | Superseded by ADR 0004 |
| [0004: llama.cpp SYCL on the B60 behind LiteLLM](0004-llamacpp-sycl-b60-behind-litellm.md) | Accepted; Tiel is the sole B60 workload; nightly eval handoff amended by ADR 0005 |
| [0005: Nightly B60 eval handoff](0005-nightly-b60-eval-handoff.md) | Accepted; amends ADR 0004 with a nightly 02:00–04:00 Flux-suspend GPU handoff to the private eval runner |
