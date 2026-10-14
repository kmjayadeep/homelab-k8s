# ADR 0006: Tune the B60 server with an operator-started local autoresearch loop through LiteLLM

- Status: Accepted
- Date: 2026-10-14
- Related plan: [0014: B60 autoresearch](../plans/0014-b60-autoresearch.md)
- Supersedes: [ADR 0005](0005-nightly-b60-eval-handoff.md)
- Amends: [ADR 0004](0004-llamacpp-sycl-b60-behind-litellm.md) (single B60 Deployment, changed only through Git)

## Context

ADR 0005 introduced a scheduled GitHub Actions eval with a dedicated in-cluster runner, a GPU handoff to transient Jobs, an admission policy and a watchdog. After deploying it, the operator chose a simpler model, inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch). The operator starts a Claude Code session locally during low traffic, and the agent hill-climbs one llama-server parameter at a time on the **production** Deployment. Evaluation goes **through LiteLLM**, not around it. The operator accepts that `qwen-intel` serves experimental configs during a session and stops other consumers for its duration.

## Decision

- **No in-cluster eval infrastructure.** The `llm-eval` runner, RBAC, admission policy, Service, watchdog and alerts are removed, and the private `homelab-llm-evals` workflow is disabled.
- **The experiment is the production manifest.** The agent edits only the llama-server `args` in `deployment-tiel-coder-trial.yaml`, on a local `autoresearch/<tag>` branch.
  - Identity, routing and context flags are protected: `--ctx-size 131072` and `--parallel 1` stay fixed.
  - `experiment.py` rejects edits outside `args`, changes to protected flags, and more than two changed flags.
- **Session control:** during an operator-started session, the agent uses the operator's kubeconfig to:
  - suspend `llm-serving/llm-serving-intel-llama` (with the marker `llm-autoresearch.cboxlab.com/suspended-by`)
  - apply that app's Kustomize build with server-side apply
  - `git reset --hard` its own rejected experiment commits on the `autoresearch/<tag>` branch
  - resume Flux at the end

  [AGENTS.md](../AGENTS.md) carries this as a narrow exception.
- **Evaluation and keep rule:** the fixed `evaluate.py` measures quality (49 graded tasks) and time through LiteLLM's `qwen-intel`, with the key read in-process from `pass`. `experiment.py verdict` applies a deterministic keep rule:
  - +2 tasks with no more than 15% extra time, or
  - at least 5% faster with at most −1 task against both the best and the baseline, and
  - at least 3 GiB of headroom on `titania-gpu`.

  Model-generated code runs in a local network-less Docker sandbox.
- **Adoption:** kept configs reach `main` only through a PR that the human merges. Ending a session resumes Flux, so production returns to `main` until then.

## Alternatives considered

- **Keep ADR 0005's nightly pipeline.** It provided unattended scheduling and stronger isolation, but the operator found the machinery disproportionate. It also tested fixed variants rather than climbing from the best result.
- **A separate eval Deployment or alias.** It would avoid touching production, but the single GPU means only one server can run at a time anyway, and the operator explicitly wants evaluation through the real LiteLLM route.
- **Committing each experiment to `main`.** This would keep Flux in charge, but it floods history, turns every rejected idea into a deploy and a revert, and requires push rights to `main`.

## Consequences

- **Availability:** `qwen-intel` restarts every experiment (about every 35 minutes) and may serve worse configs between keep and discard. The operator must stop consumers first.
- **Abandoned sessions:** if the session dies, Flux stays suspended and production keeps the last applied config. That is the kept config, or one under evaluation. `experiment.py finish` or `flux resume` recovers it. No in-cluster watchdog or alert covers this.
- **Memory:** host memory on `titania-gpu` is still the main risk. Rollouts and evals abort below 2 GiB free, and the restore runs immediately. Larger K/V or batch settings remain risky.
- **Measurement limits:** the eval probes about 24K tokens and is noisy at 49 tasks. Fixed seeds and margins reduce, but do not remove, spurious keeps, so treat a kept change as a candidate for the PR review.

## Implementation status

The tooling is in `automation/llm-autoresearch/` (`program.md`, `evaluate.py`, `experiment.py`). The ADR 0005 cluster objects are removed from Git and pruned by Flux. The evaluator was smoke-tested on 2026-10-14 through LiteLLM. No experiment session has run yet.
