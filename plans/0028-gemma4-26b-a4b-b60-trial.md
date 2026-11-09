# Plan 0028: Trial Gemma 4 26B-A4B (QAT Q4_0 + MTP, vision) on the B60

- Status: Draft 2026-11-08; manifests in this PR, no measurements yet
- Owner: Homelab operator
- Related ADR: [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md) (one B60 Deployment behind LiteLLM), [ADR 0006](../adrs/0006-local-b60-autoresearch.md) (flag tuning)
- Related plans: [0018](0018-b60-model-switch-baseline.md) (trial method and Ornith baseline numbers), [0025](0025-nemotron-lightning-b60-trial.md) (previous trial, same manifest shape and gates)

## Goal and scope

Serve **Google Gemma 4 26B-A4B** (official QAT Q4_0 GGUF with its vision projector, plus Google's first-party MTP draft head packaged as GGUF) on the single Intel Arc Pro B60 and measure it with the fixed evaluator against the Ornith-1.5 21G-ICE baseline.

Why this model, after a research pass on 2026-11-08 over the ≤24 GB MoE class: Ornith remains the strongest on published coding and agentic numbers, and nothing newer clearly beats it (Flint 40B-A2.5B: text-only, below Ornith on SWE-bench/Terminal-Bench, 4-bit does not fit; Qwen3.8-Flash-Next via Strata: needs a second card). Gemma 4 26B-A4B is the one candidate that keeps vision **and** fits 128K with real VRAM headroom: the independent B60 writeup ([srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks/blob/main/models/production/gemma-4-26b-a4b.md)) measured 19.9 GiB loaded at 131K Q8 KV with the drafter (Ornith sits at 92.9–97%), 62.8 tok/s decode at 97% MTP acceptance, and ~1,600 tok/s prefill at 12K. The expected result is **parity or slightly worse quality for a large host-OOM safety margin**; the quality gate is the one most likely to fail (published SWE-bench Verified about 66–68 against Ornith's 79; weaker JSON/tool adherence in third-party tests).

Out of scope: the runtime (llama.cpp SYCL, same b11515 image), parallel slots, 256K context, anything in litellm beyond the versioned `model_list` entry, and an `experiment.py` target (add one per ADR 0006 only if the quality gate passes and tuning is worth a session).

## Starting state and prerequisites

Baseline: Ornith-1.5 21G-ICE as recorded in plan 0018 (`oct15c`) and reconfirmed in plan 0025: 44–46/49, short decode 68 tok/s, 27.2 tok/s and 1,177 tok/s prefill at 100K, idle VRAM 92.9% rising to 97% over uptime.

Field measurements for Gemma 4 26B-A4B on a B60 (llama.cpp SYCL b10433–b10566, Q8 KV, `--parallel 1`):

| Metric | Field value |
| --- | ---: |
| Decode with MTP, greedy | 62.84 tok/s at 97.2% acceptance |
| n-max sweep (harness sampling) | 3 → 59.5, 5 → 65.3, 7 → 61.9, 8 → 44.1 tok/s |
| Prefill | 1,592 tok/s at 4K, ~1,633 at 12K |
| VRAM loaded at 131K, Q8 KV, drafter | 19.9 GiB (17.85 GiB without mmproj in the sweep) |
| Cold load | 23 s |

Artifacts, pinned by repo revision and Hugging Face LFS hash (read from the file pages on 2026-11-08):

| File | Source | Size |
| --- | --- | ---: |
| `gemma-4-26B_q4_0-it.gguf` | `google/gemma-4-26B-A4B-it-qat-q4_0-gguf` @ `d1c082be` | 14.4 GB |
| `gemma-4-26B-it-mmproj.gguf` | same repo and revision | 1.19 GB |
| `gemma-4-26B-A4B-it-qat-assistant-MTP-Q8_0.gguf` | `Janvitos/gemma-4-26B-A4B-it-qat-assistant-MTP-Q8_0-GGUF` @ `f18d498f` | 462 MB |

Known risks going in:

- **Quality quant.** Unsloth reports that llama.cpp's Q4_0 conversion of Google's QAT checkpoint loses accuracy and prefers its own `UD-Q4_K_XL` QAT GGUF. The field writeup chose QAT Q4_0 for the SYCL XMX path (+10% decode over Q4_K_M). If quality lands 1–2 tasks short, `unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL` is the first alternative (about 16 GB, fits).
- **Thinking parser.** The field config ran `--reasoning off` because the thinking parser returned HTTP 500 on b10xxx. This trial keeps `--reasoning-budget 2048` for parity with Ornith; if 500s appear, switch to `--reasoning off` and record it.
- **Chat template.** `--jinja` is mandatory for tool calls. The GGUF-embedded template is used first; Google's updated official template is the fallback if tool loops appear at long context.
- `qwen-intel` and `sensitive` keep pointing at `ornith-1.5-35b-a3b-intel`, which is at 0 replicas during the trial, so **Open WebUI and kagent's local model are down for the trial**. `local-first` falls back to DeepSeek as designed. Flip the alias only on promotion (plan 0018 step 7, including the alias-drift check).
- Download: about 16 GB, roughly 3–4 minutes at the 83 MB/s seen in plan 0018, plus load.

## Steps and gates

1. **This PR** merges: `pvc-gemma4.yaml` (25 Gi), `deployment-gemma4.yaml` (1 replica), `service-gemma4.yaml`; `deployment-ornith.yaml` to 0 replicas; Flux health check retargeted; LiteLLM route `gemma-4-26b-a4b-intel` (`supports_vision: true`). Gate: pod Ready, 0 restarts, `/props` shows the alias and `n_ctx` 131072, **idle VRAM below 90%** (`xpu-smi stats -d 0 -j`; the field value predicts about 83%), node free memory above 3 GiB, Flux `llm-serving-intel-llama` and `litellm` Ready, `/v1/models` lists the new route.
2. **Checksums**: the init container log shows `OK` for all three files. A mismatch means re-read the hash on Hugging Face and fix the manifest; never remove the check.
3. **Function gate** through the versioned route: one benign chat, one `tools` request (never execute the call), one benign image (vision), then `python3 automation/llm-autoresearch/evaluate.py --smoke --model gemma-4-26b-a4b-intel`. If the thinking parser returns 500, set `--reasoning off`, re-roll and note it in the Outcome.
4. **Measure.** Two full runs of `evaluate.py --model gemma-4-26b-a4b-intel`; read VRAM right after the 100K probe. Record rows in the Outcome table.
5. **Tune only if the quality gate passes.** Add a `gemma4` target to `experiment.py` (ADR 0006 amendment, as plan 0025 did) and run a session. First ideas: Gemma's published sampling (`--temp 1.0 --top-k 64`), `--spec-draft-n-max 3` and `7`, `--batch-size 4096`, the Unsloth `UD-Q4_K_XL` QAT quant as a model swap (a new plan step, not a flag).
6. **Promote or remove.** Promotion follows plan 0018 step 7 (alias move, `/router/settings` check, ADR 0004 amendment). Removal reverses this PR; Ornith's files are still on `intel-llama-ornith-models`, so the return is a checksum re-verify. Deleting the Gemma PVC (about 16 GB on `titania-gpu`) needs explicit approval.

Gates, taken from plan 0025:

| Gate | Target | Ornith reference |
| --- | ---: | ---: |
| `passed` (mean of 2 runs) | within 2 of Ornith | 44–46 |
| tools / needles | 8/8, 3/3 | 8/8, 3/3 |
| vision smoke | 1 benign image answered | passes |
| short decode | at least 30 (goal: at or above 68) | 68 |
| `decode_tps_100k` | at least 30 (the gate Ornith misses) | 27.2 |
| `prefill_tps_100k` | at least 500 | 1,177 |
| VRAM idle and after the probe | below 90% (the point of this trial) | 92.9% / 97% |
| `min_free_gib` | at least 3 | 16.1 |
| `quality_seconds` | within 1.3× Ornith | 420–460 s |

## Validation and rollback

- `kustomize build clusters/titania/apps/llm-serving-intel-llama` and `clusters/titania/apps/litellm` plus `git diff --check` on the PR; `kubectl --dry-run=client` as required by AGENTS.md. Flux state is confirmed from the cluster, never inferred from Git.
- Memory abort rule from plan 0014: free memory below 2 GiB or VRAM at or above 95% at idle means stop and roll back before the next request.
- Rollback: Ornith `replicas: 1`, Gemma `replicas: 0`, Flux health check back to `intel-llama-ornith`, in one PR. Nothing is deleted without approval.

## Outcome

| Run | Config | short decode | decode 13K / 40K | `decode_tps_100k` | `prefill_tps_24k` / `100k` | accept | idle / peak VRAM | passed | `quality_seconds` |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| | | | | | | | | | |

To be filled after step 4.
