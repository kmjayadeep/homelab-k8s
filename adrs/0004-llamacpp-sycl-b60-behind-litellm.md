# ADR 0004: Serve local LLMs with llama.cpp SYCL on the sole B60 behind LiteLLM

- Status: Accepted
- Date: 2026-10-12
- Related plans: [B60 evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md), [Tiel trial](../plans/0008-tiel-coder-b60-trial.md), [performance comparison](../plans/0007-local-llm-performance-comparison.md)
- Supersedes: [ADR 0003](0003-intel-b60-llm-serving.md)
- Amended by: [ADR 0006](0006-local-b60-autoresearch.md) (operator-started autoresearch sessions may tune production llama-server args); 2026-10-25 amendment below (dense Swift Qwen3.8-27B adopted, Ornith kept as a stopped rollback); 2026-10-28: rolled back to Ornith, Swift manifests and PVCs removed, Deployment renamed `intel-llama-ornith`

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM and 8 vCPUs. Only one inference Deployment can hold the GPU at a time. ADR 0003 kept a Qwen3.8-27B llama.cpp GGUF while Intel llm-scaler-vLLM was evaluated. That evaluation and several later llama.cpp model trials are complete. The detailed evidence is in the related plans and is not repeated here.

Recorded observations:

- **vLLM.** Qwen3.8-27B AWQ failed to start. GPTQ started only after runtime workarounds. The Intel AutoRound Qwen3.6-27B checkpoint served 80K at 0.95 GPU-memory utilization, with about 77.6K KV-token capacity and 95% idle VRAM. 96K/128K exceeded the KV capacity, and there is no MTP support. vLLM also cannot load GGUF, which rules out the Arc-tuned and MTP GGUF artifacts.
- **llama.cpp SYCL.** It served 35B-A3B MoE GGUFs with embedded MTP heads at 128K or more on the same GPU: Qwen3.6-35B-A3B at 128K, Empero at 256K, and Tiel-Coder at 128K with a vision projector. Peak sampled VRAM was 70–87%.
- **Host memory is the binding constraint, not VRAM.** An earlier Coder 128K Q8 trial caused host OOM and lost k3s. The first Tiel 128K pod was evicted for memory pressure.
- **Earlier layers were unused.** KServe/LocalModelCache and a direct vLLM Ingress were unused by the current setup; LiteLLM was the only client of `llm-serving`.

## Decision

