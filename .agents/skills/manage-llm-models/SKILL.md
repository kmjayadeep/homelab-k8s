---
name: manage-llm-models
description: Add, switch, tune, evaluate, or troubleshoot local LLMs served by llama.cpp SYCL on this homelab's single Intel Arc Pro B60 behind LiteLLM. Use for GGUF model selection and sizing, pinned/checksummed downloads, context/KV/MTP/vision flags, the one-GPU switch procedure, LiteLLM model entries and the qwen-intel alias, Flux rollout readiness, and memory/startup failures.
---

# Manage homelab LLM models

## Scope and safety

Resolve repository paths from the repository root (`git rev-parse --show-toplevel`), not from this skill directory. Read `AGENTS.md`, [ADR 0004](../../../adrs/0004-llamacpp-sycl-b60-behind-litellm.md) and the current manifests before acting. This skill is not a snapshot of live state.

- Never display plaintext secrets, environment dumps, raw pod specs, or unfiltered logs. Use narrowly selected non-secret metadata, readiness conditions and error classifications. Quote JSONPath/custom-column arguments, because malformed JSONPath can dump the full object.
- LiteLLM credentials live in Vault through External Secrets. Before changing credentials, stores, ESO, Reloader or secret paths, read the documents `AGENTS.md` requires.
- Repository edits do not authorize live apply/reconcile, commits or pushes. Obtain explicit authorization for each. Pushing to `main` deploys through Flux.
- Every serving change rolls the pod (`Recreate`) and interrupts `qwen-intel` while the model reloads. Say so before rollout.
- Deleting Deployments, PVCs or cached model files, pruning, and force operations need explicit approval with the impact explained. Never delete a cache as a speculative fix.
- Do not disable health checks, lower precision, or shrink context to hide a failure. Report the evidence and ask.

## Architecture map

| Concern | Location |
| --- | --- |
| Serving Deployment, Service, model-cache PVC | `clusters/titania/apps/llm-serving-intel-llama/` |
| Metrics Service, ServiceMonitor | same directory |
| Flux Kustomization and its Deployment health check | `clusters/titania/bootstrap/apps/llm-serving-intel-llama.yaml` |
| LiteLLM model list, `qwen-intel` alias, ingress | `clusters/titania/apps/litellm/helm-release.yaml` |
| Current model, switching, alias-drift notes | `clusters/titania/apps/litellm/README.md` |
| llama.cpp dashboard and alerts (`job="llama-cpp"`) | `clusters/titania/infra/monitoring/llama-cpp-*.yaml` |
| GPU device plugin | `clusters/titania/infra/intel-gpu-plugin/` |
| Client performance runner | `automation/llm-performance/` |
| Trial evidence | `plans/0005`, `0007`, `0008`–`0011` |

Key facts (verify against current manifests):

- `titania-gpu` has one B60 (23.91 GiB VRAM), **24 GiB host RAM** and 8 vCPUs. It carries the taint `workload=ai:NoSchedule` and the label `gpu.intel.com/product: arc-pro-b60`.
- The device plugin advertises `gpu.intel.com/xe: 1`. Only one inference pod can hold it; a second stays Pending.
- Serving pods are plain Deployments with no KServe and no authentication. There is no Ingress; clients go through LiteLLM. No NetworkPolicy restricts in-cluster access, so don't treat the Service as private.
- The Flux Kustomization uses `wait: true` with a 30-minute timeout and an explicit `healthChecks` entry naming the active Deployment. A first download can take most of that timeout.
- The metrics Service selects every pod labelled `app.kubernetes.io/component: inference` and `app.kubernetes.io/part-of: llm-serving`. Keep those labels so a new model is scraped automatically.
- Clients (Open WebUI, OpenClaw, local Pi) use LiteLLM at `https://litellm.cosmos.cboxlab.com` and the `qwen-intel` alias.

## 1. Choose and size the model

Confirm the goal with the user: coding vs. general use, needed context, vision, tool calling, and whether a live switch is acceptable.

