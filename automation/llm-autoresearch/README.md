# llm-autoresearch

This is a local, Claude Code–driven hill-climb over the B60 llama-server flags, inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). Each experiment changes one flag in the production Deployment, evaluates the result through LiteLLM, and keeps the change only if it helps. The decision is recorded in [ADR 0006](../../adrs/0006-local-b60-autoresearch.md) and the plan in [plan 0014](../../plans/0014-b60-autoresearch.md).

| File | Role | Who edits |
| --- | --- | --- |
| [`program.md`](program.md) | Agent instructions: setup, rules, loop, keep rule | human |
| `clusters/titania/apps/llm-serving-intel-llama/deployment-tiel-coder-trial.yaml` | The experiment: llama-server `args` only | agent |
| [`evaluate.py`](evaluate.py) | Fixed evaluator (ground truth) | nobody during a session |
| [`experiment.py`](experiment.py) | `start`/`apply`/`run`/`verdict`/`record`/`finish` tooling | nobody during a session |
| `tasks/`, `sandbox/` | Eval data and the network-less grading container | nobody during a session |
| `results.tsv`, `run.log`, `runs/` | Session output (git-ignored) | tooling |

## Running a session

1. Stop agents and other consumers that use `qwen-intel`.
2. Start Claude Code in the repo root and tell it: *"Read automation/llm-autoresearch/program.md and let's kick off a new experiment. Do the setup first."*
3. Confirm the run tag and the baseline, then leave it running.
4. Interrupt it when you're done. It summarizes, opens a PR with any kept changes, and resumes Flux.

Each experiment takes about 35 minutes: a 3–5 minute rollout plus about 30 minutes of evaluation. An 8-hour night gives roughly 12–14 experiments.

## Requirements

- `kubectl` and `flux` with operator access, plus `kustomize`, `docker` and `pass` (entry `litellm/evals`) on the local machine.
- The model is called through `https://litellm.cosmos.cboxlab.com/v1` as `qwen-intel`.
- The key is read in-process (see `automation/llm-performance/bench.py`) and is never printed.
- Memory on `titania-gpu` is read from Prometheus through the Kubernetes API service proxy.

## What the eval measures

| Suite | Size | Graded by |
| --- | --- | --- |
| speed (diagnostic) | short / ~8K / ~24K prompt × 2 | llama.cpp `timings` passed through by LiteLLM |
| tools | 8 | correct function and arguments, or correctly no call |
| longctx | 3 needles in ~16K tokens | exact match |
| homelab | 8 manifest tasks | YAML assertions in the sandbox |
| code | 30 HumanEval+ tasks | HumanEval+ tests in the sandbox |

The sandbox runs model-generated code with `--network none`, a read-only root filesystem, no capabilities, a non-root user, and memory and PID limits.

`tasks/humaneval/tasks.jsonl.gz` is a fixed-seed subset of [HumanEval+](https://github.com/evalplus/humanevalplus_release) v0.1.10 (EvalPlus, Apache-2.0; HumanEval © OpenAI, MIT).

## Recovering if a session is abandoned

`python3 automation/llm-autoresearch/experiment.py finish` resumes Flux, and production returns to `main`. Running `flux resume kustomization llm-serving-intel-llama -n llm-serving` directly does the same thing, but leaves the marker annotation in place.
