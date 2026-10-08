# Plan 0010: Swift Qwen3.8 two-slot vision baseline on B60

- Status: Source prepared; rollout and benchmarks pending approval
- Owner: Homelab operator
- Related: [Swift trial](0009-swift-qwen38-b60-trial.md), [B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md), [performance comparison](0007-local-llm-performance-comparison.md)

## Goal and scope

Prepare the existing `intel-llama-swift-qwen38-trial` GitOps Deployment for two 131,072-token slots: aggregate context 262,144, Q4_0 K/V, continuous batching, batch 512, microbatch 128, MTP off. Preserve the pinned Q4_K_S model, F16 projector, sampling defaults, Flash Attention, full GPU offload, Service, PVC and Recreate strategy. Do not modify stopped rollback workloads or claim coding-quality parity from throughput alone. Q4 KV may affect long-context accuracy even though model weights are unchanged.

Source edits do not deploy the configuration. No push, apply, Flux reconciliation, restart, cache deletion or MTP-on rollout is authorized by this preparation. A Recreate rollout interrupts the endpoint. Obtain explicit approval before rollout and before any destructive rollback/scale action.

## Starting state and read-only evidence (2026-10-08)

- Git and the live Swift slot configuration were 98,304 aggregate tokens, one slot, Q8 K/V, MTP draft width 3, and F16 projector; Recreate was already configured. Flux selects this app directory and health-checks Swift.
- Live pod `intel-llama-swift-qwen38-trial-55457c5c88-xr9v9` on `titania-gpu`: 11 restarts, latest termination `OOMKilled`, exit 137, finished `2026-10-08T02:59:42Z`.
- Node capacity `24534396Ki` (~23.40 GiB), allocatable `21388668Ki` (~20.40 GiB). Node Ready, MemoryPressure False at inspection. Keep the container limit at 16Gi: 32Gi exceeds both capacity and allocatable RAM. A higher limit alone cannot add physical RAM and could weaken host containment. The request stays 8Gi; raising the limit also requires reviewing reservation and other node consumers.
- Point-in-time metrics: container working set 13,684 MiB; node working set 6,831 MiB. These independently reported metrics are not additive physical-memory accounting and are not peak measurements.
- `xpu-smi stats -d 0 -j`: 21,792.86 MiB used, 89.02% of GPU memory under the old configuration. Not a new-config startup or vision peak result.
- Filtered kernel journal since 2026-10-07: 33 lines matching memcg OOM indicators and 22 lines mentioning a killed llama-server; zero `CONSTRAINT_NONE`, killed containerd/k3s, or TTM eviction-failure matches. Counts are matching lines, not distinct incidents. This supports cgroup memory-limit pressure rather than proving GPU exhaustion or host-wide OOM. Request-specific attribution and exact transient peaks remain unknown.
- Available current/previous server logs did not retain startup buffer allocation detail. Cgroup counters were not available at the standard container paths inspected. Exact model, projector, KV, recurrent-state, compute and draft buffer allocations remain **unmeasured**; do not invent these from GGUF file sizes.

## Memory gate: 256K plus vision is not yet verified

The pinned model file is 16,575,850,592 bytes (~15.44 GiB), projector 927,607,232 bytes (~0.86 GiB). File sizes are not device allocations. The earlier Swift plan estimated Q8 KV at ~4 GiB for 128K. Assuming the same cache layout and linear scaling, Q4_0's 18 bytes per 32 values versus Q8_0's 34 gives about **4.24 GiB at 256K**, versus ~3 GiB Q8 at 96K. This is only a sizing hypothesis: hybrid/recurrent buffers, padding, MTP state and vision compute are not covered. The old observed ~21.28 GiB device use leaves limited headroom; startup alone cannot verify loaded two-slot vision capacity.

After approved rollout, extract only allocation categories, device identifiers and byte/MiB totals from startup logs; never print raw logs or request content. Record device model buffers, projector weights/compute, K/V cache, recurrent state, compute/scratch and MTP allocations separately. Verify effective `n_ctx_per_seq=131072`, two slots, Q4 cache and no active speculation. Check that GPU offload did not silently fall back to host RAM. Sample device use and host/container RAM during concurrent near-limit image requests, not just at idle.

Stop testing on OOM, restart, allocation failure, node pressure, eviction, unsafe host headroom or device memory approaching exhaustion. A suggested conservative device gate is at least 1 GiB free during measured peaks; this is not a driver guarantee. Do not deliberately repeat an OOM to obtain a measurement.

