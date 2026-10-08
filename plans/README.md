# Plans and evaluations

Plans are temporary coordination artifacts: steps, gates, rollback instructions, and measurements. They are not authoritative architecture or the live cluster inventory. On completion, preserve cited historical evidence, write durable decisions in an ADR when appropriate, and update current instructions in `docs/`. See [the documentation workflow](../docs/change-workflow.md) and [template](TEMPLATE.md).

| Plan | Recorded state / follow-up |
| --- | --- |
| [0001: Sealed Secrets to Vault](0001-sealed-secrets-to-vault.md) | Completed with follow-up work; decision in [ADR 0001](../adrs/0001-vault-external-secrets.md) |
| [0002: Autonomous repository agent](0002-autonomous-ai-agent.md) | Approved for incremental implementation; decision in [ADR 0002](../adrs/0002-autonomous-repository-agent.md); confirm actual implementation before use |
| [0003: Envoy agent router](0003-envoy-agent-router-llm-gateway.md) | Superseded by plan 0004 |
| [0004: Direct vLLM ingress](0004-retire-envoy-for-direct-vllm-ingress.md) | Completed (per plan); verify current manifests before relying on it |
| [0005: Intel B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md) | Active evaluation; [ADR 0003](../adrs/0003-intel-b60-llm-serving.md) contains decision history |
| [0006: Longhorn restore runbook](0006-longhorn-restore-runbook.md) | Recovery procedures; requires explicit approval before any live or destructive steps |
| [0007: Local LLM performance comparison](0007-local-llm-performance-comparison.md) | Active client-side evaluation with repeatable runner and HTML comparison |
| [0008: Tiel Coder B60 trial](0008-tiel-coder-b60-trial.md) | Completed staged 80K/MTP trial; predictor and cache retained for rollback |
| [0009: Swift Qwen3.8 B60 trial](0009-swift-qwen38-b60-trial.md) | Completed staged 128K/Q4_K_S/MTP trial; Swift left running, earlier caches retained |
| [0010: Swift two-slot vision baseline](0010-swift-qwen38-concurrency.md) | Source prepared for 256K aggregate/Q4 KV/MTP off; OOM investigation recorded, rollout and benchmarks pending approval |
