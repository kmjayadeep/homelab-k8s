# Plan 0007: Reproducible local LLM performance comparisons

- Status: Active evaluation
- Owner: Homelab operator
- Related evaluation: [Intel B60 serving evaluation](0005-intel-arc-b60-llm-serving-evaluation.md)

## Goal and scope

Preserve a small, repeatable client-side performance baseline for the Intel B60's local models and compare future candidates in [one standalone HTML table](../automation/llm-performance/report.html). The [runner and operating instructions](../automation/llm-performance/README.md) and numeric-only [results directory](../automation/llm-performance/results/) live in Git. This plan covers measurement and interpretation, **not** an automatic GPU rollout, secret migration, or quality benchmark.

## Starting state and prerequisites

- On 2026-10-04, the Git manifest for `intel-llama` selected Unsloth Qwen3.6-35B-A3B UD-IQ4_XS + MTP with llama.cpp SYCL, Q8 K/V, Flash Attention, one slot and a configured 128K context. LiteLLM's authenticated `/v1/models` listed `qwen3.6-35b-a3b-intel`. Manifest and model-list evidence do not prove exact live weights/flags, sustained readiness, or GPU headroom.
- The Greatjedi Qwen3.8 trial and vLLM Qwen3.6-27B are declared stopped in Git. Do not turn them on implicitly; the sole B60 cannot serve them concurrently with `intel-llama`. A switch interrupts the currently serving endpoint and requires explicit approval, a cache-preserving rollback plan, and verification of actual Flux/live state.
- `/v1/chat/completions` is reached through `https://litellm.cosmos.cboxlab.com/v1`. The eval credential is read in-process from `pass litellm/evals` and is never stored in Git, a run result or HTML. Never send it to the HTTP redirect target or print it.
- A prior Qwen3-Coder 128K Q8 trial caused global host OOM and k3s loss; the Qwen3.6 128K synthetic-prompt trial is separate evidence, not blanket permission to stress future checkpoints. These measurements stop at about 25K active input tokens.

## Steps and gates

1. Preserve the current measurements in `automation/llm-performance/results/20261004-qwen3.6-35b-a3b-intel.json` and the generated `report.html`. Keep failed runs as failures, never score them as zeros or fabricate missing results for stopped models.
2. For each authorized future model, confirm exact artifact/revision, runtime flags, sole GPU ownership, endpoint/model ID, node readiness, and approval for any endpoint interruption. Do not apply, reconcile, scale, delete or prune from the benchmark script.
3. Run the same short/medium/long synthetic prompts, three sequential streaming requests each, temperature 0, 256 reported output tokens maximum, from the same client/network path. Pin the served **versioned** model name, not a mutable alias. Commit new numeric-only results separately; generate the single-file HTML comparison. Inspect both before staging for credentials or unexpected content.
4. Compare medians and sample counts, not isolated peak rates. Match actual prompt/output token counts and `finish_reason`; report mismatched settings, rate limits, truncation or errors. The short prompt can be warmed/cached. Decode rate is client-observed stream rate; TTFT includes network, queue and prefill. Reasoning tokens can be included in output usage. No engine prefill or quality score is inferred.
5. Stop increasing prompt depth if node pressure, restarts, errors or insufficient headroom are observed. A configured context maximum is not tested active depth. Do not advance beyond this fixed profile without a separate safety plan and approval.

## Recorded outcome (2026-10-04)