- Serve local models as plain Kubernetes Deployments running pinned official `ghcr.io/ggml-org/llama.cpp` SYCL images. Each Deployment has a checksum-verified, pinned Hugging Face GGUF on a node-local PVC.
- Keep exactly one B60 inference Deployment in Git. **Since 2026-10-28 that is `intel-llama-ornith` (renamed from `intel-llama-tiel-coder-trial` the same day; LiteLLM route `ornith-1.5-35b-a3b-intel`, formerly `tiel-coder-35b-a3b-intel`), serving Ornith-1.5-35B-A3B 21G-ICE**, after the operator rolled back from Swift and removed its manifests. From 2026-10-25 to 2026-10-28 it was `intel-llama-swift-qwen38-trial`, serving the dense Swift Qwen3.8-27B Q3_K_M (ukisai; embedded MTP head, draft 3, F16 projector, llama.cpp SYCL b11854, 128K Q8 KV, one slot) adopted by the operator in [plan 0018](../plans/0018-b60-model-switch-baseline.md) at parity quality (43/49 against Ornith's 44–46) while accepting about half of Ornith's decode (43–50 tok/s short, 14.6 at 100K; prefill 407–490). `intel-llama-tiel-coder-trial` first served from 2026-10-15 Ornith-1.5-35B-A3B 21G-ICE (gbuzhf; Tiel's imatrix, MTPv2 head, Sharp template) adopted in [plan 0015](../plans/0015-ornith-ice-quant-b60-trial.md). Autoresearch `oct15b` removed MTP (equal decode, +9% long prefill), which freed VRAM to keep the BF16 mmproj on the GPU (peak 93.6%). It previously served Tiel-Coder 35B-A3B IQ4_XS (same weights). Both ran 128K, one slot and Q8 KV; MTP was removed in `oct15b` and n-gram speculation (`--spec-type ngram-mod`) added in `oct15c`. The served state on 2026-10-24 is recorded in [plan 0018](../plans/0018-b60-model-switch-baseline.md).
- Expose models only through LiteLLM, using the stable `qwen-intel` alias plus a versioned name. `llm-serving` has no Ingress. An ingress NetworkPolicy was proposed but not adopted, so in-cluster pods can still reach the unauthenticated servers.
- Do not keep stopped trial Deployments or caches as standing rollback. Rollback means re-adding manifests from Git history and downloading the pinned artifacts again. A temporary exception from 2026-10-25 to 2026-10-28 kept the Ornith Deployment, Service and PVC at zero replicas while the operator used Swift; on 2026-10-28 the operator rolled back to Ornith and approved removing the Swift Deployment, Service, both PVCs and LiteLLM route, so the rule holds again. Resource names describe the model served, not a trial status (`intel-llama-ornith`, PVC `intel-llama-ornith-models`).
- Remove KServe, the vLLM app and the direct vLLM Ingress.

## Alternatives considered

- **Intel llm-scaler-vLLM.** It has better batching and prefill scheduling, but it hit the 80K KV ceiling, had no MTP, could not use GGUF, and checkpoint compatibility was fragile on this GPU. That is a poor fit for single-user long-context coding. Reconsider it if concurrency matters more than context.
- **KServe InferenceServices with LocalModelCache.** This adds CRDs, controllers and a cache health dependency that blocked unrelated rollouts, with no benefit for a single GPU and a single model.
- **Retaining stopped trials for rollback.** This holds hundreds of GiB of node-local storage, and it advertised dead LiteLLM entries. The artifacts are pinned and can be downloaded again.

## Consequences

- **Parallel slots and 256K were tested on 2026-10-15 and rejected** (PRs #268–#273):
  - **Two independent 128K slots** (`--ctx-size 262144 --parallel 2`) used 24,471 of 24,480 MiB VRAM at idle. Two concurrent ~111K prompts then caused a **host OOM** on `titania-gpu`: the kernel killed `longhorn-manager` and the node was NotReady for about 6 minutes, while the container's anonymous memory was only 1.2 GiB. Exhausted VRAM spills into host RAM outside the pod limit, so treat about 95% VRAM as the practical ceiling on this card.
  - **Two slots sharing the 128K pool** (`--parallel 2 --kv-unified`) were stable at 94.1% peak, but SYCL only time-slices. Short decode went from 62 tok/s for one client to about 29 + 29. Two concurrent ~49K prompts decoded at 5.9 and 13.7 tok/s and finished no sooner than running them back to back. One slot stays, because a single active client keeps more than 30 tok/s.
  - **Dense alternative, measured 2026-10-24/25 (plan 0018):** Swift Qwen3.8-27B with its embedded MTP head reaches 43–50 tok/s short and 14.6–14.8 at 100K on llama.cpp SYCL b11854 (Q3_K_M; Q4_0 and Q4_K_S are 10–20% slower, same quality). The 100K ceiling is the SYCL attention path: the XMX kernels are prefill-only, so decode with a 4-token MTP batch runs on the generic tile kernel over the whole cache. No dense model beats Ornith on speed; the operator adopted Swift for its quality profile and VRAM headroom (idle 82% against 93%), not speed.
- One model is served at a time. Switching models interrupts `qwen-intel` and requires a download when the cache is gone.
- Configured context is not validated capacity. On 2026-10-14 a single-request probe through LiteLLM retrieved 3/3 needles at 52K, 105K and 111K prompt tokens (LiteLLM caps input at 114,688). Prefill was 1,116 / 985 / 971 tok/s, but decode fell to 29.8 / 21.8 / 22.7 tok/s with MTP acceptance 0.35–0.40 on prose output, so decode is below 30 tok/s beyond about 50K. VRAM stayed at 86.4% (preallocated). Container anonymous memory was 4.5 GiB at idle and the working set peaked at 9.7 GiB including file cache; the host prompt cache is capped at 4 GiB (`--cache-ram 4096`, default 8 GiB). Sustained multi-request load remains untested, and host memory remains the main risk.
- LiteLLM's `STORE_MODEL_IN_DB` can override the Git alias. Check effective routing after every switch (see `clusters/titania/apps/litellm/README.md`).
- Follow-up: rewrite the `.agents/skills/manage-llm-models` skill, which still describes KServe/Envoy, and remove the `kserve-localmodel-huggingface` Vault role in the sibling `homelab-iac` repository.

## Implementation status

Since 2026-10-28 `intel-llama-ornith` is the only Deployment in `clusters/titania/apps/llm-serving-intel-llama/` and `qwen-intel` points at `ornith-1.5-35b-a3b-intel`. Swift was the owner from 2026-10-25 to 2026-10-28, and the Tiel-named Ornith Deployment before that; the Swift manifests, its two PVCs and its LiteLLM route were removed on 2026-10-28. The stopped trials, vLLM, KServe and the stale LiteLLM entries were removed in separate pull requests; the NetworkPolicy pull request was closed unmerged. This ADR does not prove live state; check `flux get ks -A` and `kubectl -n llm-serving get deploy,svc,pvc` for live state.
