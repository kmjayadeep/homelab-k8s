# ADR 0004: Serve local LLMs with llama.cpp SYCL on the sole B60 behind LiteLLM

- Status: Accepted
- Date: 2026-10-12
- Related plans: [B60 evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md), [Tiel trial](../plans/0008-tiel-coder-b60-trial.md), [performance comparison](../plans/0007-local-llm-performance-comparison.md)
- Supersedes: [ADR 0003](0003-intel-b60-llm-serving.md)
- Amended by: [ADR 0005](0005-nightly-b60-eval-handoff.md) (nightly eval may borrow the B60 02:00–04:00)

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM and 8 vCPUs. Only one inference Deployment can hold the GPU at a time. ADR 0003 kept a Qwen3.8-27B llama.cpp GGUF while Intel llm-scaler-vLLM was evaluated. That evaluation and several later llama.cpp model trials are complete. The detailed evidence is in the related plans and is not repeated here.

Recorded observations:

- **vLLM.** Qwen3.8-27B AWQ failed to start. GPTQ started only after runtime workarounds. The Intel AutoRound Qwen3.6-27B checkpoint served 80K at 0.95 GPU-memory utilization, with about 77.6K KV-token capacity and 95% idle VRAM. 96K/128K exceeded the KV capacity, and there is no MTP support. vLLM also cannot load GGUF, which rules out the Arc-tuned and MTP GGUF artifacts.
- **llama.cpp SYCL.** It served 35B-A3B MoE GGUFs with embedded MTP heads at 128K or more on the same GPU: Qwen3.6-35B-A3B at 128K, Empero at 256K, and Tiel-Coder at 128K with a vision projector. Peak sampled VRAM was 70–87%.
- **Host memory is the binding constraint, not VRAM.** An earlier Coder 128K Q8 trial caused host OOM and lost k3s. The first Tiel 128K pod was evicted for memory pressure.
- **Earlier layers were unused.** KServe/LocalModelCache and a direct vLLM Ingress were unused by the current setup; LiteLLM was the only client of `llm-serving`.

## Decision

- Serve local models as plain Kubernetes Deployments running pinned official `ghcr.io/ggml-org/llama.cpp` SYCL images. Each Deployment has a checksum-verified, pinned Hugging Face GGUF on a node-local PVC.
- Keep exactly one B60 inference Deployment in Git: at present, `intel-llama-tiel-coder-trial` (Tiel-Coder 35B-A3B IQ4_XS, BF16 mmproj, MTP, 128K, one slot, Q8 KV).
- Expose models only through LiteLLM, using the stable `qwen-intel` alias plus a versioned name. `llm-serving` has no Ingress. An ingress NetworkPolicy was proposed but not adopted, so in-cluster pods can still reach the unauthenticated servers.
- Do not keep stopped trial Deployments or caches as standing rollback. Rollback means re-adding manifests from Git history and downloading the pinned artifacts again.
- Remove KServe, the vLLM app and the direct vLLM Ingress.

## Alternatives considered

- **Intel llm-scaler-vLLM.** It has better batching and prefill scheduling, but it hit the 80K KV ceiling, had no MTP, could not use GGUF, and checkpoint compatibility was fragile on this GPU. That is a poor fit for single-user long-context coding. Reconsider it if concurrency matters more than context.
- **KServe InferenceServices with LocalModelCache.** This adds CRDs, controllers and a cache health dependency that blocked unrelated rollouts, with no benefit for a single GPU and a single model.
- **Retaining stopped trials for rollback.** This holds hundreds of GiB of node-local storage, and it advertised dead LiteLLM entries. The artifacts are pinned and can be downloaded again.

## Consequences

- One model is served at a time. Switching models interrupts `qwen-intel` and requires a download when the cache is gone.
- Configured context is not validated capacity. Near-limit context, sustained load and the MTP speedup are untested for Tiel, and host-memory pressure remains the main risk.
- LiteLLM's `STORE_MODEL_IN_DB` can override the Git alias. Check effective routing after every switch (see `clusters/titania/apps/litellm/README.md`).
- Follow-up: rewrite the `.agents/skills/manage-llm-models` skill, which still describes KServe/Envoy, and remove the `kserve-localmodel-huggingface` Vault role in the sibling `homelab-iac` repository.

## Implementation status

Tiel is the Git-declared B60 owner in `clusters/titania/apps/llm-serving-intel-llama/`. The stopped trials, vLLM, KServe and the stale LiteLLM entries were removed in separate pull requests; the NetworkPolicy pull request was closed unmerged. This ADR does not prove live state; check `flux get ks -A` and `kubectl -n llm-serving get deploy,svc,pvc` for live state.
