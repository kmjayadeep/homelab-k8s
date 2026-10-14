# Plan 0014: B60 llama-server autoresearch

- Status: Ready; no session run yet
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
3. **Session end:** summarize `results.tsv`, then open a PR with any kept changes and the results table. Run `experiment.py finish` to resume Flux.
4. **Adoption:** the operator reviews and merges the PR. Update ADR 0004 if the serving flags change materially.

## Validation and rollback

- **Abandoned session:** `python3 automation/llm-autoresearch/experiment.py finish` resumes Flux. `flux resume kustomization llm-serving-intel-llama -n llm-serving` does the same but leaves the marker annotation.
- **Rejected experiment:** handled inside the loop by resetting and restoring.
- **Unsure about a kept config:** close the PR. Production follows `main`.

## Outcome

Record each session here: date, tag, number of experiments, kept changes and the PR link.
