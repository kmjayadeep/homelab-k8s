# Plan 0014: B60 llama-server autoresearch

- Status: Active; first session 2026-10-14 (`oct14`)
- Owner: Homelab operator
- Related ADR: [ADR 0006](../adrs/0006-local-b60-autoresearch.md)

## Goal and scope

Find better llama-server settings for the production B60 model (currently Tiel-Coder 35B-A3B) with an autoresearch-style loop:

1. Change one parameter.
2. Evaluate through LiteLLM.
3. Record the result.
4. Keep the change if it improved, otherwise discard it.

The loop runs locally from Claude Code during low-traffic windows that the operator chooses.

Out of scope:

- Changing the model, image, resources or context size.
- Merging results without review.

## Starting state and prerequisites

Verified on 2026-10-14:

- **Through LiteLLM** (`qwen-intel` and `tiel-coder-35b-a3b-intel`):
  - tool calls work
  - `seed` and `chat_template_kwargs` are passed through, and identical seeded requests return identical text
  - llama.cpp `timings` (including `draft_n` and `draft_n_accepted`) reach the client
- **Flags:** the production image (`server-intel b11515`) supports every candidate flag listed in `program.md`.
- **Smoke run:** `evaluate.py --smoke` passed 4/4 through LiteLLM, with decode about 64 tok/s on a short answer, MTP acceptance 0.64, and 13 GiB minimum free on `titania-gpu`.
- **Validation tests** (scratch worktree, no cluster access):
  - `experiment.py validate` accepted one-flag and coupled-pair changes
  - it rejected uncommitted edits, `--ctx-size` changes, non-`args` edits and three-flag changes
  - `verdict` produced the expected KEEP/DISCARD/CRASH results, including the baseline guard and the memory-headroom discard

Before each session:

- Stop other `qwen-intel` consumers.
- Check that `pass show litellm/evals` works in the local shell and that Docker is running.
- Make sure `main` is current.

## Steps and gates

1. **Session start** (`program.md` → Setup):
   - create the `autoresearch/<tag>` branch
   - run `evaluate.py --smoke`
   - run `experiment.py start`, which suspends Flux with the marker and checks Flux, the Deployment and node memory
   - record the baseline run as `keep`
2. **Loop** (`program.md` → loop): edit one flag, commit, `run`, `verdict`, `record`, then keep, or reset and `apply --restore`. Stop only on infrastructure failure or when the human interrupts.
3. **Session end:** summarize `results.tsv`, run `experiment.py archive` and commit `results/<tag>/`, then open a PR with the results and any kept changes. Run `experiment.py finish` to resume Flux.
4. **Adoption:** the operator reviews and merges the PR. Update ADR 0004 if the serving flags change materially.

## Validation and rollback

- **Abandoned session:** `python3 automation/llm-autoresearch/experiment.py finish` resumes Flux. `flux resume kustomization llm-serving-intel-llama -n llm-serving` does the same but leaves the marker annotation.
- **Rejected experiment:** handled inside the loop by resetting and restoring.
- **Unsure about a kept config:** close the PR. Production follows `main`.

## Outcome

Record each session here: date, tag, number of experiments, kept changes and the PR link.

### 2026-10-14 `oct14` (11:02–14:17 CEST, daytime, operator present)

