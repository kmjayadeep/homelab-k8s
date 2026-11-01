# Plan 0024: Trial NVIDIA Nemotron 3.5 Lightning 30B-A3B on the B60

- Status: Draft (manifests in PR; operator evaluates)
- Owner: Homelab operator
- Related ADR: [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md) (one B60 Deployment behind LiteLLM), [ADR 0006](../adrs/0006-local-b60-autoresearch.md) (flag tuning)
- Related plans: [0015](0015-ornith-ice-quant-b60-trial.md) (first rejected this model on quality: SWE-bench Verified 51.6), [0018](0018-b60-model-switch-baseline.md) (trial method and Ornith baseline numbers)

## Goal and scope

Serve **NVIDIA Nemotron 3.5 Lightning 30B-A3B** (bartowski Q4_0 + first-party MTP head) on the single Intel Arc Pro B60 and measure it with the fixed evaluator against the Ornith-1.5 21G-ICE baseline. The operator asked for this trial after reading an independent B60 writeup ([srmiles/local-llm-benchmarks](https://github.com/srmiles/local-llm-benchmarks/blob/main/models/tested/nemotron-3.5-lightning-30b-a3b.md)) that measured it as the fastest 30B-class model on the same card and runtime.

Plan 0015 rejected this model unseen on vendor quality numbers. This plan measures it. **It knowingly breaks one hard requirement from plans 0015/0018: there is no vision projector for this model, so the trial is text-only.** Promotion would need the operator to drop or relax the vision requirement.

Out of scope: the runtime (llama.cpp SYCL, same b11515 image), parallel slots, anything in litellm beyond the versioned `model_list` entry.

## Starting state and prerequisites

Baseline: Ornith-1.5 21G-ICE as recorded in plan 0018 (`oct15c`): 44–46/49, short decode 68 tok/s, 27.2 tok/s and 1,177 tok/s prefill at 100K, idle VRAM 92.9% rising to 97% over uptime.

What the field writeup measured for Nemotron (b10566 SYCL, Q4_0 + Q8_0 MTP head, Q8 KV, 128K, `--parallel 1`):

| Metric | Field value |
| --- | ---: |
| Synthetic decode, n-max 7 | 91.9 tok/s at 99.5% MTP acceptance |
| Decode at 2K / 12K / 32K / 70K context | 89.9 / 88.0 / 74.2 / 72.2 tok/s |
| Prefill at 12K / 83K | 1,760 / 1,031 tok/s |
| Peak VRAM at 128K | 22.26 GiB (about 92.7%) |
| Real agent traffic (opencode, 82K ctx) before retune | 46% acceptance, 23.6–58.3 tok/s |
| Real code generation after `--spec-draft-p-min 0.6`, `temp 0.2` | 50.7 tok/s (from 35.0) |

Two findings there shape the config: `--spec-draft-n-max` must stay at or below 7 (a +71% verify-step cost appears at batch 9 on this card), and 262K context fits but leaves 126 MiB free and quarters decode, so 128K it is. Q4_0 is the only quant that fits: the dense trunk and SSM tensors do not compress, so IQ2 through Q4_0 all land at 17.5–17.8 GiB and Q4_K_M (23.7 GiB) cannot load beside the 2 GiB head.

Prerequisites and open items for the operator:

- **Checksums are not pinned.** The Hugging Face file hashes could not be read from the agent's environment. The init container downloads from `resolve/main`, prints the sha256 of each file and continues. After the first start, copy both values into `MODEL_SHA256` / `MTP_SHA256` in `deployment-nemotron.yaml` and, if possible, replace `main` in `HF_REPO` with the repo revision.
- `qwen-intel` and `sensitive` keep pointing at `ornith-1.5-35b-a3b-intel`, which is at 0 replicas during the trial, so **Open WebUI and kagent's local model are down for the trial**. `local-first` falls back to DeepSeek as designed. Flip the alias only if the trial is promoted (step 7 of plan 0018, including the alias-drift check).
- Other `qwen-intel` consumers stopped for the download: about 21 GB, roughly 5 minutes at the 83 MB/s seen in plan 0018, plus load.
- Flag check on b11515: `--spec-draft-p-min` was used in plan 0014 on this build; `--model-draft` with `--spec-type draft-mtp` and `--n-gpu-layers-draft` are standard. If the server rejects a flag at startup, the pod log says so before the model loads.

## Steps and gates

1. **This PR** merges: `pvc-nemotron.yaml`, `deployment-nemotron.yaml` (1 replica), `service-nemotron.yaml`; `deployment-ornith.yaml` to 0 replicas; Flux health check retargeted; LiteLLM route `nemotron-3.5-lightning-30b-a3b-intel`. Gate: pod Ready, 0 restarts, `/props` shows the alias and `n_ctx` 131072, **idle VRAM below 95%** (`xpu-smi stats -d 0 -j`), node free memory above 3 GiB, Flux `llm-serving-intel-llama` and `litellm` Ready, `/v1/models` lists the new route.
2. **Pin checksums** from the init container log in a follow-up PR (no restart needed: the files exist and the next start verifies them).
3. **Function gate** through the versioned route: one benign chat, one `tools` request (never execute the call), then `python3 automation/llm-autoresearch/evaluate.py --smoke --model nemotron-3.5-lightning-30b-a3b-intel`. No image check: the route is `supports_vision: false`.
4. **Measure.** Two full runs of `evaluate.py --model nemotron-3.5-lightning-30b-a3b-intel`; read VRAM right after the 100K probe. Record rows in the Outcome table.
5. **One tuning idea per rollout if close**, judged by a full run: `--spec-draft-p-min` removed (plan 0014 found p-min changed answers on Ornith's MTP head, scoring 40 at both 0.2 and 0.6; if quality lands below Ornith here, this is the first suspect), `--spec-draft-n-max 3` and `5`, `--temp 0.2` (the field writeup's code-generation setting), `--batch-size 4096` (watch VRAM). Stop after two consecutive ideas without a gain.
6. **Promote or remove.** Promotion follows plan 0018 step 7 (alias move, `/router/settings` check, ADR 0004 amendment) and must record the decision to drop the vision requirement. Removal reverses this PR; Ornith's files are still on `intel-llama-ornith-models`, so the return is a checksum re-verify. Deleting the Nemotron PVC (about 21 GB on `titania-gpu`) needs explicit approval.

Gates, taken from plan 0018 phase 1 with the vision line struck:

| Gate | Target | Ornith reference |
| --- | ---: | ---: |
| `passed` (mean of 2 runs) | within 2 of Ornith | 44–46 |
| tools / needles | 8/8, 3/3 | 8/8, 3/3 |
| short decode | at least 30 (goal: clearly above 68) | 68 |
| `decode_tps_100k` | at least 30 (the gate Ornith misses) | 27.2 |
| `prefill_tps_100k` | at least 500 | 1,177 |
| VRAM idle and after the probe | below 95% | 92.9% / 97% |
| `min_free_gib` | at least 3 | 16.1 |

## Validation and rollback

- `kustomize build clusters/titania/apps/llm-serving-intel-llama` and `clusters/titania/apps/litellm` plus `git diff --check` on the PR; `kubectl --dry-run=client` as required by AGENTS.md. Flux state is confirmed from the cluster, never inferred from Git.
- Memory abort rule from plan 0014: free memory below 2 GiB or VRAM at or above 95% at idle means stop and roll back before the next request.
- Rollback: Ornith `replicas: 1`, Nemotron `replicas: 0`, Flux health check back to `intel-llama-ornith`, in one PR. Nothing is deleted without approval.

## Outcome

| Run | Config | short decode | decode 13K / 40K | `decode_tps_100k` | `prefill_tps_24k` / `100k` | accept | idle / peak VRAM | passed | `quality_seconds` |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| — | Q4_0 + MTP Q8_0, n-max 7, p-min 0.6, b11515 | | | | | | | | |
