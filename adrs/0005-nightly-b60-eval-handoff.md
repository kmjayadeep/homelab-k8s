# ADR 0005: Lend the B60 to a nightly eval by suspending Flux, not by changing Git

- Status: Superseded by [ADR 0006](0006-local-b60-autoresearch.md) (2026-10-14)
- Date: 2026-10-14
- Related plan: [0013: Nightly LLM parameter eval](../plans/0013-nightly-llm-parameter-eval.md)
- Amends: [ADR 0004](0004-llamacpp-sycl-b60-behind-litellm.md) (single B60 Deployment in Git)

## Context

The operator wants llama-server flags and sampling parameters evaluated every night, with results ready in the morning. `titania-gpu` has a single Arc Pro B60, so a flag change needs the production `intel-llama-tiel-coder-trial` pod to release the GPU. The serving Flux Kustomization uses `wait: true`, health-checks that Deployment, and reconciles every 15 minutes. Any out-of-band scale or patch is reverted, and the reverted pod would contend for the GPU in the middle of a run. Consumers of `qwen-intel` will avoid 02:00–04:00 Europe/Berlin.

## Decision

- **Window:** every night between 02:00 and 04:00 Europe/Berlin, the nightly workflow in the private `kmjayadeep/homelab-llm-evals` repository may do the following. This standing approval covers only these steps:
  - Suspend `llm-serving/llm-serving-intel-llama` with field manager `flux-client-side-apply`, plus the marker annotation `llm-eval.cboxlab.com/suspended-by`.
  - Scale the production Deployment to zero.
  - Run transient `llm-eval-server-*` Jobs that clone the production pod and change only allowlisted llama-server arguments.
- **Restore:** to return the GPU, the workflow resumes the Kustomization. Flux then reapplies the Git-declared replicas, so Git stays the source of truth and nothing is committed to change production.
- **Watchdog:** the in-cluster `llm-eval-watchdog` CronJob runs at 03:50 local. It deletes leftover eval Jobs and resumes the Kustomization **only if** it carries the eval marker. An operator's own suspension is never undone.
- **Runner boundary:** the workflow runs on a dedicated ARC runner (`homelab-llm-evals`, ServiceAccount `llm-eval-runner`) registered only to the private repository.
  - Its namespaced Role covers that one Kustomization, that one Deployment and its scale, Jobs, and reading Pods and their logs.
  - The `llm-eval-server-jobs` ValidatingAdmissionPolicy only admits runner-created Jobs that match the eval-server shape:
    - digest-pinned `ghcr.io/ggml-org/llama.cpp` image
    - model-cache PVC and emptyDir volumes only
    - no ServiceAccount token
    - no Secret, ConfigMap or field references
    - no host namespaces or privilege
- **Promotion:** a winning configuration reaches production only through a reviewed PR to `clusters/titania/apps/llm-serving-intel-llama/`.

## Alternatives considered

- **Nightly Git commits that switch flags.** This floods history, couples evaluation to the PR workflow, and still leaves production down if a revert commit fails.
- **Removing `replicas` from the manifest so Flux ignores scaling.** Git would no longer guarantee that production comes back.
- **A second inference Deployment in Git.** There is only one GPU, so this needs the same handoff, and ADR 0004 rejected keeping stopped deployments.
- **Varying sampling parameters only.** This is safe, but it cannot answer the server-flag questions (MTP draft length, batch sizes, K/V types) that motivated the eval. It is kept as the default `sampling` mode.
- **Reusing the existing `cosmos` runners.** They serve public repositories, where fork pull requests could run code that holds this ServiceAccount.

## Consequences

- `qwen-intel` is unavailable for up to about 2 hours on nights that run in `full` mode. The `sampling` mode only adds load.
- A non-default flag set can exhaust host memory on `titania-gpu`. Mitigations:
  - the eval pod keeps production's memory limit
  - a guard aborts when available memory drops below 2 GiB, or on OOM
  - flag values are allowlisted, with context never above 131072
  - risky K/V types are gated behind a separate approval
  - the GPU node is an agent, not the control plane
- Failure modes are covered by the watchdog and by the `LlmEvalProductionNotRestored` and `LlmEvalServerLingering` alerts.
- `llm-serving` Kustomization health briefly shows "suspended" each night.

## Implementation status

Superseded on 2026-10-14: the operator replaced the nightly pipeline with a local autoresearch loop (ADR 0006). The `llm-eval` cluster objects were removed from Git and the private repository's workflow was disabled. The text below describes the state before removal.


The manifests are in `clusters/titania/apps/llm-eval/` and `clusters/titania/bootstrap/apps/llm-eval.yaml`. The harness is in the private `kmjayadeep/homelab-llm-evals` repository and starts in `sampling` mode. `full` mode requires the supervised handoff check in plan 0013 phase 1. This ADR does not prove live state; check `flux get ks -n llm-serving` and the workflow history.
