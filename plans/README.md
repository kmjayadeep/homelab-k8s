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
| [0008: Tiel Coder B60 trial](0008-tiel-coder-b60-trial.md) | 128K + BF16 projector retained after first-pod memory eviction; LiteLLM vision/limits and public image smoke verified, near-limit/sustained safety untested |
| [0009: Swift Qwen3.8 B60 trial](0009-swift-qwen38-b60-trial.md) | Completed staged 128K/Q4_K_S/MTP trial; Swift left running, earlier caches retained |
| [0010: Swift two-slot vision baseline](0010-swift-qwen38-concurrency.md) | Abandoned for current serving; operator requested rollback to 96K/Q8/one-slot/MTP after prefill regression; incomplete evidence retained |
| [0011: Empero Qwen3.8 distill 256K trial](0011-empero-qwen38-distill-b60-trial.md) | IQ3_M serving verified qwen-intel alias; near-256K synthetic text/vision passed at 87.33% peak sampled VRAM, structured tools failed |
| [0012: Vault internal TLS](0012-vault-internal-tls.md) | Completed 2026-10-13 for TLS; restore and seal/unseal drills deferred |
| [0014: B60 autoresearch](0014-b60-autoresearch.md) | Active: local one-parameter hill-climb through LiteLLM per [ADR 0006](../adrs/0006-local-b60-autoresearch.md); session `oct14` merged (ubatch 1024, reasoning budget 2048) |
| [0015: Ornith ICE quant trial](0015-ornith-ice-quant-b60-trial.md) | Completed 2026-10-15: 21G-ICE adopted (44.5 vs Tiel 43.5; decode 66.8 vs 61.6 tok/s; later tuned in plan 0014); old model files removed |
| [0016: Longhorn 1.9 → 1.13 upgrade](0016-longhorn-1.9-to-1.13-upgrade.md) | Active: 1.9.2 → 1.12.1 done 2026-10-23 with automatic engine upgrade; 1.13 blocked on Kubernetes 1.34; progress table inside the plan |
| [0017: Vault 1.18 → 2.0 upgrade](0017-vault-1.18-to-2.0-upgrade.md) | Active: step 1 (1.18.5) started 2026-10-23, `vault-0` rolled and awaiting manual unseal (Shamir, no auto-unseal); vault-1/2 still 1.18.1 |
| [0018: Swift Qwen3.8-27B dense trial](0018-b60-model-switch-baseline.md) | In progress: phase 1 rejected Swift Q4_K_S + MTP on MoE-level speed gates (43/49, 12.7 tok/s decode at 100K vs Ornith 27.2); phase 2 (2026-10-24 evening) retries with dense-realistic gates: Q4_0, MTP draft length, batch size, lower quant |
