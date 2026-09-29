# Intel Arc Pro B60 LLM serving evaluation

- Status: Active evaluation
- Date: 2026-09-24
- Hardware: `titania-gpu`, Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM, 8 vCPUs

## Objective

Serve a high-quality coding model through an OpenAI-compatible endpoint with a useful long context. The desired target was more than 30 generated tokens/second (20 minimum) at 64K context, ideally 128K, without a major quality regression.

## Serving architecture

- Intel GPU device plugin advertises `gpu.intel.com/xe: 1`; this is the correct resource for the B60 `xe` driver.
- The selected Intel trial is served by a privileged single-GPU `llm-scaler-vLLM` deployment in `llm-serving`; the previous llama.cpp SYCL deployment is retained at zero replicas for rollback.
- The selected client route is LiteLLM's `qwen-intel` alias; the old direct `intel-llama` Ingress is no longer managed.
- Exactly one inference Deployment may request the B60 at a time. The `intel-vllm` Deployment currently owns it and `intel-llama` is stopped.
- Model caches use node-local `local-path` PVCs. Separate 35–40 GiB PVCs preserve tested artifacts for rollback rather than deleting them.
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

### Retained llama.cpp rollback model

The stopped `intel-llama` rollback manifest selects the pinned Qwen3.6-35B-A3B UD-IQ3_S + MTP GGUF under llama.cpp SYCL, with Q8 KV cache, Flash Attention, one parallel slot, and a **128K configured maximum**. The Qwen3-Coder-30B-A3B Q4_K_M and Qwen3.8-27B GGUF caches remain separate and intact for rollback. The previous 96K Coder measurements below remain historical baselines, not a quality comparison. Qwen3.6's 128K near-limit synthetic-prompt result and memory readings are recorded below; agentic coding quality and MTP-off performance remain untested on the B60.

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

### Qwen3.6-35B-A3B MTP evaluation

[Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) is a distinct 35B-total/3B-active MoE with native MTP support. [Unsloth's MTP GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF) bundles MTP tensors and documents llama.cpp `--spec-type draft-mtp --spec-draft-n-max 2`. At revision `5bc3e238d916f48a861bac2f8a1990a0e9b7e98d`, its UD-IQ4_XS file is 18,209,036,576 bytes (~16.96 GiB; SHA-256 `df27a780435b7b45c2597536112ea3cb091f8544c3d0c3318d9f4258b31f7adf`); UD-IQ3_S is 15,346,432,288 bytes (~14.29 GiB; SHA-256 `ab639a7f330f96c47d3e6c2dd2d6445182e7b763e17e6048dc850a71bbc9f27f`). These are publisher artifacts, not local B60 results. Unsloth estimates ~24 GB total memory for 4-bit MTP; that is **not** a promise of 64K context in 23.91 GiB VRAM. The actual B60 trial below used the smaller IQ3_S artifact, not the 4-bit variant; IQ4_XS and an MTP-off baseline remain untested. The separate cache preserves coder rollback. The `intel-llama-qwen36-a3b-trial` Deployment and separate 40Gi cache PVC use the pinned UD-IQ3_S artifact and draft-MTP width 2. During testing, the coder workload was paused without deleting its cache; the old ingress therefore had no endpoint, and measurements used a localhost port-forward to the trial pod. The installed llama.cpp build 11151 started and served the model with MTP flags at all tested contexts. After testing, the trial was returned to zero replicas and the coder endpoint was temporarily restored; the validated artifact is now selected by the main `intel-llama` Deployment with the same PVC. Neither model cache was removed. **MTP-off was not measured**, so these results do not isolate MTP's speedup or verify acceptance rate. Publisher speed claims on other hardware are not B60 results.

#### Qwen3.6-35B-A3B IQ3_S + MTP B60 trial (2026-09-26)

One llama.cpp/SYCL session, Q8 KV, Flash Attention, MTP draft width 2, 128 generated tokens per test. A synthetic repeated-text prompt was sized near each context limit; TTFT is client-observed streaming latency, throughput comes from llama.cpp timings, and VRAM is sampled every ~8 seconds with node `xpu-smi` (GPU utilization was N/A). Single runs do not establish quality or an SLA. The short 16K test (30 prompt tokens) measured 0.66 s TTFT and 61.8 tok/s decode.

| Configured context | Actual prompt tokens | TTFT | Prefill | Decode | Idle / peak sampled VRAM | Min host available RAM |
|---:|---:|---:|---:|---:|---:|---:|
| 16K | 14,008 | 16.5 s | 853 tok/s | 51.1 tok/s | 15,171 / 15,426 MiB (63.0% peak) | 21,286 MiB |
| 32K | 30,010 | 35.4 s | 848 tok/s | 47.6 tok/s | 15,433 / 15,529 MiB (63.4% peak) | 21,546 MiB |
| 48K | 46,012 | 56.3 s | 818 tok/s | 40.5 tok/s | 15,699 / 15,954 MiB (65.2% peak) | 21,176 MiB |
| 64K | 62,014 | 79.0 s | 786 tok/s | 40.4 tok/s | 15,965 / 16,061 MiB (65.6% peak) | 21,428 MiB |
| 80K | 78,016 | 103.7 s | 753 tok/s | 40.8 tok/s | 16,231 / 16,327 MiB (66.7% peak) | 21,333 MiB |
| 96K | 94,018 | 129.9 s | 724 tok/s | 33.2 tok/s | 16,497 / 16,593 MiB (67.8% peak) | 21,317 MiB |
| 112K | 110,020 | 158.4 s | 695 tok/s | 31.1 tok/s | 16,763 / 17,018 MiB (69.5% peak) | 20,758 MiB |
| 128K | 126,022 | 186.5 s | 677 tok/s | 28.8 tok/s | 17,029 / 17,125 MiB (70.0% peak) | 20,862 MiB |

Each step reached Ready and completed a near-limit prompt. At the end, the B60 node was Ready with MemoryPressure False and the trial pod had zero restarts. This does **not** establish production fitness: IQ3_S quality, coding/tool reliability, MTP-off baseline, broader prompt variability, and sustained/concurrent loads remain untested. The old Coder 128K OOM applied to a different checkpoint; it should not be generalized to this successful 128K Qwen3.6 trial.

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

A 128K maximum for the Qwen3.6 IQ3_S MTP artifact is a workload capacity decision, not a complete node safeguard. The required protections are:

1. Configure kubelet `system-reserved` / `kube-reserved` memory and memory-pressure eviction thresholds on `titania-gpu`.
2. Give node services higher protection than inference and configure cgroup/systemd-oomd pressure handling so the inference workload is terminated before `containerd` or k3s fails.
3. `xpu-smi` is installed on `titania-gpu` and can sample VRAM over SSH; add continuous alerting on GPU memory pressure, memory PSI, OOM events, node NotReady, and k3s-agent failure. GPU compute utilization reported N/A in this trial.
4. Add Proxmox/monitoring health checks for the guest and Kubernetes node, with a documented controlled-reset procedure.
5. Test new model/context combinations through a canary allocation process before changing the production deployment.

Kubernetes GPU device limits allocate a GPU device; they do not impose a strict VRAM cap. Intel GPU/TTM/unified-memory pressure may not be fully contained by normal pod memory limits.

## Pi local-model configuration

After promotion, the public `intel-llama` endpoint and LiteLLM serve the alias `qwen3.6-35b-a3b-intel`. LiteLLM advertises 114,688 input plus 16,384 output tokens (128K total); no Qwen3-Coder-specific pricing was copied to the new model. OpenClaw on `openclaw` uses `litellm/qwen3.6-35b-a3b-intel` as its primary model with 131,072 context and 16,384 max output tokens; its gateway was restarted and was active. Local Pi's `~/.pi/agent/models.json` lists `litellm-intel/qwen3.6-35b-a3b-intel` through LiteLLM with 131,072 context, 16,384 max output tokens and Qwen chat-template thinking support; `settings.json` enables it while retaining the existing cloud default. Pi listed the new model, and a benign chat request to the public llama endpoint succeeded. **OpenClaw and Pi were not end-to-end inference-tested**, and successful configuration/model listing is not proof of coding/tool reliability.

## vLLM comparison and decision

### Qwen3.8 quantized checkpoint startup attempts (2026-09-29)

With the sole B60 released from `intel-llama`, the pinned `intel/llm-scaler-vllm` image failed to start both the existing Qwen3.8-27B AWQ trial and a separate Qwen3.8-27B GPTQ-Int4 attempt. The AWQ trial exited with a quantization validation error (the exact cause was not captured). The GPTQ attempt used `palmfuture/Qwen3.8-27B-GPTQ-Int4` at revision `d85a556c59b2959d083d685a8d1db100f4aeb88d` (20,984,859,696 bytes of safetensors, including MTP), with 8K maximum context, one sequence, 2,048 batched tokens, FP8 KV, 0.90 GPU-memory utilization, and no MTP or remote model code. The first GPTQ startup failed because the image defaulted to BF16, while GPTQ here supports only FP16. After adding `--dtype=float16`, initialization reached a different failure: `AttributeError: 'RowParallelLinear' object has no attribute 'weight'. Did you mean: 'qweight'?`. This matches the GDN ESIMD quantized out-projection incompatibility in [Intel llm-scaler issue #533](https://github.com/intel/llm-scaler/issues/533); [PR #557](https://github.com/intel/llm-scaler/pull/557) proposes a two-site fallback guard but was unmerged when checked. Neither attempt reached readiness or produced TTFT, prefill, decode, or quality measurements. The GPTQ attempt used a separate 35Gi node-local PVC; it was not removed. The live trial Deployment was scaled back to zero to stop its crash loop. Do not interpret these failures as GPU memory limits or model-quality results; diagnose or fix runtime/checkpoint compatibility before another startup attempt.

After these failures, a rerun with `--dtype=float16` and `DISABLE_ESIMD_GDN_OUTPROJ=1` reached Ready for the GPTQ checkpoint, but was superseded before benchmarking. A temporary attempt to patch the same guard in the trial container failed its path assertion and was stopped without running model code; the environment switch worked without that patch.

### Intel AutoRound Qwen3.6-27B live trial (2026-09-29)

The trial selected Intel's `Intel/Qwen3.6-27B-int4-AutoRound` at revision `abc86de19eb1ebbf6a7df4582341325c22ddcb7d` (18,996,705,768 bytes of safetensors) on a separate 35Gi node-local PVC. The pinned llm-scaler image ran with FP16, FP8 E4M3 KV, one sequence, eager mode, no MTP, and `DISABLE_ESIMD_GDN_OUTPROJ=1` plus `DISABLE_ESIMD_PAGE_ATTN=1`. These measurements began as **live-only** Deployment/PVC changes while the two Intel serving Flux Kustomizations were suspended. The later manifest change records the pinned AutoRound PVC and vLLM Deployment as the sole GPU owner, leaving the AWQ PVC and old GGUF caches intact. Before resuming Flux, verify that its Git source contains the matching revision and that no other inference Deployment requests the B60.

Each row is one benign synthetic streaming completions request through localhost port-forward, with 128 output tokens requested but fewer actually generated. TTFT and decode are client-observed; prefill seconds and tokens/second are derived from the server's `vllm:request_prefill_time_seconds_sum` and `vllm:request_prefill_kv_computed_tokens_sum` deltas. The short request's ~8-second prefill includes per-request vLLM overhead and only 14 tokens, so its ~1.7 tok/s ratio is not meaningful throughput. These are single-run timings, not quality tests or SLAs; repeated/varied and coding/tool tests are still needed. 8K ran at 0.90 GPU-memory utilization; 16K/32K/64K at 0.94; 80K at 0.95.

| Max context | Prompt tokens | Output tokens | TTFT | Server prefill | Server prefill tok/s | Client decode tok/s |
|---:|---:|---:|---:|---:|---:|---:|
| 8K short | 14 | 43 | 8.45 s | 8.42 s | 1.7 | 23.9 |
| 8K near-limit | 7,933 | 23 | 6.93 s | 6.91 s | 1,147.8 | 22.7 |
| 16K short | 14 | 43 | 8.33 s | 8.30 s | 1.7 | 23.9 |
| 16K near-limit | 16,123 | 23 | 14.73 s | 14.70 s | 1,096.9 | 22.1 |
| 32K short | 14 | 43 | 8.37 s | 8.34 s | 1.7 | 24.0 |
| 32K near-limit | 32,503 | 23 | 34.03 s | 33.97 s | 956.8 | 21.7 |
| 64K short | 14 | 43 | 8.20 s | 8.19 s | 1.7 | 23.9 |
| 64K near-limit | 65,263 | 23 | 87.41 s | 87.30 s | 747.6 | 20.4 |
| 80K short | 14 | 43 | 8.36 s | 8.34 s | 1.7 | 24.0 |
| 80K near-limit | 81,661 | 23 | 121.38 s | 121.24 s | 673.6 | 19.7 |

vLLM reported 77,608 KV-cache token capacity at 0.94 GPU-memory utilization; 80K startup and near-limit request succeeded at 0.95. Idle VRAM after the 80K request was 23,327 MiB of 24,480 MiB (95.29%). The node remained Ready with MemoryPressure False; no sustained-load or peak-during-request sampling was recorded. 96K and 128K were **not attempted**: they exceed the observed KV capacity, and pushing GPU-memory utilization higher with this single B60 would leave too little safety margin. Compared with the separate Qwen3.6-35B-A3B llama.cpp GGUF synthetic trial above, this 27B AutoRound checkpoint is a different model/quantization and did not demonstrate a quality or speed improvement. The 80K configuration was left running for further evaluation at the operator's request; the accompanying manifest change records it as Git desired state, but pushing alone does not resume the suspended serving Kustomizations. The previous llama.cpp Deployment is stopped but its cache is retained. After enabling `--enable-auto-tool-choice --tool-call-parser=qwen3_coder`, a benign non-executed `lookup_city_timezone` request with `tool_choice: auto` returned HTTP 200, `finish_reason: tool_calls`, the expected function name and a JSON argument object with key `city` (292 prompt / 29 completion tokens, 9.73 seconds client elapsed). One successful tool structure is not a reliability or answer-quality evaluation. The live endpoint is `intel-vllm.llm-serving.svc.cluster.local:8000`; LiteLLM's stable `qwen-intel` alias was changed to route to it while preserving the versioned 35B entry on the stopped llama.cpp service. Both `qwen-intel` and `qwen3.6-27b-intel` returned HTTP 200 through LiteLLM on repeated benign requests; an earlier alias request timed out. The 27B entry reuses the established internal accounting rates, not measured operating cost. Flux application of the committed revision and sustained quality remain to be verified.

Keep the previously serving Qwen3.8 GGUF and its cache available for rollback. The original trial manifest selected a separately pinned Qwen3.8-27B AWQ safetensors checkpoint; the new Git manifest instead records the running Intel AutoRound trial while preserving the old AWQ cache for rollback. This third-party AWQ checkpoint is not weight-identical to the Intel-Arc-tuned GGUF and cannot be assumed to preserve its quality or MTP speedup. A Kustomize dry-run is not an inference test.

A live comparison requires stopping the current owner of the sole B60, interrupting its endpoint, with a rollback path. Measure model load and readiness, host and GPU pressure, short and deep-prompt prefill/decode, and representative coding and tool tasks before claiming comparable quality or a usable 64K context. Increase context incrementally; startup at 64K is not evidence that a near-64K active prompt is safe.

For the fixed B60, the selected Qwen3.6-35B-A3B UD-IQ3_S + MTP completed one 126,022-token prompt at 128K configured context with 28.8 tok/s decode and 17,125 MiB peak sampled VRAM. Qwen3-Coder Q4_K_M (96K) and the Qwen3.8 Intel-tuned MTP variant remain rollback options. This is not a sustained-load or agentic coding SLA; keep host OOM protection and context management on the roadmap.
