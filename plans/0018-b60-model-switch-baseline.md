# Plan 0018: Trial Swift Qwen3.8-27B (dense) against Ornith-1.5 21G-ICE on the B60

- Status: In progress. Phase 1 (2026-10-24 afternoon): Swift Q4_K_S + MTP **rejected** against MoE-level speed gates; Ornith restored. **Phase 2 reopened the same evening** with dense-realistic gates: Q4_0 weights, MTP draft length, batch size, then a lower quant
- Owner: Homelab operator
- Related ADR: [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md) (one B60 Deployment behind LiteLLM), [ADR 0006](../adrs/0006-local-b60-autoresearch.md) (flag tuning)
- Related plans: [0009](0009-swift-qwen38-b60-trial.md) (first Swift trial, 2026-10-06), [0010](0010-swift-qwen38-concurrency.md) (abandoned two-slot experiment on Swift), [0015](0015-ornith-ice-quant-b60-trial.md) (how 21G-ICE was adopted), [0014](0014-b60-autoresearch.md) (how its flags were tuned)

## Goal and scope

Serve the dense **Swift Qwen3.8-27B** (ukisai, a reasoning-efficient fine-tune of Qwen3.8-27B with embedded MTP) on the single Intel Arc Pro B60 and adopt it only if it beats the current Ornith-1.5 21G-ICE on the fixed evaluator while keeping every hard requirement. The operator chose a dense model deliberately; the MoE notes below are kept as evidence only. This page first pins down **what is served today**, so the trial has a reference to compare against and a known-good config to return to.

Hard requirements, unchanged from plan 0015:

- 128K single-slot context with a vision projector (LiteLLM advertises 114,688 input + 16,384 output)
- at least 30 tok/s decode, at least 500 tok/s prefill
- tool calling through LiteLLM (evaluator tool suite 8/8)
- B60 VRAM below about 95% and at least 3 GiB of host-memory headroom on `titania-gpu` (ADR 0004: VRAM exhaustion spills into host RAM and has taken the node down)

Out of scope: the runtime (llama.cpp SYCL stays), parallel slots, and anything in the litellm or llm-serving manifests other than the model backend and its `model_list` entry.

## Starting state and prerequisites

### Baseline: what is served on 2026-10-24

Everything below was read from the repository and from the live cluster (`titania` context) on 2026-10-24 between 15:05 and 15:20 CEST. Manifests are desired state; the live checks confirm they match.

**Git.** `main` at `f44d4d14`. The serving manifests last changed in `165c7581` (curl digest bump); the last functional change was `d02458a0` (`--spec-type ngram-mod`, autoresearch `oct15c`). Flux Kustomization `llm-serving/llm-serving-intel-llama` is Ready, not suspended, at `main@sha1:f44d4d14`; Kustomization `flux-system/litellm` and HelmRelease `litellm/litellm` (chart `litellm-helm` 1.90.0, release v43) are Ready.

