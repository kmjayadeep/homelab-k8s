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
- **Keep-rule finding:** settings that shouldn't change answers (draft length, micro-batch) moved quality by ±2 tasks between runs, which equals the +2 quality-keep threshold. That caused one likely false keep (draft length 4), and it inflated "best" to 45, which then rejected a 6%-faster draft length of 3. Fixed in PR [#255](https://github.com/kmjayadeep/homelab-k8s/pull/255) (see `program.md` → The goal), which replayed `oct14` to the hand-merged config:
  - speed-only flags are judged on time, with quality only as a guard
  - quality is compared against a reference, the mean of the last 3 kept runs, rather than a single best run, and quality keeps need +3
  - comparing against the single baseline run instead was tried in the replay and rejected, because one lucky keep then made every later run look like +3