If 256K fails, report **actual** allocation totals first. Keep model and projector precision unchanged. If measured KV/slot overhead is the limiting factor, the smallest likely change is a modest aggregate-context reduction while retaining two slots, Q4 KV and vision. Compute a candidate from measured fixed allocation plus KV bytes/token and safety margin, round down to runtime-supported alignment, then validate it. Start with 229,376 aggregate (112K per slot) only if measured headroom supports it; otherwise use 196,608 (96K per slot) or the measured safe bound. Do not claim any of these fit before testing. If vision scratch or host RAM is the limiting factor instead, context reduction may not suffice: consider CPU projector placement only after measuring host headroom and latency, or upgrade node RAM. Dropping model quantization quality or vision is not the default fallback.

## Benchmark steps and gates

1. Obtain rollout approval, preserve the old Git revision for rollback, and verify sole GPU ownership and node health. Validate the source, deploy through reviewed GitOps, confirm Flux applied the expected revision and the new pod is Ready. No direct Pod edits. If unsafe, stop and request approval for rollback to the prior 96K/Q8/one-slot/MTP configuration; preserve the PVC and projector.
2. Treat the supplied **500 tok/s prefill / 30 tok/s decode** as a reference, not a measured baseline for this new configuration. Run a fresh short-request sanity check before long loads. Use a private direct endpoint/approved port-forward to isolate llama.cpp scheduling from gateway queuing; test the versioned LiteLLM route separately.
3. Test all eight baseline cells: one and two simultaneous requests at **64K and 128K per occupied slot**, each text-only and with vision. At two slots and 128K, exercise both slots together. Account for chat-template and image tokens and reserve output space (e.g. 512 tokens); 128K means total prompt + image + generated tokens per slot, not a 131,072-token text prompt plus output. Use server tokenization/usage to report actual depths. Keep aggregate allocation 262,144 for this primary matrix; a smaller-allocation test is a separate configuration.
4. Use fixed benign synthetic text and a generated image with a known expected answer, fixed image resolution, output budget and sampling. Disable request prompt-cache reuse (`cache_prompt: false` where supported), confirm computed prompt-token counts, and avoid concurrent external traffic. Warm up separately; collect at least three repetitions per cell. Do not send private conversations or source code into benchmark logs.
5. For each request capture server computed prompt tokens/time and prefill tok/s, output tokens/time and per-request decode tok/s, client TTFT and monotonic stream-event timestamps. Report median/p95/max inter-token latency, labelling event/chunk latency if multiple tokens arrive per event. Aggregate throughput is total generated tokens divided by the shared measured wall-time window; do not simply sum rates measured over different windows. Record total completion elapsed time as well.
6. Sample GPU used/total memory with xpu-smi at ~1 second intervals where practical; record host available RAM/PSI, container working set and cgroup current/peak memory when available, and kernel/cgroup OOM counters. Record maxima/minima and sampler coverage gaps. Compare restart count and termination reason before/after each cell and monitor Ready/MemoryPressure; zero sampled events alone does not prove no transient spike.
7. Explicit mixed-phase test: let A begin sustained decoding, then submit B's uncached 64K/128K prefill (repeat with vision). Align A's timestamped output with B's prefill interval; report A's before/during/after median/p95/max output gaps and whether A produced any tokens during that interval. Continuous batching enables scheduling but does **not** guarantee non-blocking prefill on this runtime/backend. Microbatch 128 is a tuning hypothesis, not proof of overlap.
8. Only after memory gates pass, obtain approval for a second GitOps rollout adding `--spec-type draft-mtp --spec-draft-n-max 3`. Keep all other settings and test inputs identical; re-run the matrix and mixed-phase test, capturing draft/acceptance counters if available plus extra RAM/VRAM. Compare against MTP-off and the supplied reference. The source intentionally remains MTP-off until this comparison is approved and complete.
9. Compare fixed coding, long-context retrieval, structured tool-call and vision tasks against Q8/one-slot historical configuration using the same prompts, sampling and scoring. Do not execute returned tool calls. Q4 KV and concurrency throughput are not quality evidence; any regression requires reporting and reconsidering KV precision/context trade-offs.

## Results and outcome

| Configuration | 64K / 128K, 1 / 2 requests, text / vision | Prefill / decode / ITL | RAM / VRAM / OOM | Mixed-phase stalls |
| --- | --- | --- | --- | --- |
| Q4 KV, 256K aggregate, MTP off | Not run: requires rollout approval | Unknown | Unknown | Unknown |
| Same, MTP draft width 3 | Not run: requires second rollout approval | Unknown | Unknown | Unknown |

Source-only preparation and read-only OOM investigation are complete. 256K aggregate plus vision fit, concurrency throughput, prefill/decode overlap, coding quality and MTP speedup remain unverified. Record validation results in the change report; update this plan with numeric-only evidence after approved live tests.