- Use GGUF artifacts from a pinned Hugging Face commit. Read the model card and file list; check the architecture and chat template support in the pinned llama.cpp build, and check the license. Distinguish publisher claims from tested capability.
- MoE 35B-A3B class models at IQ3/IQ4 have been the practical fit, running at 128K–256K. Dense 27B models fit at 80–96K.
- `--spec-type draft-mtp` works only when the GGUF embeds MTP heads (look for an `-MTP` artifact). Flags cannot add MTP to a model without them.
- Vision needs the publisher's matching `mmproj` file from the same revision.
- VRAM budget is weights + KV (Q8 K/V at the configured context) + projector + runtime overhead. Keep at least ~1 GiB of GPU headroom.
- **Host RAM is the binding constraint.** A 128K Q8 trial once caused host OOM and lost k3s, and the first Tiel 128K pod was evicted for memory pressure. Set `requests.memory` near real usage; the kubelet evicts pods running above their request first.
- Kubernetes `memory` is host RAM, not VRAM. `gpu.intel.com/xe: 1` allocates a device, not a VRAM amount.

## 2. Add the serving resources

Copy the current Deployment's pattern rather than inventing a new one:

- **PVC:** `local-path`, `ReadWriteOnce`, sized for the artifacts plus room for a `.partial` download. Give each artifact its own PVC; never repoint an existing cache at different weights.
- **Init container:** use the pinned `curlimages/curl` digest. If the file exists, verify it with `sha256sum -c`. Otherwise download the `resolve/<commit>/<file>` URL to `*.partial`, verify the checksum, then `mv` it into place. Take the SHA-256 from HF file/LFS metadata, never from a local download you didn't verify.
- **Server image:** use an official `ghcr.io/ggml-org/llama.cpp` `server-intel` image pinned by index digest. Record the build number and oneAPI version in a comment.
- **Args:** `--model`, `--alias <versioned-name>` (must equal the LiteLLM model name), `--host 0.0.0.0`, `--port 8080`, `--metrics`, `--jinja`, `--ctx-size`, `--cache-type-k/v q8_0`, `--flash-attn on`, `--parallel 1`, `--n-gpu-layers 99`, plus `--mmproj` and MTP flags if applicable. Use the publisher's recommended sampling. Continuous batching is on by default, so don't add `--cont-batching`.
- **Pod:** `strategy: Recreate`, the node selector and toleration above, `gpu.intel.com/xe: 1` in requests and limits, CPU and memory requests/limits, a 2Gi memory-backed `/dev/shm`, and a `/health` startup probe with a long `failureThreshold` for model load plus readiness and liveness probes.
- **Labels:** standard name/instance labels plus `component: inference` and `part-of: llm-serving`.
- **Service:** port `http` 8080.
- Add the new files to the directory's `kustomization.yaml`.

Increase context step by step: configuring 128K is not evidence that a near-128K prompt is safe.

## 3. Wire LiteLLM

- Add a versioned `model_list` entry. `model_name` and `litellm_params.model` (`openai/<name>`) must match `--alias`. Use the internal URL `http://<service>.llm-serving.svc.cluster.local:8080/v1` and `api_key: not-used`.
- In `model_info`, keep `max_input_tokens + max_output_tokens` at or below `--ctx-size`; the usual split reserves 16,384 tokens for output.
- Set `supports_vision` or `supports_function_calling` to `true` only after a benign test through LiteLLM succeeds. Otherwise leave them `false`.
- Pricing goes in `model_info` as USD per token. Local entries reuse the internal accounting rates documented in the LiteLLM README; don't invent other costs.
- Remove entries whose backend no longer exists. Clients should see only models that can answer.

## 4. Switch the GPU owner (staged, approved)

Get explicit approval for the interruption, then use separate commits so Flux applies each stage:

