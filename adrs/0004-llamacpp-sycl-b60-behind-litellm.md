# ADR 0004: Serve local LLMs with llama.cpp SYCL on the sole B60 behind LiteLLM

- Status: Accepted
- Date: 2026-10-12
- Related plans: [B60 evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md), [Tiel trial](../plans/0008-tiel-coder-b60-trial.md), [performance comparison](../plans/0007-local-llm-performance-comparison.md)
- Supersedes: [ADR 0003](0003-intel-b60-llm-serving.md)
- Amended by: [ADR 0006](0006-local-b60-autoresearch.md) (operator-started autoresearch sessions may tune production llama-server args)

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM and 8 vCPUs. Only one inference Deployment can hold the GPU at a time. ADR 0003 kept a Qwen3.8-27B llama.cpp GGUF while Intel llm-scaler-vLLM was evaluated. That evaluation and several later llama.cpp model trials are complete. The detailed evidence is in the related plans and is not repeated here.

Recorded observations:

- **vLLM.** Qwen3.8-27B AWQ failed to start. GPTQ started only after runtime workarounds. The Intel AutoRound Qwen3.6-27B checkpoint served 80K at 0.95 GPU-memory utilization, with about 77.6K KV-token capacity and 95% idle VRAM. 96K/128K exceeded the KV capacity, and there is no MTP support. vLLM also cannot load GGUF, which rules out the Arc-tuned and MTP GGUF artifacts.
- **llama.cpp SYCL.** It served 35B-A3B MoE GGUFs with embedded MTP heads at 128K or more on the same GPU: Qwen3.6-35B-A3B at 128K, Empero at 256K, and Tiel-Coder at 128K with a vision projector. Peak sampled VRAM was 70–87%.
- **Host memory is the binding constraint, not VRAM.** An earlier Coder 128K Q8 trial caused host OOM and lost k3s. The first Tiel 128K pod was evicted for memory pressure.
- **Earlier layers were unused.** KServe/LocalModelCache and a direct vLLM Ingress were unused by the current setup; LiteLLM was the only client of `llm-serving`.

## Decision

- Serve local models as plain Kubernetes Deployments running pinned official `ghcr.io/ggml-org/llama.cpp` SYCL images. Each Deployment has a checksum-verified, pinned Hugging Face GGUF on a node-local PVC.
- Keep exactly one B60 inference Deployment in Git: at present, `intel-llama-tiel-coder-trial`. Since 2026-10-15 it serves Ornith-1.5-35B-A3B 21G-ICE (gbuzhf; Tiel's imatrix, MTPv2 head, Sharp template) adopted in [plan 0015](../plans/0015-ornith-ice-quant-b60-trial.md). Autoresearch `oct15b` removed MTP (equal decode, +9% long prefill), which freed VRAM to keep the BF16 mmproj on the GPU (peak 93.6%). It previously served Tiel-Coder 35B-A3B IQ4_XS (same weights). Both run 128K, one slot, Q8 KV and MTP.
- Expose models only through LiteLLM, using the stable `qwen-intel` alias plus a versioned name. `llm-serving` has no Ingress. An ingress NetworkPolicy was proposed but not adopted, so in-cluster pods can still reach the unauthenticated servers.
- Do not keep stopped trial Deployments or caches as standing rollback. Rollback means re-adding manifests from Git history and downloading the pinned artifacts again.
- Remove KServe, the vLLM app and the direct vLLM Ingress.

## Alternatives considered

- **Intel llm-scaler-vLLM.** It has better batching and prefill scheduling, but it hit the 80K KV ceiling, had no MTP, could not use GGUF, and checkpoint compatibility was fragile on this GPU. That is a poor fit for single-user long-context coding. Reconsider it if concurrency matters more than context.
- **KServe InferenceServices with LocalModelCache.** This adds CRDs, controllers and a cache health dependency that blocked unrelated rollouts, with no benefit for a single GPU and a single model.
- **Retaining stopped trials for rollback.** This holds hundreds of GiB of node-local storage, and it advertised dead LiteLLM entries. The artifacts are pinned and can be downloaded again.

## Consequences

- One model is served at a time. Switching models interrupts `qwen-intel` and requires a download when the cache is gone.
- Configured context is not validated capacity. On 2026-10-14 a single-request probe through LiteLLM retrieved 3/3 needles at 52K, 105K and 111K prompt tokens (LiteLLM caps input at 114,688). Prefill was 1,116 / 985 / 971 tok/s, but decode fell to 29.8 / 21.8 / 22.7 tok/s with MTP acceptance 0.35–0.40 on prose output, so decode is below 30 tok/s beyond about 50K. VRAM stayed at 86.4% (preallocated). Container anonymous memory was 4.5 GiB at idle and the working set peaked at 9.7 GiB including file cache; the host prompt cache is capped at 4 GiB (`--cache-ram 4096`, default 8 GiB). Sustained multi-request load remains untested, and host memory remains the main risk.
- LiteLLM's `STORE_MODEL_IN_DB` can override the Git alias. Check effective routing after every switch (see `clusters/titania/apps/litellm/README.md`).
- Follow-up: rewrite the `.agents/skills/manage-llm-models` skill, which still describes KServe/Envoy, and remove the `kserve-localmodel-huggingface` Vault role in the sibling `homelab-iac` repository.

## Implementation status

Tiel is the Git-declared B60 owner in `clusters/titania/apps/llm-serving-intel-llama/`. The stopped trials, vLLM, KServe and the stale LiteLLM entries were removed in separate pull requests; the NetworkPolicy pull request was closed unmerged. This ADR does not prove live state; check `flux get ks -A` and `kubectl -n llm-serving get deploy,svc,pvc` for live state.
