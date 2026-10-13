# LiteLLM

LiteLLM is the only entry point to local models. Clients (Open WebUI, OpenClaw, Pi) use `https://litellm.cosmos.cboxlab.com` with LiteLLM keys. The inference servers in `llm-serving` have no authentication and no Ingress. No NetworkPolicy restricts them, so any in-cluster pod can still reach them directly.

## Current model

| LiteLLM name | Backend Service | Model | Limits |
|---|---|---|---|
| `qwen-intel` (alias) → `tiel-coder-35b-a3b-intel` | `intel-llama-tiel-coder-trial.llm-serving:8080` | Tiel-Coder 35B-A3B IQ4_XS + BF16 mmproj, llama.cpp SYCL, MTP | 114,688 input + 16,384 output (131,072 configured) |

- Capabilities: chat, reasoning, vision. Function calling is advertised as `false` until tool reliability is tested more broadly.
- Known limits: one benign image request passed. Near-limit context, sustained load and the MTP speedup are untested, and the first 128K pod was evicted for host-memory pressure. See [plan 0008](../../../../plans/0008-tiel-coder-b60-trial.md#128k-vision-follow-up).
- Clients should use `qwen-intel`, not the versioned name, so the model can be changed without reconfiguring clients.

## Pricing

Every local entry uses the same **internal accounting rates**. They are not actual cost: $0.10/1M uncached input, $0.01/1M cache-read input, and $1.00/1M output, set in `model_info`. Cache reads are discounted only if the backend reports `prompt_tokens_details.cached_tokens`.

## Switching models

The B60 has room for one inference Deployment at a time (`gpu.intel.com/xe: 1`; a second pod stays Pending).

1. Add the new backend (Deployment, Service, PVC) in `clusters/titania/apps/llm-serving-intel-llama/` at zero replicas, and add a versioned `model_list` entry with the exact served alias, limits and pricing.
2. Scale the current backend to zero and confirm its pod has exited. Then scale the new one to one and wait for Ready. Use separate commits.
3. Send a benign request to the versioned LiteLLM name.
4. Point `router_settings.model_group_alias.qwen-intel` at the new entry.
5. Remove the old backend and its `model_list` entry, or keep them stopped if you need a rollback.

## Alias drift (`STORE_MODEL_IN_DB=True`)

LiteLLM persists Router Settings in its database. A persisted `model_group_alias` can override the HelmRelease value after a Helm upgrade, and this has happened before. After any alias change:

- check `GET /router/settings` (`current_values.model_group_alias`) and `/model/info`
- if the alias is stale, send the **complete** alias map with an authenticated `POST /config/update`
- send a benign request through `qwen-intel`

Prefer the Git-managed alias over editing Model Group Alias Settings in the Admin UI. Never print keys or config values while checking.

## History

Previous selections and trial evidence:

- Qwen3.6/Qwen3.8 and vLLM: [B60 evaluation](../../../../plans/0005-intel-arc-b60-llm-serving-evaluation.md)
- Swift: [plan 0009](../../../../plans/0009-swift-qwen38-b60-trial.md) and [plan 0010](../../../../plans/0010-swift-qwen38-concurrency.md)
- Empero: [plan 0011](../../../../plans/0011-empero-qwen38-distill-b60-trial.md)
- Tiel 80K and 128K: [plan 0008](../../../../plans/0008-tiel-coder-b60-trial.md)

The serving manifests for those trials were removed from Git; recover them from history if needed.