| LiteLLM model | Actual prompt tokens | Successful requests | Median client TTFT | Median streamed decode | Median end-to-end |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.6-35b-a3b-intel` | 31 | 3/3 | 0.12 s | 48.94 tok/s | 5.34 s |
| `qwen3.6-35b-a3b-intel` | 8,411 | 3/3 | 13.16 s | 47.33 tok/s | 18.55 s |
| `qwen3.6-35b-a3b-intel` | 25,171 | 3/3 | 40.98 s | 43.67 tok/s | 46.97 s |

All nine requests reported 256 output tokens and `finish_reason=length`; the figures therefore do not promise a complete user-visible answer. No VRAM/host-pressure/cluster telemetry or other model was measured in this suite. Short-prompt TTFT ranged 0.09–0.34 s and may include warm/prefix-cache effects. These results are **not** comparable to historical Qwen3.8 one-off completions (different artifacts, request paths and settings).

## Intel Qwen3.6-27B AutoRound comparison (2026-10-05)

The operator selected the retained `Intel/Qwen3.6-27B-int4-AutoRound` vLLM trial, **not** the Greatjedi Qwen3.8 Intel-Arc-tuned GGUF. This Intel-published quantized checkpoint is the intended 27B candidate; do not infer that AutoRound is a fine-tune or that it will outperform the 35B baseline. The previous 27B trial reached an 80K near-limit request, but was not measured with this repeatable client profile. See [plan 0005](0005-intel-arc-b60-llm-serving-evaluation.md) for trial evidence and memory risks.

Before the switch, Git declared `intel-llama` (35B) at one replica in `llm-serving-intel-llama` and `intel-vllm` (27B) at zero in **a separate** `llm-serving-intel-vllm` Flux Kustomization. The vLLM Deployment selects Intel's revision `abc86de19eb1ebbf6a7df4582341325c22ddcb7d` on its retained node-local PVC, with FP16, FP8 E4M3 KV, one sequence, eager mode, no MTP, 0.95 GPU-memory utilization, and an 80K configured context. Its internal served name is `qwen3.6-27b-intel-trial`; LiteLLM exposes the versioned ID `qwen3.6-27b-intel`. `qwen-intel` remains mapped to the 35B endpoint and should not be moved for this benchmark. Verify actual Flux/live state, cache availability, disk, B60 node readiness, effective LiteLLM routing, and GPU/host headroom before any switch. The prior 80K test left very little idle VRAM headroom; stop on pressure rather than assuming the ~25K profile is harmless.

After explicit operator approval for the interruption and GitOps deployment/push, the switch used **sequential, reviewable** commits (no benchmark-script scaling):

1. Retain the 35B result/report. Validate both serving Kustomize builds and client dry-runs for changed manifests; review the diff for pruning risk. Confirm how each Flux Kustomization will observe the intended revision; no direct live patch or suspended Flux unless separately approved.
2. First GitOps revision: set `intel-llama` to zero while keeping `intel-vllm` at zero. Leave each Flux health check on its own Deployment. Wait for the llama Kustomization to apply that exact revision and for the old pod to exit/release the B60. The 35B endpoint will be unavailable during the switch. **Do not start the 27B GPU claimant until release is verified.**
3. Second GitOps revision: set `intel-vllm` to one, leaving llama at zero. Wait for the vLLM Kustomization to apply the intended revision and Deployment to reach Ready. Verify model/cache readiness using non-secret metadata, node pressure, restarts, and a benign authenticated request to `qwen3.6-27b-intel`. Check for persisted LiteLLM DB routing overrides; Helm values alone do not establish effective routing. If readiness or routing differs, do not run the profile.
4. Monitor B60 VRAM, host available memory, node pressure and pod restarts while running the existing three-depth profile using `--model qwen3.6-27b-intel`; stop before the next depth on pressure, failures, or missing headroom. Generate the report and compare actual token counts, finish reasons, sample counts and medians to the 35B baseline. Keep numeric-only results and report under review; no deeper context stress without separate approval. This compares the deployed Intel AutoRound/vLLM stack with the 35B GGUF/llama.cpp stack, **not** the isolated effects of model size, quantization, or runtime, and is not a coding-quality test.

Rollback requires operator approval for a new live switch: first commit/apply `intel-vllm` replicas zero and verify its pod has exited; then commit/apply `intel-llama` replicas one and verify the old PVC/model is Ready and the versioned 35B LiteLLM request works. Verify the stable alias separately. Keep both caches/PVCs; never delete them as part of this comparison. If the first stage stalls or Flux reports a different revision, stop and diagnose rather than start both GPU owners.

### Recorded outcome (2026-10-05)

The first commit `97d27782` scaled `intel-llama` to zero; Flux applied it and the old pod exited before the second commit `9368eb00` started `intel-vllm`. All three `llm-serving` Flux Kustomizations reported Ready at the second revision. `intel-vllm` was 1/1 Ready with zero restarts, `intel-llama` remained at zero, and a benign request through the versioned LiteLLM ID succeeded. The model was **left running**. These point-in-time checks do not establish future availability.

The [numeric-only result](../automation/llm-performance/results/20261005T170127959036Z-qwen3.6-27b-intel.json) and [HTML report](../automation/llm-performance/report.html) preserve the nine-request comparison:

| LiteLLM model | Actual prompt tokens | Successful requests | Median client TTFT | Median streamed decode | Median end-to-end |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.6-27b-intel` | 31 | 3/3 | 0.13 s | 23.59 tok/s | 10.94 s |
| `qwen3.6-27b-intel` | 8,411 | 3/3 | 6.94 s | 22.69 tok/s | 18.18 s |
| `qwen3.6-27b-intel` | 25,171 | 3/3 | 24.44 s | 21.88 tok/s | 36.10 s |

All nine requests reported 256 output tokens and `finish_reason=length`. The earlier 35B run had higher decode rates (48.94/47.33/43.67 tok/s) but longer medium/long TTFT (13.16/40.98 s); these are client observations from **different** model, runtime and quantization stacks. A gated run checked node Ready, MemoryPressure False, predictor readiness, zero restarts and host-memory utilization (<85%, observed 66–67%) before/after each request. SSH VRAM telemetry was unavailable due to a changed host key; no GPU VRAM or peak host pressure was sampled. Do not infer memory safety at 80K, coding quality, or a persistent performance advantage. The stable `qwen-intel` alias was not moved and still targets the stopped 35B endpoint per Git; verify effective DB routing before using that alias.

## Validation and rollback

Run the Python unit tests and regenerate the HTML from committed data; diff it against the checked-in report and check JSON contains only the allowlisted numeric fields. The runner uses only client requests; no manifest dry-run is needed for this documentation/tooling change. If a live model trial fails, stop only the trial workload **after approval**, restore the previous sole GPU owner and verify the endpoint; do not delete either model cache or PVC. Revert a bad report/result through a reviewed Git change rather than silently rewriting historical evidence.

## Follow-up

Future rows need actual permission to switch the B60 and evidence of live readiness. Consider node telemetry and deeper prompts only after OOM protections are in place; the existing profile is deliberately modest. Compare coding quality separately if model selection needs it. On closing this evaluation, keep the measurements and update the plan index and any lasting decision record.
