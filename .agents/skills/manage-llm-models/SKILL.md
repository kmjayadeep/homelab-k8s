---
name: manage-llm-models
description: Add, replace, evaluate, or troubleshoot local LLM models in this homelab's KServe, vLLM, local model cache, and Envoy AI Gateway stack. Use for model selection, CPU or AMD GPU sizing, tool calling, model aliases, Flux rollout readiness, and stale cache recovery.
---

# Manage homelab LLM models

## Scope and safety

Resolve repository paths below from the repository root (`git rev-parse --show-toplevel`), not from this skill directory. Read `AGENTS.md` and inspect current manifests/status before acting; this skill is not a snapshot of live state.

- Never display plaintext secrets, environment dumps, raw pod specs, or unfiltered logs. Use narrowly selected non-secret metadata, readiness conditions, and error classifications. Quote JSONPath/custom-column arguments; malformed JSONPath can dump the full object on error. Prefer JSON piped to a strict allowlist filter for complex extraction.
- Keep model credentials in existing Vault/External Secrets integrations. Before changing credentials, stores, ESO, Reloader, or secret paths, read the ADR, both migration plans, and sibling `homelab-iac/vault-config/PATHS.md` as required by `AGENTS.md`.
- Repository edits do not authorize live apply/reconcile, commits, or pushes. Obtain explicit authorization for each relevant action; use the `commit-push` skill when requested. Pushing to the watched branch can trigger deployment.
- Deletion, pruning, force operations, and destructive replacement require explicit approval with the impact explained. Never delete cache files, PVCs, or PVs as a speculative fix.
- Do not disable health checks or fabricate readiness to bypass a problem.

## Architecture map

| Concern | Repository location |
| --- | --- |
| InferenceServices and resource sizing | `clusters/titania/apps/llm-serving/` |
| Per-model caches, shared node group, download runtime | `clusters/titania/infra/kserve-localmodel/` |
| CPU serving runtime Helm configuration | `clusters/titania/infra/kserve/helm-release-runtimes.yaml` |
| AMD ROCm serving runtime | `clusters/titania/infra/kserve-rocm/` |
| Public aliases, Backend, AIServiceBackend, AIGatewayRoute | `clusters/titania/apps/llm-gateway/` |
| Cache Flux dependency and health expressions | `clusters/titania/bootstrap/infra/06-kserve.yaml` |
| Serving Flux dependencies | `clusters/titania/bootstrap/apps/llm-serving.yaml` |

Important relationships:

- An InferenceService `storageUri` selects a cache by matching its `sourceModelUri`, including the revision. Resource names alone do not select the cache.
- LocalModelCache is cluster-scoped. LocalModelNode tracks models per node; LocalModelNodeGroup selects cache nodes and defines local storage.
- `llm-serving` depends on `kserve-localmodel`. An unhealthy old cache can block deployment of an unrelated new model.
- The cache Flux Kustomization uses `wait: true` and a 15-minute timeout, requiring `copies.total > 0` and `copies.available == copies.total`. Check the current manifest for changes.
- Serving Flux currently uses `wait: false`: Flux Ready is not proof that a predictor is ready.
- Public endpoint: `https://llm-gateway.cosmos.cboxlab.com/v1`. Inspect routes for current aliases and overrides.

## 1. Clarify the model change

Determine whether the user wants an additional model/alias, a replacement behind an existing alias, or just research. Confirm parameter budget, CPU versus GPU, context length, concurrency, and tool-calling needs.

- Do not recommend a 7B model when the requested class is roughly 100M parameters.
- Read model cards and inspect artifact filenames/configuration before recommending deployment. Pin Hugging Face models to an immutable commit with the existing `hf://owner/model:commit` convention.
- Check architecture, tokenizer/chat template, license, artifact format, and installed runtime compatibility. Standard safetensors checkpoints are the simplest fit here. GGUF-only models are not a drop-in assumption; assess runtime support explicitly.
- Distinguish publisher claims from independently tested capability. Abliteration can change output quality; lower refusal counts do not prove better reasoning, coding, or tool use.
- Do not enable remote model code or execute publisher-provided scripts without reviewing the need and obtaining approval.

Sizing:

- Approximate BF16 weight memory as parameters × 2 bytes. Add runtime overhead, KV cache, context/concurrency headroom, and download/storage needs.
- Kubernetes memory limits describe host RAM, not GPU VRAM. `amd.com/gpu: 1` allocates a device, not a VRAM quantity. Verify actual GPU model/VRAM and node availability; never infer 20 GiB VRAM from `memory: 20Gi`.
- Keep CPU models on the CPU runtime; the ordinary CUDA image is not suitable for a CPU-only node. Confirm ROCm support for the actual AMD GPU.
- Inspect node selectors, taints/tolerations, and stop annotations. `serving.kserve.io/stop: "true"` can be intentional; do not resume it implicitly.

