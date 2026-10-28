# autoresearch: B60 llama-server tuning

This is an experiment loop, inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch), for tuning the production llama.cpp server on the Intel Arc Pro B60. The human edits this file. You (the agent) edit only the llama-server `args` in the Deployment manifest. The loop changes one idea at a time, evaluates it through LiteLLM, keeps the change if it helps and discards it if it doesn't.

The operator runs this from Claude Code during a low-traffic window and has stopped other `qwen-intel` consumers. Production **is** the experiment: every change replaces what `qwen-intel` serves until the session ends.

## Setup

Do these steps once per session, together with the human:

1. **Agree on a run tag** based on today's date, for example `oct15`. Create the branch `autoresearch/<tag>` from an up-to-date `main`; it must not already exist.
2. **Read the in-scope files:**
   - `automation/llm-autoresearch/README.md`: context.
   - `automation/llm-autoresearch/evaluate.py`: the fixed evaluator. **Read-only.**
   - `automation/llm-autoresearch/experiment.py`: session tooling. **Read-only.**
   - `clusters/titania/apps/llm-serving-intel-llama/deployment-ornith.yaml`: **the file you edit, and only its llama-server `args`.**
   - `adrs/0006-local-b60-autoresearch.md`: what the operator has approved.
   - `automation/llm-autoresearch/results/*/results.tsv`: every past session. Don't repeat an idea that was already discarded on the current config unless you have a reason to expect a different result.
3. **Smoke check:** `python3 automation/llm-autoresearch/evaluate.py --smoke`. It sends one request per suite. If it fails, stop and tell the human.
4. **Start:** `python3 automation/llm-autoresearch/experiment.py start`. This suspends Flux for `llm-serving-intel-llama` with a marker annotation and creates `results.tsv`. It refuses if `results.tsv` still holds a previous, unarchived session; archive that first (see "Ending the session").
5. **Confirm with the human, then begin.** The first run is the baseline: the unchanged config.

## What you may change

You may change **only** the `args` list of the `llama-server` container in `deployment-ornith.yaml`. Rules:

- **Protected flags.** These may not be touched: `--model`, `--mmproj`, `--alias`, `--host`, `--port`, `--metrics`, `--jinja`, `--ctx-size` (stays 131072), `--parallel` (stays 1) and `--n-gpu-layers`. Production needs the full single-slot 128K context, which the eval cannot see, so nothing may trade it away.
- **One idea per experiment.** That means one flag, or a coupled pair such as `--cache-type-k` with `--cache-type-v`, or `--batch-size` with `--ubatch-size`. `experiment.py` rejects more than two changed flags.
- **Everything else is off-limits:** the image, init container, resources, probes, volumes and all other files.
- **Candidate areas:**
  - speculative decoding: `--spec-draft-n-max`, `--spec-draft-n-min`, `--spec-draft-p-min`, or removing `--spec-type` and its options
  - `--batch-size` and `--ubatch-size`
  - `--threads` and `--threads-batch` (the node has 8 vCPUs)
  - K/V cache types
  - `--flash-attn`
  - sampling defaults: `--temp`, `--top-p`, `--top-k`, `--min-p`, `--presence-penalty`, `--repeat-penalty`
  - reasoning controls such as `--reasoning-budget`

  At about 100K tokens, MTP acceptance was only 0.35–0.40. Worth testing first: speculative decoding off (`--spec-type none`) or a shorter draft. Judge these on `decode_tps_100k` as well as overall time.

  Check that a flag exists in this llama.cpp build before using it. A crash on an unknown flag wastes a restart. To list the supported flags, run `kubectl -n llm-serving exec deploy/intel-llama-ornith -c llama-server -- /app/llama-server --help`. Other options include `--cache-reuse`, `--poll`, and n-gram speculation (`--spec-type`, `--spec-ngram-*`).
- **Memory is the binding risk.** A past 128K trial OOMed the host and took k3s down. The evaluator and `apply` abort when free memory on `titania-gpu` drops below 2 GiB, and `verdict` discards anything below 3 GiB of headroom. Be careful with f16 K/V or larger batches.

## The goal

Make the model **better and/or faster** on the fixed eval, using these metrics from `evaluate.py`:

- **`passed`/`total`:** 49 graded tasks: 30 HumanEval+, 8 homelab manifests, 8 tool calls and 3 long-context needles.
- **`quality_seconds`:** total wall time of those tasks. It reflects both speed and how long the model thinks.
- **`decode_tps_100k` / `prefill_tps_100k`:** one request of about 100K prompt tokens. Production must decode at least 30 tok/s at long context, and on 2026-10-14 this config managed only 21.8–22.7 tok/s at 105–111K (ADR 0004). This is the main gap to close.
- **Diagnostics:** `decode_tps`, `ttft_8k_s`, `prefill_tps_24k`, `mtp_accept` and `min_free_gib`. The speed suite's depth labels undercount: "8K" and "24K" are really about 13K and 40K tokens. They are kept for comparability.