**Model.** Ornith-1.5-35B-A3B, quant `TIEL_Calibrated-MTPv2-21G-ICE` from `gbuzhf/Ornith-1.5-35B-A3B-TIEL-Calibrated-MTPv2-ICE-GGUF` at revision `9991338360005ec7785aefe8c26e9847ced3f1cf` (MIT; Tiel's imatrix, MTPv2 head, Qwen-Sharp v22.4.1 template). Vision projector `mmproj-BF16.gguf` from `peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF-MTP` at `bbe9e566f39e4fc9652ac66b71968289a03c520a`. Both are pinned by sha256 in the init container of `clusters/titania/apps/llm-serving-intel-llama/deployment-tiel-coder-trial.yaml`.

**Runtime.** `ghcr.io/ggml-org/llama.cpp@sha256:86b37d26…` (server-intel, oneAPI 2026.1.1). The live server reports `build_info` `b11515-3d65c90d0`, alias `tiel-coder-35b-a3b-intel`, one slot, `n_ctx` 131072, modalities vision and video, and a chat template that supports tools, parallel tool calls, reasoning effort and preserved reasoning.

**llama-server args** (live Deployment revision 72 matches Git):

| Area | Setting |
| --- | --- |
| Context | `--ctx-size 131072 --parallel 1 --n-gpu-layers 99` |
| KV cache | `--cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on` |
| Host prompt cache | `--cache-ram 4096` |
| Batching | `--batch-size 4096 --ubatch-size 2048` |
| Reasoning | `--reasoning-budget 2048` |
| Sampling | `--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0 --repeat-penalty 1.0` |
| Speculation | `--spec-type ngram-mod` (defaults); MTP off |
| Always | `--metrics --jinja`, `--mmproj` on the GPU (no `--no-mmproj-offload`) |

**Resources.** Requests 4 CPU / 8Gi, limits 6 CPU / 16Gi, `gpu.intel.com/xe: 1`, `/dev/shm` 2Gi. Strategy Recreate. Probes on `/health` (startup up to 15 minutes).

**Live workload.** Pod `intel-llama-tiel-coder-trial-69fdb88d58-nc97s` on `titania-gpu`, started 2026-10-23 07:51 UTC (recreated on the Longhorn upgrade day), 0 restarts, Ready. PVC `intel-llama-tiel-coder-model-cache` (40Gi, `local-path`, bound 18 days) holds only `model-21g-ice.gguf` (20.8 GB) and `mmproj-bf16.gguf` (0.9 GB). The backing disk on `titania-gpu` has about 428 GB free, so a second model file can sit beside the current one during a trial.

**Live memory and power at idle** (`xpu-smi stats -d 0 -j` over SSH, `kubectl top`, `free -m`):

| Reading | Value |
| --- | --- |
| B60 VRAM used | 23,777 MiB, **97.1%** |
| GPU power | 1.5–3 W |
| Pod working set | 6.6 GiB |
| Node memory used / available | 7.5 GiB (35%) / 14.9 GiB |
| Node uptime | 15 days |

The 97.1% idle VRAM is **higher than any value recorded so far** for this config (peak 93.6% in `oct15b`, before n-gram speculation was added) and above the ~95% practical ceiling in ADR 0004. The container's startup log has rotated away, so the allocation breakdown could not be recovered. Whether this is growth after a full-context request (the metrics show `n_tokens_max` 131071) or a change from `ngram-mod` is unknown. Treat it as the first thing to check after any restart of the current config, and as a reason not to add anything else to the GPU. **Checked 2026-10-24 17:55 CEST:** after the rollback restart the same config idled at 22,749 MiB (92.9%), so the 97.1% was growth during 29 hours of uptime, including a full-context request, not the startup footprint. Expect idle VRAM to creep by about 4 points between restarts.

**Live counters since the 2026-10-23 restart** (`/metrics`): 5.9M prompt tokens processed, 178M prompt tokens served from cache, 1.89M tokens generated; n-gram speculation drafted 814K tokens in 12,790 drafts and had 261K accepted (0.32 per drafted token, about 20 per draft). No requests were in flight at the time of reading.

**LiteLLM.** Git maps alias `qwen-intel` to `model_list` entry `tiel-coder-35b-a3b-intel` → `http://intel-llama-tiel-coder-trial.llm-serving:8080`, 114,688 input / 16,384 output tokens. `/v1/models` through the evals key lists both names; `/router/settings` and `/model/info` return 403 for that key, so the **persisted alias was not re-verified** today (see "Alias drift" in `clusters/titania/apps/litellm/README.md`). Other entries on the proxy are cloud models and are not affected.

### Baseline: evaluator results for this exact config

From autoresearch session `oct15c` on 2026-10-15 (`automation/llm-autoresearch/results/oct15c/results.tsv`), commit `d02458a` is the config served today. Its predecessor row (same config without `ngram-mod`) is kept for context. Single runs; quality moves by about ±2 tasks between identical runs.

| Metric | Served config (`ngram-mod`) | Same config, no speculation |
| --- | --- | --- |
| passed / 49 | 44 | 46 |
| `quality_seconds` | 418 | 458 |
| short decode tok/s | 67.9 | 64.8 |
| `ttft_8k_s` (≈13K tokens) | 9.25 | 8.85 |
| `prefill_tps_24k` (≈40K tokens) | 1,372 | 1,375 |
| speculation acceptance | 0.57 | — |
| `decode_tps_100k` | 27.2 | 27.8 |
| `prefill_tps_100k` | 1,177 | 1,179 |
| min free host memory | 16.1 GiB | 16.2 GiB |

Other recorded evidence for the model: two plan 0015 runs on the untuned 21G-ICE scored 45 and 44; tools 8/8 and needles 3/3 in every run; a 111K probe retrieved 3/3 needles at 23.6 tok/s decode and 1,015 tok/s prefill. Decode at about 100K is still below the 30 tok/s target; this is the main known weakness of the current setup, and a candidate that closes it without losing quality is the main thing worth switching for.

A fresh baseline run (`python3 automation/llm-autoresearch/evaluate.py`, about 12 minutes, uses production `qwen-intel`) has not been taken since 2026-10-15. Take one at the start of the trial, with other `qwen-intel` consumers stopped, so the comparison is same-day.

### Dense candidates (research 2026-10-24)

Decode on the B60 is memory-bound: 27B dense at 4-bit measured 21–24 tok/s here (plan 0007), 40 tok/s only with Qwen3.8-27B's MTP head and only at short context (Swift, plan 0009: 40.5 / 28–31 / 23–26 tok/s at 73 / 8.4K / 25K prompt tokens). A community table for the Arc B70 (about 10% faster than the B60) with llama.cpp SYCL gives 14B Q4_K_M ≈ 49 tok/s, 24B ≈ 33, 27B ≈ 21–26, 32B ≈ 23–24; a B580 (same memory bandwidth as the B60) ran Gemma 4 12B Q4_K_M at 40–41 tok/s. So a dense model clears 30 tok/s with margin only at about 14B or below, and a 24B lands on the line at short context. Vendor scores below are self-reported.

| Candidate | Dense size | Vision / ctx | Coding evidence | Expected B60 decode (short) | Fit at 128K | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Gemma 4 12B Unified (Apr 2026, Apache 2.0) | 12B | image+audio, 256K (config 128K) | LiveCodeBench v6 72.0, Tau2 69.0 (card); no SWE-bench published | ≈40 tok/s at Q4_K_M; Q8_0 (12.7 GB) likely ≈30 | easy: 5:1 local:global attention keeps 128K KV small | **Try first.** Only dense option with real speed headroom; unknown agentic quality vs Ornith; Gemma 4 tool-call loops reported in agent harnesses; MTP drafter exists but llama.cpp support is not merged |
| Devstral Small 2 24B (Dec 2025, Apache 2.0) | 24B | image, 256K | SWE-bench Verified 68.0, Terminal-Bench 2 22.5 (card) | ≈29–30 tok/s at Q4_K_M; well under 30 beyond 8K | tight: ~14.3 GB weights + ~10 GB Q8 KV at 128K; needs q4 KV or 64K | Best dense coder, but fails the 30 tok/s and 128K gates on this card; Mistral marks it deprecated |
| Ministral 3 14B (Dec 2025, Apache 2.0) | 13.5B + 0.4B vision | image, 256K | LiveCodeBench 64.6 (reasoning variant); not coding-tuned | ≈44 tok/s at Q4_K_M | likely fine | Fallback if Gemma 4 12B disappoints; expect weaker code quality |
| Qwen3.8-27B (Aug 2026, Apache 2.0) | 27B | image+video, 262K | SWE-bench Pro 61.7, Terminal-Bench 2.1 73.0 (card) | 21–24 tok/s; 40 short / 25 at 25K with MTP (measured) | fine (≈4 GiB KV at 128K) | Best quality, already rejected twice for speed (ADR 0004, plan 0010); revisit only with a faster runtime |
| Gemma 4 31B, GLM-4-32B, Qwen3-32B class | 31–32B | — | — | ≈18–22 tok/s | — | Out on speed |
| Qwen3-14B / SERA-14B, Phi-4 14B | 14B | none | SWE-bench Verified 41.7 (SERA) | ≈45 tok/s | fine | Out: no vision, 2025 quality, Phi-4 weak at tools |

No official Qwen3.8 dense model below 27B exists (the 9B is a third-party distill into Qwen3.5-9B, whose hybrid attention ran at only 23 tok/s on a B60 in one report). GLM has no 2026 small dense release. Mistral Small 4 is MoE.

### Qwen candidates, including variants already tried (research 2026-10-24)

What this repo has already measured on the B60 (all llama.cpp SYCL unless noted; short decode is a request of under 250 prompt tokens):

| Variant | Measured here | Why it was left |
| --- | --- | --- |
| Qwen3.8-27B, GSQ/RCO IQ3_S and UD-Q4_K_M, no MTP (plan 0005) | 6.7 and 12.3 tok/s short at 64K | IQ quants are slow on SYCL; far below target |
| Qwen3.8-27B Greatjedi Intel-Arc IQ3_S + Q4 MTP (plan 0005, ADR 0003) | 25.9 tok/s short | Below 30 even at short context |
| Qwen3.8-27B Intel AutoRound Q4_K_M, no MTP (plan 0007) | 21.3 / 17.5 / 13 tok/s at 73 / 8.4K / 25K | Too slow |
| Qwen3.8-27B Swift Q4_K_S + MTP draft 3, 128K Q8 KV (plan 0009) | 40.5 / 28–31 / 23–26 tok/s at 73 / 8.4K / 25K; KV only ≈4 GiB at 128K | Long-context decode lost to Tiel (39 at 25K); the two-slot experiment (plan 0010) was abandoned for prefill regression, not the model |
| Qwen3.6-27B Intel AutoRound int4 on vLLM-XPU (plan 0007) | 23.6 / 22.7 / 21.9 tok/s; 80K ceiling | Too slow, vLLM retired (ADR 0004) |
| Qwen3.6-35B-A3B UD-IQ3_S + MTP draft 2, 128K Q8 KV (plan 0005, 2026-09-26) | 61.8 short; 51 / 40 / 33 / 28.8 tok/s at 14K / 62K / 94K / 126K; peak VRAM 70% | Replaced by the IQ4_XS quant |
| Qwen3.6-35B-A3B UD-IQ4_XS + MTP draft 2, 128K (plans 0005 and 0007, 2026-10-01 to 10-05) | 48.9 / 47 / 43 tok/s at 31 / 8.4K / 25K on the plan 0007 runner; 29.4 tok/s at 126K; idle VRAM ≈19.8 GB; tool call OK | Superseded by the Qwen3.8 chase and then Tiel's MTP speed, **not by a measured failure**; it predates the 49-task evaluator and all of the plan 0014 tuning |
| Qwen3-Coder-30B-A3B Q4_K_M, 96K (ADR 0003) | 48 short, 13 at 60K; a 128K Q8 run OOMed the host | No MTP head; old generation |
| Qwen2.5-14B AWQ on vLLM (plan 0005) | 46 short, 18.7 at 120K | Old generation; vLLM retired |
| Empero Qwen3.8-35B-A3B distill IQ3_M, 256K (plan 0011) | ran at 87% VRAM near 256K | Structured tool calls failed |
| Ornith-1.5 / Tiel (Qwen3.5+Gemma4 derived MoE) | current, see baseline | — |

Qwen's own like-for-like table (vendor numbers): Qwen3.6-35B-A3B scores SWE-bench Verified 73.4, SWE-bench Pro 49.5, Terminal-Bench 2.0 51.5, LiveCodeBench v6 80.4; Qwen3.8-27B scores SWE-bench Pro 61.7 and Terminal-Bench 2.1 73.0. Ornith's card claims 79 on SWE-bench Verified against Qwen3.6-35B-A3B, while BenchLM's independent aggregate ranks Qwen3.6-35B-A3B above Ornith, with the biggest gap in coding. No official Qwen3.8 MoE below Flash-Next (125B-A6B, too large) exists, and no Qwen3.8 dense below 27B.

**Dense Qwen path (the operator's stated preference).** The only dense Qwen worth the GPU is **Qwen3.8-27B**: Qwen3.5-27B and Qwen3.6-27B are the same size and architecture class with strictly lower scores, Qwen3.5-9B is far weaker and ran at only 23 tok/s on a B60 in one SYCL report (hybrid-attention kernels), and Qwen3-14B is a 2025 text-only model. Qwen3.8-27B is a hybrid dense model: 64 layers in a 3:1 Gated DeltaNet to full-attention layout, 4 KV heads × 256 dims on the 16 full-attention layers, so the 128K Q8 KV cache is only about 4.3 GiB (plan 0009 measured about 4). Vision and video, 262K native, MTP head, Apache 2.0.

Five artifacts were tried here; the best was Swift Q4_K_S with embedded MTP at 40.5 / 28–31 / 23–26 tok/s (73 / 8.4K / 25K prompt tokens). Levers that were **not** combined in any of those runs:

- **Q4_0 weights.** The SYCL backend has a reorder fast path for Q4_0; on an Arc B70, Qwen3.5-27B Q4_0 decoded 27.5 tok/s against 21.4 for Q4_K_M and 16.4 for IQ4_XS. Unsloth ships `Qwen3.8-27B-Q4_0.gguf` (16.1 GB) with `mmproj-BF16/F16` and an `MTP/mtp-Qwen3.8-27B-Q4_0.gguf` draft. Memory is the catch: 16.1 GB weights + about 4.3 GiB KV + 1.6 GiB draft + 0.9 GB projector + compute buffers is at or above the 95% ceiling, so start with the projector on the CPU (`--no-mmproj-offload`) or a smaller ubatch, and fall back to UD-Q4_K_S (15.4 GB).
- **Deeper MTP draft for code.** Field notes on the ggml-org draft head show code generation gaining 2.7–3.4× at draft 3–7 on CUDA, but prose and debugging peaking at draft 3 with acceptance falling to 0.23 at 7. Swift used draft 3. The evaluator's code suite is where a deeper draft would show.
- **`draft-dflash`.** Build b11515 supports it, and ggml-org publishes a DFLASH Q4_0 draft (1.09 GB) for Qwen3.8-27B. Unmeasured anywhere on SYCL.
- **The plan 0014 flags** (batch 4096 / ubatch 2048, `--cache-ram`, reasoning budget) were never applied to a dense 27B here; the AutoRound run used llama.cpp defaults.

Expectation: 45–55 tok/s short and 30–35 at 25K are plausible if Q4_0 and MTP stack; at 100K expect 20–28 tok/s, so the 30 tok/s long-context target will probably still not be met. The decision is whether the quality step (SWE-bench Pro 61.7, Terminal-Bench 73.0, LiveCodeBench 90.3 against Qwen3.6-27B's 53.5 / 63.4 / 83.9) is worth a long-context decode roughly equal to Ornith's 27. Gate it on the 100K probe before moving the alias.

Not worth retrying: any IQ3 or IQ4 quant of a dense model on SYCL, Qwen3.6-27B and Qwen3.8-27B without MTP, Qwen2.5-14B, Qwen3-Coder-30B-A3B, Empero's distill. The MoE Qwen3.6-35B-A3B row above remains the fallback if the operator later reopens MoE.

### Prerequisites

- Candidate chosen and its GGUF (and projector, if vision is kept) pinned by repository revision and sha256. Plan 0015's research from 2026-10-14 lists what was already rejected (Nemotron 3.5 Lightning, Gemma 4 26B-A4B, Laguna XS 2.1, dense 27B models) and why; re-check before repeating it.
- Confirm the candidate's flags exist in build b11515, or pin a newer image in a separate commit first.
- Other `qwen-intel` consumers stopped for the download and eval windows. A first switch cost 13–23 minutes of downtime in plan 0015, almost all download; the Deployment's progress deadline is 10 minutes and it does not roll back on its own.
- Operator approval before any `kubectl delete`, PVC file removal, or Flux suspend outside an autoresearch session.

## Steps and gates

### Candidate artifact

Repository `ukisai/Swift-Qwen3.8-27B-GGUF`, revision `98a6100719e3aafa186041089b71c7b48390dbe1` (last modified 2026-10-01; same revision as plan 0009). Checksums below are the Hugging Face LFS object hashes (`x-linked-etag`), re-read on 2026-10-24; the repo's `SHA256SUMS` lists a different value for the projector and two values for Q4_K_M, so pin the LFS hashes, which are what plan 0009 verified on download.

| File | Bytes | SHA-256 | Use |
| --- | ---: | --- | --- |
| `Swift-Qwen3.8-27B-Q4_K_S.gguf` | 16,575,850,592 | `974812e92df1ce82d91aa7aafa466ef1b707c91fdd3074dfb29438aa59d279d3` | step 1; proven at 128K here |
| `mmproj-Swift-Qwen3.8-27B-F16.gguf` | 927,607,232 | `9f3a5e81486b0c0270eff405b9a22911bf388aa7b58f3788eed9b0774904283b` | step 1 |
| `Swift-Qwen3.8-27B-Q4_0.gguf` | 15,972,755,552 | `2f6c6709ff863e942e9796827f44fe75e0c8431a7b7e09859930762dde9da8e2` | step 6 speed experiment (SYCL Q4_0 fast path) |

MTP tensors are embedded in every tier (Q8_0), so `--spec-type draft-mtp` needs no draft file. License: Swift Open License v1.0, free below US$1M annual revenue; fine for this homelab. The publisher reports a 0.1% long-context divergence in all tiers and has not re-evaluated vision on the GGUFs.

What differs from the 2026-10-06 run of the same file: llama.cpp b11515 instead of the early-October build, the device-plugin pod spec (no `privileged`, no `/dev/dri` hostPath), the 49-task evaluator plus the 100K probe, and the flags learned in plan 0014. Plan 0009 measured 40.5 / 28.3 / 24.9 tok/s at 73 / 8.4K / 25K prompt tokens, idle VRAM 88.5% at 128K without the projector and 89.0% at 96K with it.

### Ordered steps

Each step is one pull request unless noted. Every manifest step runs `kustomize build clusters/titania/apps/llm-serving-intel-llama | kubectl apply --dry-run=client -f -` (and the litellm path when touched) plus `git diff --check` first. Nothing is applied by hand; Flux applies merged `main`. Stop other `qwen-intel` consumers before step 3.

1. **Register the versioned LiteLLM route** (no downtime). Add `model_list` entry `swift-qwen3.8-27b-q4ks-intel` → `http://intel-llama-swift-qwen38-trial.llm-serving.svc.cluster.local:8080/v1`, same accounting rates, `supports_reasoning`, `supports_vision`, `supports_function_calling: true`, 114,688 input + 16,384 output. Leave `qwen-intel` on Tiel. Gate: HelmRelease Ready; `/v1/models` lists the new name.
2. **Pre-download while Ornith keeps serving** (no downtime). Add `pvc-swift-qwen38.yaml` (40Gi, `local-path`) and a one-shot `Job` with the same checksum-verifying curl init script, `nodeSelector`/toleration for `titania-gpu`, no GPU request. The Job binds the `WaitForFirstConsumer` PVC and fills it (about 17.5 GB, 10–20 minutes). Add `deployment-swift-qwen38-trial.yaml` at **`replicas: 0`** in the same PR, modelled on the current Tiel manifest (same image digest `86b37d26…`, resources, probes, `gpu.intel.com/xe: 1`, `/dev/shm` 2Gi) with the Swift init script and these args:
   - `--model /models/model.gguf --mmproj /models/mmproj.gguf --alias swift-qwen3.8-27b-q4ks-intel --host 0.0.0.0 --port 8080 --metrics --jinja`
   - `--ctx-size 131072 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on --parallel 1 --n-gpu-layers 99 --cache-ram 4096`
   - publisher sampling: `--temp 1.0 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0 --repeat-penalty 1.0`
   - `--spec-type draft-mtp --spec-draft-n-max 3`
   - **not yet:** `--batch-size 4096 --ubatch-size 2048` and `--reasoning-budget`; a dense 27B's compute buffers are larger than the MoE's and Swift already idles near 90%, so those are step 6 experiments. The Flux Kustomization has `wait: true` and a 30 m timeout; the Job must complete inside it, otherwise split the Job into its own PR. Gate: Job `Complete` with exit 0, PVC Bound on `titania-gpu`, Ornith untouched.
3. **Hand over the GPU** (about 5 minutes of `qwen-intel` downtime). One PR: Tiel `replicas: 0`, Swift `replicas: 1`, and the Flux `healthChecks` entry in `clusters/titania/bootstrap/apps/llm-serving-intel-llama.yaml` retargeted to `intel-llama-swift-qwen38-trial`. Recreate frees the GPU when the Tiel pod exits; the Swift init only re-verifies checksums. Remove the Job in this PR or the next. Gate: pod Ready, 0 restarts, `/props` shows the alias and `n_ctx` 131072, **idle VRAM below 95%** (`xpu-smi stats -d 0 -j` over SSH), node free memory above 3 GiB, Flux Ready.
4. **Function gate** through the versioned route only: one benign chat, one 32×32 red-square image, one `tools` request (never execute the call). Then `python3 automation/llm-autoresearch/evaluate.py --smoke --model swift-qwen3.8-27b-q4ks-intel`.
5. **Measure.** Two full runs: `evaluate.py --model swift-qwen3.8-27b-q4ks-intel` (about 12 minutes each; the second starts from a warm pod like every Ornith run). Read VRAM again right after the 100K probe, since that is where Ornith reached 97%. Compare with the Ornith rows above. Keep gates:
   - `passed` within 2 of the Ornith reference (44–46) on the mean of the two runs, tools 8/8, needles 3/3
   - `decode_tps_100k` at least 27 (parity) and `prefill_tps_100k` at least 500; 30 remains the goal
   - idle and post-probe VRAM below 95%, `min_free_gib` at least 3
   - a dense 27B that merely ties Ornith on quality still loses on short decode (expect about 40 vs 68 tok/s), so adopt only on a clear quality win or on parity with better long-context decode.
6. **Tune before judging, if step 5 is close.** One idea per rollout, same as plan 0014, each judged by a full run (the `experiment.py` tooling is bound to the Tiel Deployment, so run `evaluate.py --model …` by hand and record rows in this plan): `--spec-draft-n-max 5` (field notes show code gaining up to 3× at 5–7 while prose peaks at 3), `--reasoning-budget 2048`, `--batch-size 4096 --ubatch-size 2048` (watch VRAM), `--temp 0.6`, and finally the **Q4_0 file** (swap the init pin and alias to `…-q40-intel` with its own LiteLLM entry): on SYCL, Q4_0 decoded about 28% faster than Q4_K_M for a 27B in community tables. Stop tuning when two consecutive ideas fail.
7. **Promote or roll back.** Promote: point `router_settings.model_group_alias.qwen-intel` at the Swift entry, verify the persisted alias (`/router/settings` with an admin credential, never printed; align with a complete `/config/update` if stale), send a benign alias request, then record the outcome here and amend ADR 0004. Roll back: reverse step 3 (Swift 0, Tiel 1, health check back), keep the Swift PVC until the operator approves deleting it. Removing the Tiel Deployment, PVC or model files after promotion is a separate, approved PR.

## Validation and rollback

- Dry-runs and `git diff --check` on every PR; Flux revision and Deployment readiness confirmed from the cluster, never inferred from Git.
- Memory abort rule from plan 0014 applies throughout: if `titania-gpu` free memory drops below 2 GiB or VRAM reads 95% or more at idle, stop and roll back before the next request.
- Rollback at any point is step 3 in reverse: Swift to 0 replicas and Tiel to 1 in one PR, health check retargeted. Ornith's files stay on their PVC, so the return is a checksum re-verify and about 5 minutes. The Ornith Deployment at `f44d4d14` (args listed above) is the known-good config.
- Never delete the Swift or Tiel PVCs, model files, or results without explicit approval. `results/` rows from `evaluate.py` runs are copied into this plan's Outcome.

## Outcome

### 2026-10-24 Swift Qwen3.8-27B Q4_K_S + MTP (15:07–17:50 CEST, operator present)

PRs [#364](https://github.com/kmjayadeep/homelab-k8s/pull/364) (route), [#365](https://github.com/kmjayadeep/homelab-k8s/pull/365) (pre-download), [#366](https://github.com/kmjayadeep/homelab-k8s/pull/366) (handover), and the rollback PR linked below. Steps 1–5 ran as planned; step 6 tuning was skipped because the gap is not a tuning gap.

- **Pre-download:** the Job fetched 17.5 GB in about 6 minutes and both checksums verified. Handover downtime for the GPU was 2 minutes to Ready (checksum re-verify only).
- **Load gate:** build b11515, alias and `n_ctx` 131072 confirmed, projector loaded, MTP draft context created, 0 restarts. Idle VRAM **22,828 MiB (93.2%)**; pod working set 10.6 GiB (Ornith: 6.6); host available 20.9 GB.
- **Function gate:** chat, 32×32 red-square image ("Red") and a structured `get_weather` tool call all passed through the versioned route; smoke 4/4, decode 37.4 tok/s, acceptance 0.68. VRAM after the smoke **23,230 MiB (94.9%)**, and it stayed at that value through the full run (53 samples at 20 s).
- **Run 1** (`evaluate.py --model swift-qwen3.8-27b-q4ks-intel`, 27 minutes):

| Metric | Swift run 1 | Ornith reference (oct15c) |
| --- | --- | --- |
| passed / 49 | **43** (code 25/30, homelab 7/8, tools 8/8, needles 3/3) | 44–46 |
| `quality_seconds` | **1,029** | 418–458 |
| short decode | 35.3 (speed suite 28.8) | 67.9 |
| decode at ≈13K / ≈40K | 25.0 / 19.5 | — |
| `ttft_8k_s` | 23.9 | 9.25 |
| `prefill_tps_24k` | 511 | 1,372 |
| MTP acceptance | 0.60 | n-gram 0.57 |
| `decode_tps_100k` | **12.7** | 27.2 |
| `prefill_tps_100k` | **441** | 1,177 |
| `min_free_gib` | 15.8 | 16.1 |

- **Verdict:** DISCARD. Both hard long-context gates failed (decode 12.7 vs the 27 parity gate and the 30 target; prefill 441 vs the 500 minimum), quality did not beat Ornith (43 vs 44–46, inside noise), and total eval time was 2.5× longer. The dense 27B loses about 65% of its decode between short and 100K context on this card, against about 60% for the MoE, from a far lower starting point. Batch/ubatch tuning would help prefill, not a 2× decode gap, so step 6 was skipped and the second run was not taken. A failed code task list is in the run JSON (`runs/20261024T172220.json`, git-ignored).
- **Rollback:** step 3 reversed in one PR (Swift 0, Tiel 1, health check back). Ornith's files were still on their PVC. The Swift Deployment, Service, PVC (17.5 GB on `titania-gpu`) and LiteLLM entry are **retained at zero replicas**; removing them needs operator approval and is a separate PR.
- **What this settles:** on the B60 with llama.cpp SYCL, a dense 27B cannot meet the 128K-context decode requirement even with an embedded MTP head, so the dense path below 27B (Gemma 4 12B, Ministral 3 14B) is the only dense option left, at a quality cost. Any future Qwen3.8-27B attempt would need a different runtime or a Q4_0 build and should be judged on `decode_tps_100k` first.

### Phase 2 (reopened 2026-10-24 evening): dense-realistic gates

The operator reduced the speed expectation: a dense 27B reads about 16 GB of weights per token where the MoE reads about 3 GB, so parity with Ornith's decode is not a fair gate. Swift is kept as the candidate because of its quality, and the question becomes whether a Q4_0 or a lower quant plus MTP tuning gets it to a usable 128K speed.

**Revised gates** (replace the step 5 speed gates; everything else stands):

| Gate | Phase 1 | Phase 2 | Why |
| --- | --- | --- | --- |
| `passed` (mean of 2 runs, final candidate) | 44–46 | at least 44; any single run below 42 discards that config | a dense model only earns its slot on quality parity or better; lower quants must not give that away |
| short decode | 40 goal | at least 35 | Q4_K_S already does 35; the quants below should not be slower |
| `decode_tps_100k` | at least 27 | **at least 18** | about two thirds of Ornith; 128K sessions stay interactive |
| `prefill_tps_100k` | at least 500 | at least 500 (TTFT about 200 s at 100K) | unchanged; prefill is compute bound and dense should manage it |
| VRAM idle and after the probe | below 95% | below 95% | unchanged (ADR 0004) |
| `min_free_gib` | at least 3 | at least 3 | unchanged |

**Method.** One idea per rollout, PR-merged like phase 1 (the autoresearch exception covers only the Tiel Deployment). Each rollout gets a 6-minute speed-only probe first (`speed()` and `deep()` from the fixed evaluator, run from a scratch script, no graded tasks) and a full `evaluate.py --model …` run only when the probe meets the speed gates. Rows below record both. Stop after two consecutive ideas without a gain.

**Ordered ideas.**

1. **Q4_0 weights** (`Swift-Qwen3.8-27B-Q4_0.gguf`, 15,972,755,552 bytes, LFS sha `2f6c6709…`), args otherwise identical to run 1, served under the same LiteLLM route name with alias `swift-qwen3.8-27b-q4ks-intel` kept for now so the LiteLLM entry is untouched; the plan row says which file was loaded. SYCL has a reorder fast path for Q4_0 mat-vec; community tables show about +28% decode over K-quants for a 27B on Arc. Pre-downloaded by `job-swift-qwen38-download-q40.yaml` while Ornith serves (PVC 33.5 GB of 40Gi afterwards).
2. **MTP draft length**: `--spec-draft-n-max 2` and `5`, and one probe with `--spec-type none`, to see how much of the 100K decode loss is MTP verification cost rather than attention. Probe only; the better setting goes into the full run.
3. **`--batch-size 4096 --ubatch-size 2048`** for prefill, only if idle VRAM leaves at least 1 GiB under 95%.
4. **Q3_K_M** (`Swift-Qwen3.8-27B-Q3_K_M.gguf`, 13.62 GB, LFS sha `5ae067582f921ff9a1847ce4aab0b41ecad4c38c386e76fd4714f9a8b98e586e`): about 18% fewer weight bytes than Q4_K_S and roughly 3 GiB of VRAM headroom for idea 3. Needs either approval to delete `model-q4ks.gguf` from the 40Gi PVC or a larger PVC. Quality is the risk, so this one always gets two full runs.

Not retried: IQ3/IQ4 quants (SYCL penalty, plan 0005), Q4_K_M/Q5 (more bytes than Q4_K_S), f16 KV cache (about 8.6 GiB at 128K, does not fit).

**Rows.**

| Rollout | Files / changed flags | short decode | decode 13K / 40K | `decode_tps_100k` | `prefill_tps_24k` / `100k` | accept | idle / peak VRAM | passed | `quality_seconds` |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| run 1 (phase 1) | Q4_K_S, MTP n-max 3 | 35.3 | 25.0 / 19.5 | 12.7 | 511 / 441 | 0.60 | 93.2% / 94.9% | 43/49 | 1,029 |
| probe, [#370](https://github.com/kmjayadeep/homelab-k8s/pull/370) | Q4_0, MTP n-max 3 | 32–36 | 31–33 / 22–24 | **14.2** | 352–368 / 318 | 0.51 | 90.9% / 92.5% | — | — |
| probe, [#371](https://github.com/kmjayadeep/homelab-k8s/pull/371) | Q4_0, `--spec-type none` | 21.1 | — / 10.9 | 6.3 | 364 / 331 | — | 84.8% / 85.6% | — | — |
| probe, [#372](https://github.com/kmjayadeep/homelab-k8s/pull/372) | Q4_0, MTP n-max 5 | 28.1 | — / 21.4 | 11.0 | 349 / 317 | 0.30 | — / 93.7% | — | — |

Probe rows use the evaluator's `speed()` depths (the "24K" depth is 39.7K prompt tokens through LiteLLM) and its 100K `deep()` request; "prefill" is the 40K / 100K value.

What the first three rollouts showed (2026-10-24, 22:40–23:15 CEST):

- **Q4_0 vs Q4_K_S:** decode +12% at 100K (14.2 vs 12.7) and +15% at 40K, short unchanged, idle VRAM 2.3 points lower; but prefill fell 28% (318 vs 441 at 100K). llama.cpp fixed a "prompt-processing regression after Q4_0/Q8_0 weight reorder" (#30374, 2026-10-17) **after** build b11515, which matches this.
- **MTP is what makes a dense 27B usable here.** Without it decode is 21 short and 6.3 at 100K, so one single-token step at 100K costs about 160 ms against 47 ms short: attention over the 100K cache on the SYCL flash-attention path dominates, and the 4-token MTP verification batch amortises it. Draft length 5 loses (acceptance drops to 0.30 and the bigger batch costs more than it returns), so 3 stays.
- **Where the gap is:** the Ornith MoE pays about 2.2 ms per full-attention layer per step at 100K, Swift about 8 ms (32 query heads against 16, and 16 layers against 10). Weight quantisation cannot change that; a faster attention kernel or a newer build might. Build b11854 (2026-10-24) also adds SYCL graph record/replay (#28725), removes host waits in `fattn-mkl` (#30684) and speeds q8 dequant (#30775), so the next rollout is the image, trial Deployment only.
