# Intel Arc Pro B60 LLM serving evaluation

- Status: Active evaluation
- Date: 2026-09-24
- Hardware: `titania-gpu`, Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM, 8 vCPUs

## Objective

Serve a high-quality coding model through an OpenAI-compatible endpoint with a useful long context. The desired target was more than 30 generated tokens/second (20 minimum) at 64K context, ideally 128K, without a major quality regression.

## Serving architecture

- Intel GPU device plugin advertises `gpu.intel.com/xe: 1`; this is the correct resource for the B60 `xe` driver.
- Models are served by a privileged, single-GPU `llama.cpp` SYCL deployment in `llm-serving`.
- The public endpoint is `https://intel-llama.cosmos.cboxlab.com/v1`.
- Exactly one inference Deployment may request the B60 at a time. The experimental `intel-vllm` Deployment is kept at zero replicas when llama.cpp is active.
- Model caches use node-local `local-path` PVCs. Separate 40 GiB PVCs preserve previous model artifacts for rollback rather than deleting them.
- SmolLM2 KServe InferenceServices and LocalModelCaches were retired in commit `64e51192`.

## Models and measured results

Measurements below used a benign 128-output-token request unless otherwise noted. They are local, single-session decode results, not vendor benchmarks or quality scores. The Qwen3.8 measurements used a **64K configured context**, not a 64K-token active prompt; they do not establish long-context throughput or equivalent quality across quantizations.

| Model/runtime/configuration | Context configuration | Result | Notes |
|---|---:|---:|---|
| Qwen3.8-27B GSQ/RCO IQ3_S, llama.cpp SYCL | 64K, Q8 KV, Flash Attention | 6.73 tok/s | Initial 64K baseline. |
| Qwen3.8-27B IQ3_S plus MTP | 64K | 7.31 tok/s | Small MTP improvement on this artifact. |
| Qwen3.8-27B UD-Q4_K_M | 64K | 12.27 tok/s | Better SYCL performance than IQ3, still below target. |
| Qwen3.8-27B Intel-Arc-tuned IQ3_S + Q4 MTP | 64K, Q8 KV, Flash Attention | **25.93 tok/s** | Best tested Qwen3.8 quality/speed configuration; meets the 20 tok/s minimum on a short request. |
| Qwen3-Coder-30B-A3B Q4_K_M, llama.cpp SYCL | 64K | 48.44 tok/s | Fast short-context decode; 30.5B total MoE parameters, 3.3B active/token. |
| Qwen3-Coder-30B-A3B Q4_K_M, llama.cpp SYCL | ~60K active prompt | 13.10 tok/s decode | 60,015-token prefill was ~721 prompt tok/s. Long active context substantially reduces decode rate. |
| Qwen2.5-14B-Instruct-AWQ, Intel llm-scaler-vLLM | 128K, FP8 KV, YaRN, one sequence | 46.00 tok/s short-context decode | Successfully started after raising GPU memory utilization from 0.90 to 0.95. |
| Qwen2.5-14B-Instruct-AWQ, Intel llm-scaler-vLLM | ~120K active prompt | 18.74 tok/s decode | Accepted 120,045 prompt tokens. Initial uncached 120K prefill was ~546 prompt tok/s. |
| Qwen3.6-27B UD-Q4_K_XL, llama.cpp SYCL | 64K, Q8 KV | 8.51 tok/s | Measured before switching to its MTP artifact. |

### Current selected model

The `intel-llama` manifest selects the previously measured, pinned Qwen3-Coder-30B-A3B-Instruct Q4_K_M GGUF under llama.cpp SYCL, with Q8 KV cache, Flash Attention, one parallel slot, and a **96K configured maximum** after the staged trials below. The previous Qwen3.8-27B Intel-Arc-tuned GGUF remains in its separate cache for rollback. The 48.44 tok/s short-request measurement is not a long-context SLA: at ~60K active prompt tokens decode fell to 13.10 tok/s. The switch prioritizes measured MoE throughput; no head-to-head coding-quality comparison establishes that it matches Qwen3.8.

The separate Qwen3.6-27B MTP cache is retained only for a future controlled comparison; its MTP variant was deployed but not benchmarked. It is **not** a Qwen3.6-35B-A3B cache.

### Qwen3-Coder long-context trial and MTP findings (2026-09-26)

All new tests used one llama.cpp/SYCL session, Q8 KV, Flash Attention, benign synthetic repeated text, and 128 generated tokens. TTFT is client-observed streaming time to first output; prefill/decode are server timings. VRAM is sampled using `ssh ansible@titania-gpu` and `xpu-smi stats -d 0 -j` (memory use, **not** compute utilization; that metric was N/A). Single-run results are not a quality or latency SLA.