Requests use fixed per-task seeds, but any change to the server alters the sampling path. In session `oct14`, flags that should not change answers (draft length, micro-batch size) still moved `passed` by about ±2 tasks between runs. A single run is therefore noisy, and the keep rule compares quality against a **reference**: the mean `passed` of the last 3 kept runs. "Kept time" is the `quality_seconds` of the last kept run. `experiment.py verdict` reads the changed flags from `HEAD~1..HEAD` and applies the rule:

- **Speed-only flags** (`--batch-size`, `--ubatch-size`, `--threads`, `--threads-batch`, `--flash-attn`, `--poll`, `--cache-reuse` and every `--spec-*` flag) are judged on time. KEEP if at least 5% faster, with quality no more than 2 tasks below both the reference and the baseline. A higher score alone never keeps them.
- **Other flags** (sampling, reasoning, cache types):
  - **KEEP for quality:** at least 3 tasks above the reference, with time no more than 15% worse.
  - **KEEP for speed:** at least 5% faster, with quality no more than 1 task below both the reference and the baseline.
- **Deep decode** (both rows have `decode_tps_100k`): a drop of more than 10% vetoes any keep. A gain of at least 8%, with `quality_seconds` no more than 10% worse, counts as "faster" in both rules above.
- **DISCARD:** everything else, and any run with less than 3 GiB of memory headroom.

Replaying `oct14` through this rule reproduces the config that was merged by hand: it keeps micro-batch 1024, draft length 3 and reasoning budget 2048, and rejects draft length 4, temperature 0.3 and reasoning budget 1024.

**Simplicity criterion:** with equal results, fewer flags is better. Removing a flag without losing anything is a win; you may keep it even when `verdict` says DISCARD on a tie, and say so in the description.

## The experiment loop

LOOP FOREVER:

1. **Check the state:** `git status`, current branch and HEAD. HEAD must be the last kept config.
2. **Edit** the manifest's llama-server `args` with one idea.
3. **Commit:** `git commit -am "<short description of the idea>"`.
4. **Run:** `python3 automation/llm-autoresearch/experiment.py run > automation/llm-autoresearch/run.log 2>&1`. This applies the manifest with Flux suspended, waits for the rollout (Recreate plus checksum, about 3–5 minutes), then evaluates (about 10–14 minutes). Do **not** let the output flood your context.
5. **Read the result:** `tail -n 20 automation/llm-autoresearch/run.log`. Then run `python3 automation/llm-autoresearch/experiment.py verdict`.
6. **Record:** `python3 automation/llm-autoresearch/experiment.py record <keep|discard|crash> "<description>"`. `results.tsv` stays untracked; do not commit it.
7. **Act on the verdict:**
   - **KEEP:** leave the commit. The branch advances.
   - **DISCARD or CRASH:** run `git reset --hard HEAD~1`, then **immediately** `python3 automation/llm-autoresearch/experiment.py apply --restore`. Production must never be left on a rejected config while you think about the next idea.
8. **Repeat.**

**Crashes:**

- **Trivial mistake** (a typo or unknown flag): fix it in a new commit after the reset and retry once.
- **Broken idea** (OOM, eviction, refusal to load): record it as `crash`, reset, restore and move on.
- **Memory abort** (`apply` or the evaluator aborts on memory): reset and restore right away, and do not retry that direction with larger values.

**Infrastructure failure:** this covers LiteLLM down, Prometheus unreachable, a node NotReady, or the restore failing.

1. Stop experimenting.
2. Make sure production is on the kept config.
3. Run `experiment.py finish` if production cannot be brought back.
4. Wait for the human.

This is the only reason to stop on your own.

**NEVER STOP:** once the loop has started, do not pause to ask whether to continue. The human may be asleep. When you run out of ideas:

- re-read the llama.cpp server flags
- combine near-misses from `results.tsv`
- try the opposite direction of a discarded change
- try removing flags

The loop runs until the human interrupts you.

## Ending the session

When the human stops the loop:

1. Print `results.tsv` and summarize the kept changes against the baseline.
2. Archive the session: `python3 automation/llm-autoresearch/experiment.py archive`. This moves `results.tsv` and the run summaries into `automation/llm-autoresearch/results/<tag>/`. Commit that directory, and add the session to the Outcome section of `plans/0014-b60-autoresearch.md`.
3. Push `autoresearch/<tag>` and open a PR against `main`, even if nothing was kept, so the results reach `main`. The PR body must include the `results.tsv` contents.
4. Run `python3 automation/llm-autoresearch/experiment.py finish` to resume Flux. Production returns to `main`'s config until the PR is merged.

Never merge the PR yourself, and never push to `main`.
