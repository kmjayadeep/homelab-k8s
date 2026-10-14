# Plan 0013: Nightly B60 LLM parameter evaluation

- Status: Implemented in Git, phase 0 (sampling mode) pending first nights
- Owner: Homelab operator
- Related ADR: [ADR 0005](../adrs/0005-nightly-b60-eval-handoff.md), [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md); related plans: [0007](0007-local-llm-performance-comparison.md), [0008](0008-tiel-coder-b60-trial.md)

## Goal and scope

Run an unattended GitHub Actions eval every night. Each night tests a different set of llama.cpp **server flags** or **request sampling parameters** for the model currently serving on the B60. It measures **quality and speed** and commits a report that is ready to read in the morning.

In scope:

- The private repository `kmjayadeep/homelab-llm-evals`, which holds the harness, tasks, results and `REPORT.md`.
- The cluster objects in `clusters/titania/apps/llm-eval/`.
- The nightly GPU handoff decided in [ADR 0005](../adrs/0005-nightly-b60-eval-handoff.md).

Out of scope:

- Switching models or downloading new artifacts.
- Contexts above 131072.
- Promoting a winning configuration automatically. Promotion stays a reviewed PR to `clusters/titania/apps/llm-serving-intel-llama/`.

## Starting state and prerequisites

Verified on 2026-10-14:

- **Production:** `intel-llama-tiel-coder-trial` is the only B60 workload, running Tiel-Coder 35B-A3B IQ4_XS with MTP and `--spec-draft-n-max 3`, Q8 K/V, 131072 context and one slot.
  - The Flux Kustomization `llm-serving/llm-serving-intel-llama` uses `wait: true` with a 15m interval.
  - After the checksum init container, the server loads in about 60 s.
  - A smoke request measured about 45 tok/s decode and about 700 tok/s prefill, and its timings reported MTP draft acceptance.
- **Runner image:** `ghcr.io/kmjayadeep/actions-runner` provides Python 3.12 with the standard library only, git, curl, jq, Docker (through the dind sidecar) and tzdata. It has no kubectl and no pip. The workflow installs a checksum-pinned kubectl 1.33.0.
- **Cluster services:** Cilium enforces NetworkPolicy. Prometheus exposes `node_memory_MemAvailable_bytes{instance="192.168.1.145:9100"}` for `titania-gpu`. There is no B60 VRAM metric, so VRAM is not reported.
- **`llm-serving` contents:** the namespace holds the wildcard TLS Secret `cosmos-cboxlab-cert`. This is why runner-created Jobs are constrained by the admission policy.
- **Window:** the operator chose 02:00–04:00 Europe/Berlin (CEST/CET) and will make overnight `qwen-intel` consumers skip it.
- **Approvals:** on 2026-10-14 the operator approved creating the private repository and the supporting cluster objects ("create repo and whatever necessary").

Still to verify after merge:

- The ARC GitHub token can register a runner for the new repository.
- The admission policy admits the eval Job and rejects other Jobs.
- Flux reapplies the Deployment's replicas on resume.

## Design as implemented

**Cluster side** (`clusters/titania/apps/llm-eval/`, Flux Kustomization `llm-serving/llm-eval`):

- **Runner:** `RunnerDeployment homelab-llm-evals` with labels `cosmos` and `llm-eval`, ServiceAccount `llm-eval-runner`, and resource limits on both the runner and dind containers.
- **Runner Role in `llm-serving`:**
  - `get` and `patch` on the serving Kustomization
  - `get` on the Deployment, and `get`, `patch` and `update` on its scale subresource
  - create, get, list, watch and delete on Jobs
  - read access to Pods and Pod logs
  - nothing cluster-wide and no Secrets
- **`ValidatingAdmissionPolicy llm-eval-server-jobs`:** runner-created Jobs must be named `llm-eval-server-*` and use the digest-pinned llama.cpp image. Only the model-cache PVC and emptyDir volumes are allowed. No ServiceAccount token, no env `valueFrom`/`envFrom`, and no privilege or host namespaces.
- **Service `llm-eval`:** fronts whichever eval Job is running. Its labels differ from production so `intel-llama-metrics` and the existing llama.cpp alerts never select eval pods.
- **CronJob `llm-eval-watchdog`:** runs at 03:50 Europe/Berlin and only resumes a Kustomization carrying the eval marker annotation.
- **PrometheusRule `llm-eval`:** fires `LlmEvalProductionNotRestored` (production unavailable for more than 2h15m) and `LlmEvalServerLingering`.

