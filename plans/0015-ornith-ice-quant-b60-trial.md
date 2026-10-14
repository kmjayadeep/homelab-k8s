# Plan 0015: Trial higher-fidelity quants of the production B60 model

- Status: Draft; nothing downloaded or deployed
- Owner: Homelab operator
- Related ADR: [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md)

## Goal and scope

Find out whether a more accurate 4-bit quant of the **same weights** beats the current Tiel-Coder `UD-IQ4_XS` on the B60. Adopt it only if quality is at least equal and every hard requirement still holds:

- 128K single-slot context with the vision projector
- at least 30 tok/s decode
- at least 500 tok/s prefill

Out of scope: other model families, other runtimes, the image, resources, parallel slots, and chat-template changes. Each of those would be a separate trial.

### Why the same weights

Tiel-Coder is not a fine-tune. Its card says it is "[Ornith-1.5-35B-A3B](https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B) re-quantized dynamically with our own imatrix and carrying the Sharp chat template" ([card](https://huggingface.co/peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF-MTP)).

Research on 2026-10-14 (web sources; benchmark claims are vendor- or community-reported) found no newer model of this size that beats Ornith-1.5 for agentic coding:

- **Nemotron 3.5 Lightning 30B-A3B:** about 92 tok/s on a B60, but SWE-bench Verified 51.6.
- **Gemma 4 26B-A4B:** about 63 tok/s with vision, but SWE-bench Verified 57 and reported tool-call failures at 128K.
- **Laguna XS 2.1:** below the quality bar, and 29.5 tok/s on a B60.
- **Xing4.0-29B-A4B:** not in mainline llama.cpp.
- **Dense 27B models:** 17–26 tok/s.
- **Small Qwen3.8 MoE:** no official release exists.

The remaining headroom is quant quality.

### Candidates

All files are from [gbuzhf/Ornith-1.5-35B-A3B-TIEL-Calibrated-MTPv2-ICE-GGUF](https://huggingface.co/gbuzhf/Ornith-1.5-35B-A3B-TIEL-Calibrated-MTPv2-ICE-GGUF) (MIT, repo revision `9991338360005ec7785aefe8c26e9847ced3f1cf`). Each one embeds:

- Tiel's importance matrix
- a trained MTPv2 head (`--spec-type draft-mtp`)
- the Qwen-Sharp v22.4.1 template

Mean KLD against bf16 is the publisher's measurement (lower is better). Their `UD-IQ4_XS` reference is Unsloth's Ornith quant at the same tier as Tiel's file, not Tiel's own.

| File | Bytes | SHA-256 | Mean KLD | Size vs Tiel's 18,119,933,792 bytes |
| --- | --- | --- | --- | --- |
| `Ornith-1.5-35B-A3B-TIEL_Calibrated-MTPv2-19G-ICE.gguf` | 18,822,568,960 | `ba2581cf09101760b3d45054c439626b8f6cb3de53dad7987929072bacbe2b1f` | 0.0601 (UD-IQ4_XS: 0.0723) | +0.70 GB |
| `Ornith-1.5-35B-A3B-TIEL_Calibrated-MTPv2-21G-ICE.gguf` | 20,848,417,792 | `42fb3674d92d4ae90928dac0b3a22190702874ec71d7f94c176eb68ca4ca3881` | 0.0389 (about UD-Q4_K_XL quality at 2.4 GB less) | +2.73 GB |

Rejected:

- **[AtomicChat AD-Q4_K-IQ4_XS](https://huggingface.co/AtomicChat/Ornith-1.5-35B-A3B-GGUF):** no MTP file in the repository.
- **Q4_K_M / UD-Q4_K_XL (21.2–22.8 GB) and anything larger:** won't fit with vision at 128K.
- **Separately, the 23G/25G ICE tiers:** too large.

## Starting state and prerequisites

Measured on 2026-10-14 (ADR 0004 and [plan 0014](0014-b60-autoresearch.md)), with Tiel `UD-IQ4_XS`, ubatch 1024, reasoning budget 2048, draft length 3 and `--cache-ram 4096`:

| Metric | Value |
| --- | --- |
| Eval score | 44/49 and 42/49 (two runs of the same config; noise is about ±2 tasks) |
| Short decode | about 61 tok/s |
| Prefill at about 40K | about 1,160 tok/s |
| Long context (52K / 105K / 111K) | 3/3 needles at each depth; decode 29.8 / 21.8 / 22.7 tok/s; prefill 1,116 / 985 / 971 tok/s |
| VRAM | 21,146 of 24,480 MiB (86.4%), preallocated |
| Container memory | 4.5 GiB anonymous at idle |
| Model cache | local-path volume with 437 GB free on the node disk, so a second file fits beside the current one |

Before running this plan:

- Merge PR #259 (100K decode probe in `evaluate.py`), so every run reports `decode_tps_100k`.
- Make sure `pass` is unlocked and Docker is running locally, and that the operator has stopped other `qwen-intel` consumers.
- **Approval needed:** the `--model` swap and the init-container download are outside the ADR 0006 autoresearch exception. Each production switch is a reviewed PR to `main`, merged by the operator; rollback is a revert PR. Expect about 3 minutes of `qwen-intel` downtime per switch, plus download time on the first switch.

## Steps and gates

1. **Fresh Tiel reference.** In one low-traffic window, run `evaluate.py` twice on the current config. Record the mean `passed`, `quality_seconds`, `decode_tps`, `decode_tps_100k` and `prefill_tps_100k`. Also run the long-context probe once at about 111K (needles plus decode).
2. **Candidate 1 (19G-ICE): the drop-in.**
   - PR: add a checksum-verified download of the file to the init container as `/models/model-19g-ice.gguf`, keeping the current file. Point `--model` at it.
   - All other args stay the same, including the BF16 mmproj, 128K, Q8 KV, MTP with draft length 3, and `--cache-ram 4096`.
   - Expected VRAM is about 21.8 GiB of 23.9 GiB (about 89%).
3. **Gates for candidate 1.** Run `evaluate.py` twice and the 111K probe once. The candidate passes only if all of these hold:
   - **Loading and health:** the pod loads at 128K with mmproj, has no restarts, and peak VRAM is at most 95%. The minimum free host memory on `titania-gpu` is at least 3 GiB.
   - **Quality:** the mean of two runs is at least the Tiel reference mean, with tools at 8/8 and long-context needles at 3/3 in both runs.
   - **Speed:** short-context decode is at least 30 tok/s and `prefill_tps_100k` is at least 500. `decode_tps_100k` is no more than 5% below Tiel's.
   - **111K probe:** 3/3 needles with coherent output.
4. **Candidate 2 (21G-ICE): the better quant.** Expected VRAM is about 23.7 GiB (about 97%), over the gate.
   - First try the same args.
   - If loading fails or peak VRAM is above 95%, add `--no-mmproj-offload`. That keeps the projector in host RAM, saves about 0.86 GiB of VRAM, and makes vision slower. Re-check vision with a small image request.
   - Do not reduce context, KV type or ubatch to make it fit; those are protected by the requirements or already tuned.
   - Same gates as step 3, plus a vision smoke check if the projector moves to CPU.
5. **Choose.**
   - Adopt the best candidate that passes every gate. Prefer the one with more quality; if quality is tied, prefer higher `decode_tps_100k`.
   - If neither passes, revert to Tiel.
   - After adoption, update ADR 0004 and the LiteLLM versioned model name/metadata if the served alias changes. Then remove the unused model files from the PVC only with explicit approval.
6. **Follow-ups (separate trials):**
   - Deep decode is still below 30 tok/s beyond about 50K. Run an autoresearch session on the adopted model, focused on `decode_tps_100k` (MTP off or a shorter draft at depth).
   - Optionally test the publisher's agent-oriented template (`chat_template_sharp-v22.5.0-arrow4.0.jinja`) with an agent harness.

## Validation and rollback

- **Every manifest PR:** `kustomize build clusters/titania/apps/llm-serving-intel-llama | kubectl apply --dry-run=client -f -`. Check the checksum init exit code, readiness, restart count and VRAM (`xpu-smi` over SSH) after each rollout.
- **Memory abort:** the evaluator aborts below 2 GiB free host memory, and the run is discarded below 3 GiB headroom. On an abort or OOM, revert the PR immediately.
- **Rollback:** revert the switch PR. Tiel's file stays on the PVC throughout the trial, so rollback needs no download.
- **Measurement noise:** a single run varies by about ±2 tasks and about 8% in time. Gates therefore use two-run means, and token rates rather than wall time for speed.

## Outcome

Not started.