| Configured context | Actual prompt tokens | TTFT | Prefill | Decode | Idle / peak sampled VRAM |
|---:|---:|---:|---:|---:|---:|
| 64K | 63,022 | 98.2 s | 643 tok/s | 13.4 tok/s | 21,428 MiB idle; peak not sampled |
| 80K | 78,016 | 137.4 s | 568 tok/s | 10.5 tok/s | 22,230 / 22,557 MiB (92.1% peak) |
| 96K | 94,018 | 187.3 s | 502 tok/s | 9.0 tok/s | 23,094 / 23,156 MiB (94.6% peak) |

Host available RAM stayed above 21 GiB in the 80K and 96K sampling windows. At the end the node was Ready, MemoryPressure False, and the serving pod had zero restarts. **112K was not attempted** because 96K already used 94.6% of VRAM in this limited sample. **128K was not repeated**: a previous 128K Q8 trial with this model caused global host OOM and k3s loss. More context is not proof of a usable near-limit prompt or safe host memory behavior.

The stock Qwen3-Coder-30B-A3B-Instruct GGUF has **no MTP/NextN head**; `--spec-type draft-mtp` cannot add one. A separately loaded draft model would be conventional speculative decoding, not MTP, and is poorly suited to the 96K VRAM headroom. Do not enable MTP flags for this checkpoint.

### Candidate: Qwen3.6-35B-A3B MTP (unmeasured)

[Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) is a distinct 35B-total/3B-active MoE with native MTP support. [Unsloth's MTP GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) bundles MTP tensors and documents llama.cpp `--spec-type draft-mtp --spec-draft-n-max 2`. At revision `5bc3e238d916f48a861bac2f8a1990a0e9b7e98d`, its UD-IQ4_XS file is 18,209,036,576 bytes (~16.96 GiB; SHA-256 `df27a780435b7b45c2597536112ea3cb091f8544c3d0c3318d9f4258b31f7adf`); UD-IQ3_S is 15,346,432,288 bytes (~14.29 GiB; SHA-256 `ab639a7f330f96c47d3e6c2dd2d6445182e7b763e17e6048dc850a71bbc9f27f`). These are publisher artifacts, not local B60 results. Unsloth estimates ~24 GB total memory for 4-bit MTP; that is **not** a promise of 64K context in 23.91 GiB VRAM. Start with a separate cache, shorter context, and the existing single-GPU runtime only after verifying hybrid-model support in the installed llama.cpp build; measure with MTP off and on and retain coder rollback. A separate `intel-llama-qwen36-a3b-trial` Deployment and 40Gi cache PVC are prepared at **zero replicas** in `clusters/titania/apps/llm-serving-intel-llama/` using the pinned UD-IQ3_S artifact, 16K context, and draft-MTP width 2. For the controlled trial, the coder workload is paused without deleting its cache, and this Deployment is set to one replica. The old ingress targets only the paused coder workload, so its endpoint is interrupted during the trial; measurements use a local port-forward to the trial pod. The MTP speed claims are publisher results on different hardware, not B60 measurements. Check installed llama.cpp build 11151 for Qwen3.6-35B-A3B MTP compatibility at startup, monitor `xpu-smi` and host pressure, test short/deep prompts and MTP off/on, and roll back to the existing coder cache on failure.

## Quality evidence

The neuralnoise `harness-bench` blog showed Qwen3.6-27B UD-Q4_K_XL + Pi as the strongest cell in that author's private 16-task sweep (16/16). That is useful evidence that Qwen3.6 and Pi work well together, but the sweep did **not** include Qwen3.8-27B and ran on an M3 Max with 128 GiB unified memory. It is not a basis for preferring Qwen3.6 on the B60.

Qwen's published like-for-like comparison instead favors Qwen3.8-27B for coding and agentic tasks (vendor-reported):

| Benchmark | Qwen3.6-27B | Qwen3.8-27B |
|---|---:|---:|
| LiveCodeBench v6 | 83.9 | **90.3** |
| SWE-bench Pro | 53.5 | **61.7** |
| Terminal-Bench 2.1 | 63.4 | **73.0** |
| NL2Repo-Bench | 36.2 | **42.3** |
| DeepSWE 1.1 | 13.3 | **42.2** |
| QwenSWEBench | 49.3 | **79.0** |

The Qwen3.8 IQ3_S quant publisher also reported 85.71 on LiveCodeBench v6, equal to its cited BF16 result. These are not an independent deployment-specific evaluation, but they support retaining Qwen3.8 for difficult coding and agentic work.

## Context and memory findings

- The Qwen3-Coder-30B-A3B Q4_K_M file is 18.56 GB (about 17.28 GiB). It has 48 layers, four KV heads, and a Q8 KV cache of roughly 3 GiB at 64K.
- Its observed B60 allocation at 64K was about 20 GiB, leaving little runtime headroom.
- `--parallel 1` is intentional. 96K has been exercised with one ~94K prompt but is close to the VRAM limit; 64K had more measured headroom.
- A literal 128K context is not equivalent to merely configuring a 128K maximum. Decode speed with a heavily occupied cache can be much lower than an empty/short prompt benchmark.
- vLLM can improve prefill and concurrent scheduling, but it cannot remove the B60's VRAM and memory-bandwidth limits. It cannot serve GGUF directly.

## 128K failure and recovery

The Qwen3-Coder-30B-A3B 128K Q8 KV trial caused a host-wide failure.

Evidence from the previous guest boot:

- Linux global OOM killed `llama-server`.
- The OOM sequence then killed `containerd` and `containerd-shim`.
- `k3s-agent` failed, Kubernetes reported `titania-gpu` as `Ready=Unknown`, and SSH became unreachable.
- The Intel driver reported `TTM Buffer eviction failed`.
- The VM had ample disk space and, after restart, ample free RAM; this was allocation pressure, not disk exhaustion or a Proxmox hardware failure.

Recovery required a Proxmox `qm reset 100` from `orion`. The safe recovery sequence was:

1. Suspend the llama Flux Kustomization and scale the Deployment to zero.
2. Force-reset the VM and wait for `k3s-agent` and Kubernetes node readiness.
3. Reconcile the Git revision restoring 64K.
4. Resume the Kustomization and verify the Deployment and `/v1/models`.

That Qwen3-Coder 128K Q8 configuration must not be retried on this node without host-level OOM containment and a controlled canary.

## Resilience work still needed

A 96K maximum is a workload capacity decision, not a complete node safeguard. The required protections are:

1. Configure kubelet `system-reserved` / `kube-reserved` memory and memory-pressure eviction thresholds on `titania-gpu`.
2. Give node services higher protection than inference and configure cgroup/systemd-oomd pressure handling so the inference workload is terminated before `containerd` or k3s fails.
3. `xpu-smi` is installed on `titania-gpu` and can sample VRAM over SSH; add continuous alerting on GPU memory pressure, memory PSI, OOM events, node NotReady, and k3s-agent failure. GPU compute utilization reported N/A in this trial.
4. Add Proxmox/monitoring health checks for the guest and Kubernetes node, with a documented controlled-reset procedure.
5. Test new model/context combinations through a canary allocation process before changing the production deployment.

Kubernetes GPU device limits allocate a GPU device; they do not impose a strict VRAM cap. Intel GPU/TTM/unified-memory pressure may not be fully contained by normal pod memory limits.

## Pi local-model configuration

`~/.pi/agent/models.json` was corrected to use the `intel-llama` OpenAI-compatible provider and no longer contains the stale `ollama/qwen` entry. `~/.pi/agent/settings.json` enables that provider model. The configuration should match the currently selected served-model alias and context limit before using Pi against the local endpoint.

## vLLM comparison and decision

Keep the previously serving Qwen3.8 GGUF and its cache available for rollback. The stopped trial manifest under `clusters/titania/apps/llm-serving-intel-vllm/` selects a separately pinned Qwen3.8-27B AWQ safetensors checkpoint, since Intel llm-scaler-vLLM cannot directly reuse the GGUF. It starts at a 16K maximum with one sequence and has **no measured inference results yet**. This third-party AWQ checkpoint is not weight-identical to the Intel-Arc-tuned GGUF and cannot be assumed to preserve its quality or MTP speedup. A Kustomize dry-run is not an inference test.

A live comparison requires stopping the current owner of the sole B60, interrupting its endpoint, with a rollback path. Measure model load and readiness, host and GPU pressure, short and deep-prompt prefill/decode, and representative coding and tool tasks before claiming comparable quality or a usable 64K context. Increase context incrementally; startup at 64K is not evidence that a near-64K active prompt is safe.

For the fixed B60, the selected Qwen3-Coder-30B-A3B Q4_K_M was measured at 48.44 tok/s on a short request and 9.0 tok/s decode with ~94K active prompt tokens at the current 96K setting. The Qwen3.8 Intel-tuned MTP variant remains a rollback option (25.93 tok/s on a short request at 64K configured context). Use RAG, summaries, and context management rather than assuming a literal 128K active context is safe until the node-resilience work is completed.
