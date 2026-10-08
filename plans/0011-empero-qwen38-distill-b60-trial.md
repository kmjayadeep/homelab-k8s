# Plan 0011: Empero Qwen3.8-35B-A3B distill 256K vision/MTP trial

- Status: Safety-paused after startup VRAM gate failure; no inference tests run
- Owner: Homelab operator
- Related: [B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md), [Swift trial](0009-swift-qwen38-b60-trial.md), [abandoned concurrency experiment](0010-swift-qwen38-concurrency.md)

## Goal and scope

Evaluate [Empero's GGUF](https://huggingface.co/empero-ai/Qwen3.8-35B-A3B-Distill-GGUF) with one native 262,144-token slot, embedded MTP, and its matching F16 vision projector on the sole B60. Select IQ4_XS to retain approximately four-bit weight quality while leaving more memory headroom than Q4_K_M. This is a distilled Qwen3.6-architecture MoE, not the dense Swift Qwen3.8-27B checkpoint. Do not assume equivalent coding quality.

Trial files are under `clusters/titania/apps/llm-serving-intel-llama/empero-qwen38-trial/`. The operator approved interrupting Swift and committing/pushing the GPU switch. Commit `4e6bedec` paused Swift through Flux; no serving pods remained before Empero activation. The parent now references the trial, its Deployment is safety-paused at zero replicas, and the Flux health check targets Empero. Swift rollback revision is `0a83bbbd`; retain both caches. Activation revision `75bf4a44` was applied by Flux and reached Ready with zero restarts, but idle VRAM failed the safety gate before inference tests.

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

## Validation and outcome

Standalone trial Kustomize build and Kubernetes client dry-run passed again with the article-derived batch 2048, Q8 K/V, Flash Attention and one-slot settings present. `git diff --check` also passed. The approved activation follows a separate, confirmed Swift-stop revision before assigning the GPU to Empero. Activation revision `75bf4a44` reached Ready with a Bound 40Gi PVC and zero restarts. On 2026-10-08, `xpu-smi` measured idle GPU usage at **24,344.55 MiB (99.45%)**, leaving approximately 135 MiB free: below the 1 GiB safety gate. Host available memory was 21,235 MiB. Pause the trial through GitOps before any requests; Swift remains stopped pending rollback approval. No text, vision, tool or active-depth inference tests were run. Startup allocation categories were not recovered by the initial strict log filter; do not infer their breakdown from file sizes. Native metadata/MTP tensor presence and projector availability are recorded above, while MTP correctness/speedup, active 256K fit, vision quality and coding quality remain unverified. Retain both caches. A smaller weight quant (IQ3_M), lower context, or measured scratch reduction needs review before restarting; do not silently lower the requested context or quantization quality.