**Harness** (`kmjayadeep/homelab-llm-evals`):

- **Schedule:** two UTC crons, `25 23` and `25 0`. `evalctl window` lets through only the one that lands at 01:25 local. It then waits until 02:00, refuses to start after 02:20, and refuses a second run on the same night.
- **One experiment per night**, taken from `experiments/queue.json`. A production baseline always runs first, followed by up to two variants. Variants that share server flags reuse one server load. The order is speed, tools, longctx, homelab, then code, so a deadline still leaves speed numbers. New configs stop starting at 03:35.
- **Allowlist** (`evalctl/params.py`):

  | Parameter | Allowed |
  | --- | --- |
  | `--spec-type`, `--spec-draft-n-max` | 1–8, or removed |
  | `--batch-size` | 256–4096 |
  | `--ubatch-size` | 64–2048 |
  | `--cache-type-k`, `--cache-type-v` | q4_0, q8_0, f16 (q4_0 and f16 are gated) |
  | `--flash-attn` | on, off (gated), auto |
  | `--ctx-size` | 32768–131072 |
  | Sampling | temperature, top_p, top_k, min_p, presence/repeat penalty, thinking on/off, max_tokens, each within bounds |

- **Suites:**
  - speed: 3 depths × 2, prompt cache off
  - tool calls: 8
  - long-context retrieval: 3 needles in about 16K tokens
  - homelab manifests: 8
  - HumanEval+ coding tasks: 20, fixed-seed subset
- **Sandbox (changed from the draft):** model-generated code and YAML checks run in the runner's dind sidecar, not in a separate namespace. The HumanEval+ tests need numpy and are up to 300 KB each, which rules out a ConfigMap-fed pod. The container runs with `--network none`, a read-only root filesystem, a noexec tmpfs, no capabilities, `no-new-privileges`, UID 65534, 1 GiB of memory, 256 PIDs and a 60 s per-program timeout. Verified locally: all 20 canonical solutions pass, wrong answers fail, and outbound network is unreachable.
- **Guard:** polls Prometheus every 10 s and stops the night if available memory drops below 2 GiB, if memory goes unobservable for more than 60 s, or if the eval container is OOMKilled, terminates or restarts.
- **Steps that always run after the experiment:** restore, then grade in the sandbox, then regenerate `REPORT.md` and write the job summary, then commit `results/`. Raw completions are uploaded as a 30-day artifact.
- **Report:** per-variant quality and speed tables, a paired exact McNemar test against the same night's baseline, a baseline noise-floor history, and earlier nights.

## Steps and gates

1. **Phase 0: sampling mode** (repository variable `EVAL_MODE=sampling`, the current setting). Merge the cluster PR, then confirm:
   - the runner registers
   - `kubectl auth can-i` shows no Secret access for the runner
   - the first scheduled night commits a report

   Gate: 3 complete nights, with baseline spread recorded.
2. **Phase 1: supervised handoff.** Run `workflow_dispatch` with `mode=full` and `experiment=noise-floor` inside the window, or with `ignore_window` while consumers are paused. Watch Flux, the eval Job and memory. Gate:
   - production is restored with Flux Ready
   - the eval baseline matches the phase-0 baselines within noise
   - a deliberately cancelled run is recovered by the watchdog at 03:50

   Then set `EVAL_MODE=full`.
3. **Phase 2: low-risk server axes.** Run the MTP draft length, MTP off and batch-size experiments. Gate: no memory aborts, and minimum free RAM recorded for every config.
4. **Phase 3: gated axes.** After operator approval, set `EVAL_ALLOW_GATED=true` for the K/V cache experiments. Promote winners by manual PR, and update ADR 0004 when the serving flags change.

## Validation and rollback

- Validate manifests with `kustomize build clusters/titania/apps/llm-eval | kubectl apply --dry-run=client -f -`. A server-side dry-run on 2026-10-14 also accepted the admission policy's CEL.
- The harness CI runs `python3 -m unittest discover -s tests` before every run.
- **Stop nightly runs:** disable the workflow in the private repository. The watchdog and alerts stay in place.
- **Recover production manually** (needs approval like any other reconcile): `flux resume kustomization llm-serving-intel-llama -n llm-serving`, then delete leftover `llm-eval-server-*` Jobs.
- **Full rollback:** remove `clusters/titania/apps/llm-eval/` and `bootstrap/apps/llm-eval.yaml`. Pruning those resources is destructive and needs explicit approval.

## Outcome

Implemented in Git on 2026-10-14. Nothing has been verified live yet; record each phase gate here as it passes.
