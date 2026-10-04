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

## Validation and rollback

Run the Python unit tests and regenerate the HTML from committed data; diff it against the checked-in report and check JSON contains only the allowlisted numeric fields. The runner uses only client requests; no manifest dry-run is needed for this documentation/tooling change. If a live model trial fails, stop only the trial workload **after approval**, restore the previous sole GPU owner and verify the endpoint; do not delete either model cache or PVC. Revert a bad report/result through a reviewed Git change rather than silently rewriting historical evidence.

## Follow-up

Future rows need actual permission to switch the B60 and evidence of live readiness. Consider node telemetry and deeper prompts only after OOM protections are in place; the existing profile is deliberately modest. Compare coding quality separately if model selection needs it. On closing this evaluation, keep the measurements and update the plan index and any lasting decision record.