PR [#253](https://github.com/kmjayadeep/homelab-k8s/pull/253) (merged; draft length 4 dropped). Results: [`results/oct14/`](../automation/llm-autoresearch/results/oct14/).

- **Run:** baseline plus 10 experiments, 3 kept and 7 discarded, with no crashes. Every rollout took 174–184 s.
- **Memory:** `titania-gpu` never had less than 11.4 GiB of host memory free. B60 VRAM (`xpu-smi` over SSH) was 86.6% on the kept config and 90.3% with `--ubatch-size 2048`. Power peaked at 143 W of the 200 W limit.
- **Mechanisms exercised live:** `start`, a no-op apply, real rollouts, keep, discard with `git reset` and `apply --restore`, and `finish`.
- **Kept changes** (in the PR from `autoresearch/oct14`):
  - `--ubatch-size 1024`: prefill at 24K rose from 959 to 1165 tok/s, TTFT at 8K fell from 12.7 to 10.7 s, and `quality_seconds` dropped 22%. This is a clear win.
  - `--reasoning-budget 2048`: a further 11% less `quality_seconds` at equal quality (45/49). Budget 1024 was 4.9% faster still but lost 2 code tasks.
  - `--spec-draft-n-max 4`: **probably noise.** It was kept on +2 homelab tasks while MTP acceptance fell from 0.675 to 0.58 and time rose 4.5%. Draft length 3 was later as fast or faster. Dropped before merge; production stays on draft length 3.
- **Keep-rule finding:** settings that shouldn't change answers (draft length, micro-batch) moved quality by ±2 tasks between runs, which equals the +2 quality-keep threshold. That caused one likely false keep (draft length 4), and it inflated "best" to 45, which then rejected a 6%-faster draft length of 3. Fixed in PR [#256](https://github.com/kmjayadeep/homelab-k8s/pull/256) (see `program.md` → The goal), which replayed `oct14` to the hand-merged config:
  - speed-only flags are judged on time, with quality only as a guard
  - quality is compared against a reference, the mean of the last 3 kept runs, rather than a single best run, and quality keeps need +3
  - comparing against the single baseline run instead was tried in the replay and rejected, because one lucky keep then made every later run look like +3

### 2026-10-14 `oct14b` (16:39–18:28 CEST, operator present)

Results: [`results/oct14b/`](../automation/llm-autoresearch/results/oct14b/). The session branch predated the merge of PR #256, so `verdict` still ran the old rule; each run was also scored with the new rule's `decide()`, and the two agreed every time.

- **Run:** baseline plus 5 experiments and one repeat of the unchanged kept config, all discarded, with no crashes. Host memory never fell below 12.0 GiB free.
- **Baseline:** 44/49 in 449 s on the `oct14` config (micro-batch 1024, reasoning budget 2048, draft length 3).
- **Discarded:**
  - `--threads 6`: 45/49, +4% time.
  - `--poll 100`: 43/49, +19% time, decode unchanged.
  - `--reasoning-budget 1536`: 43/49, code 25/30, −2% time. Together with 1024 in `oct14`, 2048 looks like the floor for code quality.
  - `--spec-draft-p-min 0.2`: 40/49, +17% time. Both p-min values tried (0.2 and 0.6) scored 40, so this flag changes answers on this build and should not count as speed-only.
  - `--spec-draft-n-min 2`: 43/49, +17% time.
- **Evaluator noise finding:** the repeat of the unchanged kept config scored 42/49 in 485 s, against the baseline's 44/49 in 449 s. On an identical config, quality moved by 2 tasks (homelab 6/8 → 4/8) and time by 8%. A per-suite breakdown showed two causes:
  - **Warm cache:** the baseline ran on a pod the smoke check had just used, and its long-context suite took 4 s instead of the 25 s seen in every other run.
  - **Reasoning length:** wall time follows how many tokens the model writes (homelab 2.3K–4.9K, code 20K–26K completion tokens) at a constant decode speed of about 61–63 tok/s.

  Wall time is therefore too noisy for the 5% speed threshold, and three of the five discards may have been judged on noise.
- **Proposed evaluator changes before the next session:**
  - judge speed-only flags on the per-token rates (`decode_tps`, `prefill_tps_24k`, `ttft_8k_s`), not on `quality_seconds`
  - start the baseline from a fresh restart, or send a warm-up request after every rollout, so every run starts from the same cache state
  - consider two evaluation passes per config, or a larger task set, before tightening quality margins

### 2026-10-15 `oct15` (06:15–07:24 CEST, operator present)

Results: [`results/oct15/`](../automation/llm-autoresearch/results/oct15/). This was the first session on Ornith 21G-ICE (adopted in [plan 0015](0015-ornith-ice-quant-b60-trial.md)) and the first with `decode_tps_100k` in the keep rule.

- **Baseline:** reused the two plan 0015 evaluation runs of the identical spec from 05:47–06:11, instead of a third run (deviation; it saved about 13 minutes). Passed 45 and 44; decode 66.8 tok/s; `decode_tps_100k` 25.6 and 26.7.
- **Discarded:**
  - `--spec-draft-n-max 2`: 43/49; decode 61.8, at 100K 25.3; acceptance 0.81. Higher acceptance did not pay for the shorter drafts.
  - `--spec-draft-n-max 4`: 43/49; decode 65.7; at 100K **18.6** (−30%), acceptance 0.62. Vetoed by the deep-decode rule.
  - **MTP off** (`--spec-type`/`--spec-draft-n-max` removed): 43/49; decode 64.8 (−3%); at 100K **27.8 (+4%)**; `prefill_tps_100k` **1,137 (+9%)**; `quality_seconds` +6%. The rule discarded it.
- **Finding:** on 21G-ICE with b11515, MTP buys only about 3% at short context and costs decode and prefill at long context. It is a near-tie on one run. Confirm with two runs before removing it. Removing MTP may also free enough VRAM to put the vision projector back on the GPU.
- **Draft-length sweep at 100K:** 2 → 25.3, 3 → 26.7, 4 → 18.6 tok/s. Draft length 3 is optimal with MTP on.
- **Restore time:** each restore now takes about 305 s, because the init container verifies checksums for three model files (Tiel, 19G and 21G). Removing the unused files would shorten it (needs approval).

### 2026-10-15 `oct15b` (08:02–09:44 CEST, operator present)

Results: [`results/oct15b/`](../automation/llm-autoresearch/results/oct15b/). On 21G-ICE. The operator asked to test MTP off again.

- **Baseline:** 46/49, 456 s, decode 64.8 tok/s, `decode_tps_100k` 27.5, `prefill_tps_100k` 1,044.
- **Kept:**
  1. **MTP off** (`--spec-type`/`--spec-draft-n-max` removed). This was a simplicity keep on a tie; `verdict` said DISCARD. Quality was 45 (within noise), decode 64.8 (unchanged), at 100K 27.8, and `prefill_tps_100k` 1,138 (+9%, the same as `oct15`'s single run).
  2. **Vision projector back on the GPU** (`--no-mmproj-offload` removed), again a simplicity keep. Turning MTP off freed about 1.1 GiB of VRAM. Peak VRAM was 91.6%; vision took 0.41 s per new image vs 2.0 s on the CPU; container anonymous memory was 4.8 GiB vs 6.0. Text metrics were unchanged.
  3. **`--batch-size 4096 --ubatch-size 2048`.** KEEP by the rule: `prefill_tps_100k` 1,179 (+4%), 1,366 at about 40K, `ttft_8k_s` 9.2, `quality_seconds` −10%, peak VRAM 93.6%.
- **Discarded:** `--temp 1.0` (44/49, +10% time) and `--reasoning-budget 3072` (43/49, +13% time).
- **Net vs MTP-on baseline:** same decode, prefill at 100K +13% (1,044 → 1,179), much faster vision, four fewer flags, peak VRAM 93.6%.

### 2026-10-15 `oct15c` (10:46–12:14 CEST, operator present)

Results: [`results/oct15c/`](../automation/llm-autoresearch/results/oct15c/). Ran after the 256K/parallel trials (ADR 0004).

- **Baseline** (`oct15b` config): 46/49, 458 s, decode 64.8 tok/s, `decode_tps_100k` 27.8, `prefill_tps_100k` 1,179.
- **Kept:** `--spec-type ngram-mod` with default settings. This is n-gram speculation from the context, with no VRAM cost. Decode was 67.9 tok/s (+5%), `quality_seconds` 418 (−9%), acceptance 0.57, `decode_tps_100k` 27.2 (−2%, inside the veto), and 44/49.
- **Discarded:**
  - `--spec-ngram-mod-n-match 12`: acceptance 0.28, +15% time.
  - `--spec-ngram-mod-n-match 32`: acceptance 0.66, decode 68.0, 41/49 tripped the quality guard (likely noise).
  - `--spec-ngram-mod-n-min/max 16/32`: acceptance 0.74, decode 68.2, but +11% time.
- **Note:** raising acceptance did not cut total time. The defaults (n-match 24, draft 48–64) remain best.
