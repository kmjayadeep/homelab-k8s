# ADR 0003: Retain Qwen3.8-27B llama.cpp serving while evaluating vLLM

- Status: Superseded for model selection by the Qwen3-Coder-30B-A3B deployment; vLLM trial pending
- Date: 2026-09-26

## Deployment update

The selected llama.cpp/SYCL model is now Qwen3-Coder-30B-A3B Q4_K_M at **96K configured context**, following validated 80K and 96K single-session trials. The 96K test used 94,018 prompt tokens: TTFT 187.3 s, prefill 502 tok/s, decode 9.0 tok/s, and peak sampled VRAM 23,156 MiB (94.6%). The 80K test used 78,016 prompt tokens: TTFT 137.4 s, prefill 568 tok/s, decode 10.5 tok/s, and peak 22,557 MiB (92.1%). The node remained Ready with no serving-pod restarts. GPU compute utilization was unavailable from `xpu-smi`; these are memory readings. **112K was not tested** due to low VRAM headroom, and **128K Q8 was not repeated** because this model previously caused host-wide OOM and k3s loss there.

Qwen3-Coder-30B-A3B-Instruct has no native MTP head. `draft-mtp` cannot be enabled by flags alone; a separate draft model is a different mechanism and would use more memory. A future Qwen3.6-35B-A3B MTP GGUF trial is a **new model evaluation**, not an MTP upgrade of this checkpoint. The approved 16K trial uses a separate pinned cache and releases the sole B60 by pausing the coder workload without deleting its PVC; the coder endpoint is interrupted during the trial. Verify installed llama.cpp support, measure MTP on/off and memory pressure, and preserve the coder and Qwen3.8 caches for rollback. This ADR records the earlier Qwen3.8 decision and trial rationale; see [the evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md) for detailed measurements and the proposed candidate.

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM, and 8 vCPUs. The coding workload needs useful long context without sacrificing model quality. Only one inference Deployment can allocate the GPU at a time. At the time of this decision, `intel-llama` served a pinned, Intel-Arc-tuned Qwen3.8-27B IQ3_S GGUF with Q4 MTP through llama.cpp SYCL. Its deployment is configured for one parallel slot, Q8 KV, Flash Attention, and a 131,072-token maximum; configuration alone does not demonstrate performance or safety at that depth.

The local measurements below were recorded in [the B60 evaluation](../plans/0005-intel-arc-b60-llm-serving-evaluation.md). The Qwen3.8 measurements used short, benign 128-output-token requests at a **64K configured context**, not 64K-token active prompts. They are decode throughput, not quality scores or long-context throughput.

| Qwen3.8-27B artifact / llama.cpp SYCL configuration | Short-request decode |
|---|---:|
| GSQ/RCO IQ3_S, Q8 KV, Flash Attention | 6.73 tok/s |
| IQ3_S plus MTP | 7.31 tok/s |
| UD-Q4_K_M | 12.27 tok/s |
| Intel-Arc-tuned IQ3_S + Q4 MTP, Q8 KV, Flash Attention | **25.93 tok/s** |

The last configuration is the tested baseline for a replacement. The figures do not establish equivalent reasoning quality among quantizations. Publisher/vendor benchmarks are not independent tests of this deployment. A separate Qwen3-Coder-30B-A3B test showed decode falling from 48.44 tok/s on a short request to 13.10 tok/s with approximately 60K active prompt tokens; that result is **not** a Qwen3.8 long-context measurement.

A previous 128K Q8 KV trial with Qwen3-Coder-30B-A3B caused global host OOM and loss of the node's k3s services. This is not proof that the current Qwen3.8 128K configuration fails, but it rules out assuming a configured 128K maximum is safe. The evaluation's 64K recommendation predates the currently configured 128K maximum; no comparable Qwen3.8 128K active-context performance or host-pressure result is recorded there.

## Decision

Keep the currently serving Qwen3.8 GGUF and its cache available for rollback. Evaluate Intel llm-scaler-vLLM with a separately pinned Qwen3.8-27B AWQ safetensors checkpoint rather than attempting to use the GGUF directly. The trial manifest in `clusters/titania/apps/llm-serving-intel-vllm/` remains at zero replicas and starts with a 16K maximum; it has **no measured inference results yet**. AWQ from another publisher is not weight-identical to the current tuned GGUF and cannot be assumed to retain its quality or MTP speedup.

A live trial requires stopping the current GPU owner, with endpoint interruption and an explicit rollback path. Measure model load/readiness, host and GPU pressure, short and deep-prompt prefill/decode, and representative coding/tool tasks before claiming comparable quality or a usable 64K context. Increase context incrementally; do not treat a server startup at 64K as proof that a near-64K prompt works safely.

## Consequences

- The measured baseline remains 25.93 tok/s on a short request at 64K **configured** context, not a 64K active-context SLA.
- The vLLM candidate has no measured speed, long-context capacity, or quality on the B60. A successful Kustomize dry-run is not an inference test.
- Preserve the current `intel-llama` workload and cache until a controlled comparison and rollback have been completed.
- Host-level OOM protection remains necessary before attempting large active contexts.
