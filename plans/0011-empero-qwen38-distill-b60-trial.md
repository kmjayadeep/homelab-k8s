# Plan 0011: Empero Qwen3.8-35B-A3B distill 256K vision/MTP trial

- Status: IQ3_M running behind verified public qwen-intel alias; synthetic near-256K text/vision passed, tools failed
- Owner: Homelab operator
- Related: [B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md), [Swift trial](0009-swift-qwen38-b60-trial.md), [abandoned concurrency experiment](0010-swift-qwen38-concurrency.md)

## Goal and scope

Evaluate [Empero's GGUF](https://huggingface.co/empero-ai/Qwen3.8-35B-A3B-Distill-GGUF) with one native 262,144-token slot, embedded MTP, and its matching F16 vision projector on the sole B60. Select IQ4_XS to retain approximately four-bit weight quality while leaving more memory headroom than Q4_K_M. This is a distilled Qwen3.6-architecture MoE, not the dense Swift Qwen3.8-27B checkpoint. Do not assume equivalent coding quality.

Trial files are under `clusters/titania/apps/llm-serving-intel-llama/empero-qwen38-trial/`. The operator approved interrupting Swift and committing/pushing the GPU switch. Commit `4e6bedec` paused Swift through Flux; no serving pods remained before Empero activation. The parent now references the trial, its Deployment requests one replica for the approved IQ3_M retry, and the Flux health check targets Empero. Swift rollback revision is `0a83bbbd`; retain both caches. Activation revision `75bf4a44` was applied by Flux and reached Ready with zero restarts, but idle VRAM failed the safety gate before inference tests.

## Verified artifact evidence

Hugging Face API revision: `b1f9d1dcc3de8aa867669b0ab919384aeeb9b8d5`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `Qwen3.8-35B-A3B-IQ4_XS.gguf` | 19,627,788,160 | `b645af45431ef9b41f43cae51c9323b2d0ca84f23031d483d2105c643ae58d65` |
| `mmproj-Qwen3.8-35B-A3B-F16.gguf` | 899,283,520 | `4381cb5110074396c2c7b39221fffae0c31886aa95b674de8e103d97edf58b94` |

A bounded HTTP range read of the actual IQ4_XS GGUF header confirmed `general.architecture=qwen35moe`, `context_length=262144`, 41 blocks, `nextn_predict_layers=1`, two KV heads, and 256-dimensional K/V. Twenty tensors in `blk.40` include the NextN projections and MTP attention/expert weights; these tensors were Q8_0 or F32 in the header. MTP is present in the artifact, but runtime compatibility, acceptance and speedup are not tested. The model config describes 40 main blocks, ten full-attention layers and thirty linear-attention layers. Vision is inherited from the base; publisher says its distillation was text-only and vision was not evaluated.

The [main model card](https://huggingface.co/empero-ai/Qwen3.8-35B-A3B-Distill) claims native 256K but warns that training used 8,192-token examples and long-context/long-generation behavior may be degraded. Publisher ARC/MMLU results are not coding or 256K-quality evidence. License is Apache-2.0. Sampling is temperature 0.6, top-p 0.95, top-k 20.

## Runtime tuning and memory gate

The operator supplied [the five-flags article](https://omniforge.online/blog/your-local-llm-is-slow-because-of-five-config-flags). Apply its relevant principles, not its GPU-specific performance numbers as facts about Intel SYCL:

- Q8_0 K/V first, not Q4_0: lower-precision cache may hurt precision tasks or incur slower backend kernels. The article's 92% slowdown claim is not a benchmark of this deployment.
- Flash Attention on, full GPU offload, one slot. Aggregate 262,144 thus means one 256K slot, not two 256K sessions.
- Logical batch 2048 for prefill, no explicit physical microbatch override. Logical batch does not eliminate physical microbatch splitting, and a 2–3x speedup is not guaranteed. Inspect effective defaults and scratch allocation before claiming gains.
- MTP draft width 3, matching the previous runtime mechanism. Keep the pinned existing SYCL image until compatibility is tested; do not upgrade it speculatively.

Estimated main KV at 256K: `2 × 10 full-attention layers × 2 KV heads × 256 dimensions × 262144 tokens × (34/32 bytes)` = **2.656 GiB Q8_0**, before padding and MTP cache. IQ4_XS weights (~18.28 GiB file) + projector (~0.84 GiB file) + main KV sum to **~21.78 GiB**. File sizes are not GPU allocations. The B60 has ~23.91 GiB, leaving only ~2.1 GiB for MTP KV, recurrent state, compute/scratch, vision processing and driver headroom. Fit is plausible, **not verified**. Q4_K_M is ~20.22 GiB weights and leaves substantially less headroom.

Retain 16Gi host RAM limit: the node has ~20.4 GiB allocatable RAM, so 32Gi is not supported. A separate 40Gi PVC preserves Swift. The provisioner ConfigMap identifies `/opt/local-path-provisioner`; a pre-rollout SSH check showed 123G free there. Host available RAM was 10,492 MiB while Swift was still running. Never delete older caches to make room without explicit approval.

Extract non-secret allocation totals from startup; verify effective context, one slot, Q8 KV, offload, MTP and projector loading. Sample device memory, host available RAM, container/cgroup memory and OOM/restart metadata throughout tests. Stop on allocation failure, fallback spill/unsafe host pressure, OOM, node pressure, or less than approximately 1 GiB free device memory at sampled peaks. Do not infer 256K capacity from startup alone.

If insufficient memory, report measured model/projector/main KV/MTP/recurrent/compute allocation totals. First reconsider oversized physical scratch if observed; otherwise reduce context modestly with Q8 retained, or test IQ3_M (16,339,529,600 bytes; SHA-256 `0ad7b253ecee6de7b38ecaf82ea5553d302c3f924961b7091b7088cc99a30f95`) if 256K is mandatory and the quality trade-off is explicitly approved. Q4 KV remains a separately measured fallback, not an assumed speed improvement. Do not automatically lower model quality or silently advertise unsafe 256K.

## Steps and gates

1. Obtain explicit approval to interrupt Swift while its sole B60 is reassigned. Commit/push a GitOps revision stopping Swift; verify its pod exits and the GPU is released. Preserve its PVC, model and vision projector. Review unrelated uncommitted benchmark work separately.
2. Check storage and node health. Wire `empero-qwen38-trial` into the parent Kustomization, set its replicas to one, and retarget the existing Flux health check to Empero in a subsequent reviewed revision. Do not add a stopped WaitForFirstConsumer PVC to the waiting Flux app prematurely. Validate build/client dry-run for serving and bootstrap, then push/reconcile only after approval. No direct Pod edits.
3. Confirm exact Flux revision, checksum init exit 0, PVC Bound, Ready, no new restarts, safe GPU/host memory, and effective arguments. Begin with short text, benign vision and structured tool requests; never execute returned tools. Do not alter LiteLLM credentials or secret paths.
4. Use a private direct service port-forward for incremental active-depth tests: 16K, 64K, 128K, 192K, then near 256K only if gates pass. Reserve room for image/template/output tokens. Measure uncached prefill, decode, TTFT, stream-event gap distributions, RAM/VRAM and OOM metadata; include vision near the target depth. No quality or sustained-load claims from single synthetic runs.
5. Add a distinct versioned LiteLLM route only after predictor readiness. Advertise 245,760 input plus 16,384 output if 256K serving is validated; `supports_vision` and function calling require successful checks. Stable alias changes must preserve old versioned routes and align the persisted database-backed alias only when explicitly requested. Leave Swift's versioned route intact for rollback.
6. On failure stop and obtain rollback approval if not already granted. Stop Empero first, verify release, restore Swift replicas and Flux health check in Git, verify readiness and versioned routing before restoring a stable alias. Never delete either PVC.

## IQ3_M retry

The operator approved IQ3_M after the IQ4_XS safety pause. Keep context 262,144, Q8 K/V, MTP width 3, vision projector and batch 2048 unchanged. Use `/models/model-iq3m.gguf` and served alias `empero-qwen3.8-35b-a3b-iq3m-intel`; retain `/models/model.gguf` (IQ4_XS) and Swift's separate PVC. IQ3_M checksum was checked against the pinned publisher `SHA256SUMS`. Both model files plus the projector total approximately 36.87 GB, within the existing 40Gi claim; no deletion or overwrite of the prior model is needed. Retry commit `3e8d9e7e` was pushed and applied by Flux. Checksum init exited 0, predictor Ready with zero restarts. Server `/props` reported one slot and 262,144 context; `/v1/models` reported 262,144 training context and the expected alias. Idle VRAM was 21,257.98 MiB (86.84%), passing the safety gate. Short text and 32×32 red-square vision checks passed. A forced named tool request produced no structured call; a second `tool_choice: required` request also produced none and hit the 512-token cap. No returned tools were executed. Do not advertise function calling.

Single uncached synthetic text retrieval runs through a private direct port-forward:

| Actual prompt tokens | TTFT seconds | Prefill tok/s | Short decode tok/s | Peak sampled VRAM MiB |
| ---: | ---: | ---: | ---: | ---: |
| 16,384 | 15.24 | 1,083.1 | 39.5 | 21,377.50 |
| 65,536 | 61.50 | 1,066.8 | 33.0 | 21,377.50 |
| 131,072 | 147.77 | 887.7 | 27.0 | 21,377.50 |
| 196,608 | 268.86 | 731.7 | 22.9 | 21,377.50 |
| 261,120 | 419.66 | 622.5 | 19.9 | 21,377.50 |

Every run retrieved the benign marker, reported no truncation and zero cached prompt tokens; output was only eight tokens, so decode rates are not sustained-generation benchmarks. MTP counters showed six drafts/six accepted for these short completions; this proves the mechanism ran, not speedup versus MTP-off. Near-limit vision used 260,938 prompt plus two output tokens, correctly returned red, and took 423.55 s total with 619.6 tok/s prefill. Its 125 memory samples peaked at 21,377.62 MiB (87.3269%); minimum sampled host available RAM was 14,950 MiB. The serving pod remained Ready with zero restarts and node Ready without MemoryPressure. Sampling was approximately every three seconds plus SSH overhead; transient peaks may be missed. No coding-quality, varied vision, large-image, 16K output or sustained-load guarantee follows from these single repetitive synthetic runs.

Commit `84dfb670` added the distinct versioned LiteLLM entry with 245,760 input/16,384 output and vision true/tools false. Kustomize/client dry-run and diff checks passed; Flux applied it and HelmRelease 1.90.0 reconciled successfully. The model was visible through the public `https://litellm.cosmos.cboxlab.com/v1/models`; an authenticated benign versioned chat request returned HTTP 200 in 1.13 s (16 input/two output tokens). Authentication stayed inside the existing LiteLLM container; no credentials were displayed or changed. A narrowly filtered `/router/settings` check confirmed persisted `qwen-intel` still targets `swift-qwen3.8-27b-q4ks-intel`. The operator subsequently approved promoting `qwen-intel` to Empero. Promotion commit `20aadb4c` was pushed and applied by Flux; HelmRelease reconciled successfully. Git now targets `empero-qwen3.8-35b-a3b-iq3m-intel`. Authenticated `/config/update` returned HTTP 200 after changing only `qwen-intel` in the complete persisted alias map; all other mappings were preserved. `/router/settings` confirmed the Empero target, `/v1/models` listed `qwen-intel`, and a public alias chat request returned HTTP 200 in 0.84 s (16 input/two output tokens, 12 cached). No credentials were displayed or changed. Swift remains stopped for rollback. Both caches and the unrelated uncommitted benchmark script are preserved.

## Validation and outcome

Standalone trial Kustomize build and Kubernetes client dry-run passed again with the article-derived batch 2048, Q8 K/V, Flash Attention and one-slot settings present. `git diff --check` also passed. The approved activation follows a separate, confirmed Swift-stop revision before assigning the GPU to Empero. Activation revision `75bf4a44` reached Ready with a Bound 40Gi PVC and zero restarts. On 2026-10-08, `xpu-smi` measured idle GPU usage at **24,344.55 MiB (99.45%)**, leaving approximately 135 MiB free: below the 1 GiB safety gate. Host available memory was 21,235 MiB. Pause the trial through GitOps before any requests; Swift remains stopped pending rollback approval. No text, vision, tool or active-depth inference tests were run. Startup allocation categories were not recovered by the initial strict log filter; do not infer their breakdown from file sizes. Native metadata/MTP tensor presence and projector availability are recorded above, while MTP correctness/speedup, active 256K fit, vision quality and coding quality remain unverified. Retain both caches. A smaller weight quant (IQ3_M), lower context, or measured scratch reduction needs review before restarting; do not silently lower the requested context or quantization quality.
