# LiteLLM

LiteLLM is the only entry point to local models. Clients (Open WebUI, OpenClaw, Pi, kagent) use `https://litellm.cosmos.cboxlab.com` or the in-cluster Service with LiteLLM keys. The inference servers in `llm-serving` have no authentication and no Ingress. No NetworkPolicy restricts them, so any in-cluster pod can still reach them directly.

## Current model

| LiteLLM name | Backend Service | Model | Limits |
|---|---|---|---|
| `qwen-intel` (alias) → `swift-qwen3.8-27b-q3km-intel` | `intel-llama-swift-qwen38-trial.llm-serving:8080` | Swift Qwen3.8-27B Q3_K_M (dense, embedded MTP draft 3, F16 projector, llama.cpp SYCL b11854) since 2026-10-25 ([plan 0018](../../../../plans/0018-b60-model-switch-baseline.md)). Measured: 43/49 on the autoresearch evaluator, 43–50 tok/s short decode, 14.6 at 100K, prefill 407–490, idle VRAM 82% | 114,688 input + 16,384 output (131,072 configured) |
| `tiel-coder-35b-a3b-intel` (versioned, rollback) | `intel-llama-tiel-coder-trial.llm-serving:8080` | Ornith-1.5 35B-A3B 21G-ICE + BF16 mmproj, n-gram speculation (plan 0015, tuned in plan 0014); served 2026-10-15 to 2026-10-25, now at zero replicas with its PVC. 44–46/49, 68 tok/s short, 27 at 100K | 114,688 input + 16,384 output |

- Capabilities: chat, reasoning, vision, function calling. On Swift, a `tools` request, a 32×32 image and the 8/8 tool suite passed through LiteLLM on 2026-10-24/25.
- Known limits: one benign image request passed. Near-limit context, sustained load and the MTP speedup are untested, and the first 128K pod was evicted for host-memory pressure. See [plan 0008](../../../../plans/0008-tiel-coder-b60-trial.md#128k-vision-follow-up).
- Clients should use `qwen-intel`, not the versioned name, so the model can be changed without reconfiguring clients.

## Embeddings

`gemini-embedding-2` (Google Gemini API free tier, key at Vault `services/gemini/litellm`, Git-managed entry) serves `/v1/embeddings` at 768 dimensions for kagent agent memory. The entry caps itself below the free tier's reported 100 RPM / 30K TPM. Text sent for embedding leaves the cluster to Google.

## Pricing

Every local entry uses the same **internal accounting rates**. They are not actual cost: $0.10/1M uncached input, $0.01/1M cache-read input, and $1.00/1M output, set in `model_info`. Cache reads are discounted only if the backend reports `prompt_tokens_details.cached_tokens`.

## Switching models

The B60 has room for one inference Deployment at a time (`gpu.intel.com/xe: 1`; a second pod stays Pending).

1. Add the new backend (Deployment, Service, PVC) in `clusters/titania/apps/llm-serving-intel-llama/` at zero replicas, and add a versioned `model_list` entry with the exact served alias, limits and pricing.
2. Scale the current backend to zero and confirm its pod has exited. Then scale the new one to one and wait for Ready. Use separate commits.
3. Send a benign request to the versioned LiteLLM name.
4. Point `router_settings.model_group_alias.qwen-intel` at the new entry.
5. Remove the old backend and its `model_list` entry, or keep them stopped if you need a rollback.

## kagent

kagent ([plan 0019](../../../../plans/0019-kagent-deployment.md)) reaches LiteLLM in-cluster with its own virtual key (alias `kagent`, Vault path `apps/litellm/kagent`). Its model is the `model` field of `clusters/titania/apps/kagent/model-config.yaml`, currently the database-managed `deepseek-v4-flash`; set it to `qwen-intel` to move kagent onto the local backend. External providers such as DeepSeek and Anthropic are configured in the LiteLLM Admin UI and stored in its database, not in this repository.

## Alias drift (`STORE_MODEL_IN_DB=True`)

LiteLLM persists Router Settings in its database. A persisted `model_group_alias` overrides the HelmRelease value after a Helm upgrade; this happened on every alias change so far, most recently on 2026-10-25 (plan 0018 promotion: the alias kept pointing at the stopped Ornith backend and `qwen-intel` returned HTTP 500 until corrected). After any alias change:

- check `GET /router/settings` (`current_values.model_group_alias`) and `/model/info`
- if the alias is stale, send the **complete** alias map with an authenticated `POST /config/update`
- send a benign request through `qwen-intel`

Prefer the Git-managed alias over editing Model Group Alias Settings in the Admin UI. Never print keys or config values while checking.

The evals key gets HTTP 403 on `/router/settings` and `/config/update`. The least-exposure way to run the fix is from inside the LiteLLM pod, where `PROXY_MASTER_KEY` is already in the environment: `kubectl -n litellm exec -i <pod> -- python3 -` with a script that reads `os.environ["PROXY_MASTER_KEY"]`, calls `http://127.0.0.1:4000` and prints only status codes and the alias map. The key never leaves the pod or enters shell history.

## History

Previous selections and trial evidence:

- Qwen3.6/Qwen3.8 and vLLM: [B60 evaluation](../../../../plans/0005-intel-arc-b60-llm-serving-evaluation.md)
- Swift: [plan 0009](../../../../plans/0009-swift-qwen38-b60-trial.md) and [plan 0010](../../../../plans/0010-swift-qwen38-concurrency.md)
- Empero: [plan 0011](../../../../plans/0011-empero-qwen38-distill-b60-trial.md)
- Tiel 80K and 128K: [plan 0008](../../../../plans/0008-tiel-coder-b60-trial.md)

The serving manifests for those trials were removed from Git; recover them from history if needed.