1. Add the new PVC, Service and Deployment at `replicas: 0`, plus the versioned LiteLLM entry.
2. Scale the old Deployment to 0 and confirm its pod has exited and released the GPU.
3. Scale the new Deployment to 1 and point `healthChecks` in `bootstrap/apps/llm-serving-intel-llama.yaml` at it. Wait for the checksum init to exit 0 and the pod to be Ready with zero restarts.
4. Send a benign request to the **versioned** LiteLLM name.
5. Change `router_settings.model_group_alias.qwen-intel` and `sensitive` to the new entry and move the `&local-backend` and `&local-model-info` anchors to it; the `local-first` router entry follows them (check only its `max_parallel_requests`, equal to the server's `--parallel`).
6. Because `STORE_MODEL_IN_DB=True`, a persisted alias can override Helm values. Check `GET /router/settings`. If the alias is stale, send the **complete** alias map with an authenticated `POST /config/update`, then send a benign `qwen-intel` request.
7. Remove the old Deployment, Service, PVC and LiteLLM entry, with approval. Rollback means restoring them from git history.

Never declare two B60 Deployments at `replicas: 1`.

## 5. Validate, deploy and verify

```bash
set -o pipefail
kustomize build clusters/titania/apps/llm-serving-intel-llama | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/litellm | kubectl apply --dry-run=client -f -
git diff --check
```

A client dry-run does not prove the download, GPU compatibility, memory safety or quality.

After an authorized push, verify in this order:

1. The Flux source has the expected commit and `llm-serving-intel-llama` and `litellm` applied it.
2. The init container exited 0, the pod is Ready, and the restart count is 0.
3. Filtered logs show the SYCL device (`Arc ... B60`) and all layers offloaded, not a CPU fallback.
4. The node has no `MemoryPressure`, and GPU memory has headroom.
5. Benign text and, if enabled, image requests succeed through the versioned name and then `qwen-intel`. Report status and latency only, never content or credentials.

Read-only checks:

```bash
flux get kustomizations -n llm-serving
flux get helmreleases -n litellm
kubectl -n llm-serving get deploy,pods,svc,pvc
kubectl -n llm-serving get pods -o 'custom-columns=NAME:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,WAITING:.status.containerStatuses[*].state.waiting.reason,TERMINATED:.status.containerStatuses[*].lastState.terminated.reason'
kubectl get node titania-gpu -o 'custom-columns=NAME:.metadata.name,MEMPRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status,XE:.status.allocatable.gpu\.intel\.com/xe'
```

Performance comparisons use `automation/llm-performance/bench.py` against the versioned model ID (see its README). Run them only against a running backend, and only when approved.

## 6. Troubleshooting

- **Pod Pending:** another pod holds `gpu.intel.com/xe`, or the selector, toleration or labels don't match. Check `kubectl describe` events (filtered), not the logs.
- **Init failure:** a checksum mismatch means the wrong file or revision; don't "fix" it by deleting the cache. Also check HF availability, PVC capacity and node disk space.
- **Evicted / OOMKilled / node MemoryPressure:** host RAM. Look at the context size, the projector, and the memory request vs. actual use. Ask before reducing context or precision.
- **Crash at startup:** check that the pinned build supports the architecture or quantization, check MTP or projector compatibility, and check VRAM at the configured context. Compare against the last known-good image digest recorded in the plan.
- **Slow or queued requests:** with `--parallel 1`, requests queue behind live traffic. Check `llamacpp:requests_deferred` and the llama.cpp dashboard before blaming the model.
- **Alias points at the wrong model:** this is LiteLLM's persisted Router Settings (step 4.6), not Helm.
- **Flux Kustomization not Ready:** `healthChecks` may name a Deployment at zero replicas or one that was removed, or a first download may exceed the 30-minute timeout.

## Completion report

Report the changed paths, model and revision, image build, context and flags, and the LiteLLM names. Include validation results and what stage the change reached: local only, pushed, applied, Ready, or tested end to end. Also cover downtime, untested capabilities (near-limit context, tools, vision, MTP speedup), memory headroom, and the rollback commit. Record trial evidence in a plan, and update ADR 0004 or the LiteLLM README when the decision or current model changes.