## 2. Add a separate pinned cache

**Preserve existing caches when adding a different model.** Do not repoint the original cache to a derivative. Treat source URI as immutable and check the installed CRD before changing it.

1. Add `local-model-cache-<model>.yaml` under `infra/kserve-localmodel/`.
2. Give it a distinct name and standard labels, including name, instance, component `model-cache`, and part-of `kserve`.
3. Set `sourceModelUri` to the exact pinned URI intended for the InferenceService.
4. Select the existing node group if appropriate. Budget `modelSize` using actual artifact size plus headroom, and check aggregate reservations against group storage capacity. Do not blindly copy an oversized reservation.
5. Add the file to that directory's `kustomization.yaml`.
6. Reuse the shared download container and credential references; do not duplicate tokens.

Example learned here: original `smollm2-135m` and derivative `smollm2-135m-heretic` are separate caches. Heretic uses the same architecture but different weights and a different URI.

The shared downloader currently disables HF Xet because it crashed on the CPU. Preserve this workaround unless deliberately tested. The node group's local PV path must match the node agent's hostPath, and directory ownership must support the downloader UID/GID. Never recursively change ownership as an unapproved troubleshooting shortcut.

## 3. Wire the predictor and gateway

- For a replacement, retain the desired service identity and stable served-model alias; change the pinned URI and only the necessary configuration.
- For an additional model, create a distinct InferenceService and add it to the app Kustomization. Budget simultaneous resource usage.
- Set resource requests/limits and verify effective startup/readiness/liveness probes in the runtime. Allow enough startup time for download/model loading. Avoid unrelated runtime changes.
- Existing predictors use Recreate: replacing one can interrupt service while it restarts. Warn about this before live rollout.
- Add/update the gateway Backend hostname (`<inferenceservice>-predictor.llm-serving.svc.cluster.local`), AIServiceBackend, and route when introducing an alias.
- Update `clusters/titania/apps/litellm/helm-release.yaml` for every model LiteLLM should expose. Its `model_name` and `litellm_params.model` must match the serving runtime's `--served-model-name`; set the exact internal service URL and port in `api_base`.
- Add LiteLLM `model_info.max_input_tokens` and `model_info.max_output_tokens` that together do not exceed the runtime context window. For a 64K server with a 16K generation budget, use 49,152 input and 16,384 output tokens.
- Record supplied model pricing in LiteLLM under `litellm_params` as USD per token: `input_cost_per_token`, `cache_read_input_token_cost`, and `output_cost_per_token`. Convert any per-million-token price by dividing it by 1,000,000; do not invent costs when none are supplied.
- Route `modelNameOverride` must match the backend's `--served-model-name`; do not confuse the public alias with the internal name.
- Inspect shared aliases: `chat-smollm2-code` historically shares the `chat-default` backend and is not evidence that a separate code model exists. Changing that predictor affects both aliases.
- Update the gateway README with client selection and any limitations.

### Tool calling

Enable only when supported by the particular model and installed vLLM version. Check official documentation, not just the model family name.

- Qwen2.5 Instruct: `--enable-auto-tool-choice` and `--tool-call-parser=hermes`; its bundled template supports Hermes-style tools.
- Official SmolLM2 tool support is documented for 1.7B, not the deployed 135M variant. Flags cannot manufacture tool capability.
- Modified/abliterated weights need their own reliability tests even if the tokenizer/template remains compatible.
- Clients send `tools` and `tool_choice`; clients execute tools. Verify returned names/arguments without automatically executing them.

## 4. Validate, then deploy only when authorized

Run relevant builds and client dry-runs, using `set -o pipefail` so build failures are not masked:

```bash
set -o pipefail
kustomize build clusters/titania/infra/kserve-localmodel | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/llm-serving | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/litellm | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/llm-gateway | kubectl apply --dry-run=client -f -
git diff --check
```

Validate infrastructure runtime Kustomizations too if changed. Client dry-run does not prove admission acceptance, hardware compatibility, download success, or inference quality.

Before commit/push, review the complete diff and preserve unrelated user changes. After authorized deployment, verify in this order:

1. Flux Git source has the expected commit.
2. Cache Kustomization actually attempted/applied that commit, not an earlier one.
3. The new cache exists and all intended copies are downloaded.
4. Serving Kustomization applied the intended URI.
5. Predictor is Ready and pod is running with the expected rollout.
6. A small, benign request through the public alias succeeds. Report response status/latency without dumping potentially sensitive conversation content. Use existing non-logging authentication if needed; never expose credentials in arguments or output.

Useful read-only checks:

```bash
flux get sources git -n flux-system
flux get kustomizations -n kserve
flux get kustomizations -n llm-serving
kubectl get localmodelcaches -o 'custom-columns=NAME:.metadata.name,AVAILABLE:.status.copies.available,TOTAL:.status.copies.total'
kubectl get localmodelnodes -o 'custom-columns=NAME:.metadata.name,DELETING:.metadata.deletionTimestamp'
kubectl get nodes -o 'custom-columns=NAME:.metadata.name'
kubectl get pods -n llm-serving -o 'custom-columns=NAME:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,WAITING:.status.containerStatuses[*].state.waiting.reason'
```

When explicitly authorized, reconcile cache first, then serving, and verify actual predictor readiness:

```bash
flux reconcile kustomization kserve-localmodel -n kserve --timeout=3m
flux reconcile kustomization llm-serving -n llm-serving --timeout=3m
kubectl wait --for=condition=Ready inferenceservice/<name> -n llm-serving --timeout=180s
```

A command timeout is not proof of deployment failure. Recheck status. Avoid fragile parsing of human-readable Flux output; use named JSON fields for automation.

## 5. Troubleshooting cache/Flux stalls

### New cache is absent despite a push

Check source revision and Kustomization condition messages. Flux can still be inside the previous revision's 15-minute health check. Fetching the commit does not mean it has applied the resource. Requesting reconciliation may not interrupt an already-running health check.

### Cache says 1/2 but only one node remains

Inspect these non-secret status fields, substituting verified names:

```bash
kubectl get localmodelcache <cache> -o jsonpath='{.status.nodeStatus}{"\n"}{.status.copies}{"\n"}'
kubectl get localmodelnode <worker> -o jsonpath='{.status.modelStatus}{"\n"}'
```

Compare Kubernetes node membership, LocalModelNode objects, cache `nodeStatus`, and agent model status. Do not assume an temporarily absent worker is permanently retired; ask whether it will return.

Observed failure: a deleted worker's `NodeDownloadPending` entry remained in the cache status even after its LocalModelNode was deleted. The surviving worker reported `ModelDownloaded`, but stale `copies.total: 2` kept Flux blocked. **Deleting the stale LocalModelNode alone did not fix this.**

Recovery sequence:

1. Confirm the worker is retired, the surviving worker really downloaded the model, and controllers/agents are healthy. Inspect selected scheduling/readiness metadata and safely filtered error evidence if needed; never dump raw credential-bearing logs.
2. Obtain approval before deleting a stale LocalModelNode; explain that this is controller metadata, and do not delete model files or volumes.
3. Wait briefly for controller reconciliation. If stale status persists, diagnose controller behavior rather than repeatedly deleting resources or restarting controllers blindly.
4. As an explicitly approved last-resort repair, patch only the cache **status subresource**. Use JSON Patch `test` operations for the exact observed pending entry, downloaded entry, available count, and total count before removing the retired-node entry and correcting the total. Derive all values from current evidence; never hardcode this incident's node names/counts or mark an undownloaded copy available. If a test fails, stop and re-read status.
5. Verify the corrected status remains stable and request Flux reconciliation. If it regresses, investigate the controller; do not automate recurring status patches.
6. An approved emergency apply may create only the new cache from the committed manifest while Flux is blocked. Verify the fetched source revision includes it to avoid drift/pruning, then return to normal GitOps ownership. This is not the default deployment path.

Adding a separate cache does not itself guarantee repair of another cache's stale status. Do not loosen global health requirements merely to get a green result.

Other checks:

- Pending GPU predictor: verify GPU node exists, labels match, taints are tolerated, and device resources are advertised. Missing node affinity is not a download failure.
- Download job failure: inspect exit codes/reasons, credential readiness (not values), disk capacity, permissions, network access, and pinned model availability.
- Duplicate downloads: verify node group PV path and agent hostPath match.
- Predictor crash: inspect model/runtime compatibility, memory limits, context/KV allocation, and startup probes before changing resources.

## Completion report

State changed paths, model/revision, cache name, public alias, validation results, and whether changes are only local, pushed, applied, predictor-ready, or end-to-end tested. Mention downtime, capability uncertainties, unresolved cache/controller issues, and rollback options. Preserve the previous cache and URI for rollback; never claim dry-run success means the model is running.
