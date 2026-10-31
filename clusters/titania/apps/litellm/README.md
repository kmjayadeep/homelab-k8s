# LiteLLM

LiteLLM is the only entry point to local models. Clients (Open WebUI, OpenClaw, Pi, kagent) use `https://litellm.cosmos.cboxlab.com` or the in-cluster Service with LiteLLM keys. The inference servers in `llm-serving` have no authentication and no Ingress. No NetworkPolicy restricts them, so any in-cluster pod can still reach them directly.

## Current model

| LiteLLM name | Backend Service | Model | Limits |
|---|---|---|---|
| `qwen-intel` (alias) → `ornith-1.5-35b-a3b-intel` | `intel-llama-ornith.llm-serving:8080` | Ornith-1.5 35B-A3B 21G-ICE + BF16 mmproj, n-gram speculation (plan 0015, tuned in plan 0014); served 2026-10-15 to 2026-10-25 and again since 2026-10-28 after the rollback from Swift Qwen3.8-27B ([plan 0018](../../../../plans/0018-b60-model-switch-baseline.md)). 44–46/49, 68 tok/s short, 27 at 100K. Named `tiel-coder-35b-a3b-intel` until 2026-10-28; Tiel-Coder was a requant of the same weights | 114,688 input + 16,384 output (131,072 configured) |

- Capabilities: chat, reasoning, vision, function calling. A `tools` request through `qwen-intel` returned a valid `tool_calls` response on 2026-10-17 and the autoresearch tool suite passes 8/8.
- Known limits: one benign image request passed. Near-limit context, sustained load and the MTP speedup are untested, and the first 128K pod was evicted for host-memory pressure. See [plan 0008](../../../../plans/0008-tiel-coder-b60-trial.md#128k-vision-follow-up).
- Clients should use `qwen-intel` or one of the routers below, not the versioned name, so the model can be changed without reconfiguring clients. `qwen-intel` never falls back to a paid provider.

## Routers

Plain model names that encode a policy. Clients (kagent `ModelConfig`s, Open WebUI, scripts) pick one; the backends behind them change in this file only. Added 2026-10-30/31.

| Router | Backends | How |
|---|---|---|
| `local-first` | local llama-server, then `deepseek-v4-flash` | Own `model_list` entry for the local server with `max_parallel_requests: 1` (the server runs one slot) and `stream_timeout: 120`; `router_settings.fallbacks` sends the call to the database-managed `deepseek-v4-flash` when the slot is busy, the first streamed token takes longer than 120 s or the backend is unreachable. Timeouts are not retried locally (`retry_policy.TimeoutErrorRetries: 0`); other errors get two quick retries first |
| `sensitive` | local llama-server only | `router_settings.model_group_alias` to the versioned entry, like `qwen-intel`; no limits, no fallback, requests queue at llama-server and fail if it is down. Nothing leaves the cluster. Subject to alias drift (below) |
| `frontier` | `deepseek-v4-flash` only | `router_settings.model_group_alias`; the DeepSeek key stays in LiteLLM's database. Subject to alias drift (below) |

`local-first` is the only router with its own `model_list` entry, because `max_parallel_requests` and `stream_timeout` are per-deployment settings: on an alias they would also throttle `qwen-intel` and `sensitive`, which have no fallback. It does not repeat the backend: its `litellm_params` merge the versioned entry's block through a YAML anchor (`<<: *local-backend`) and its `model_info` reuses `*local-model-info`, so the local URL, model name, limits and rates are written once. Kustomize expands anchors and merge keys in the build output (verified with kustomize 5.8.2).

Busy detection for `local-first` counts only requests LiteLLM routes through that group, so a slot held by `qwen-intel` or `sensitive` traffic is noticed only through `stream_timeout` (streamed calls) or `request_timeout` (600 s). A 100K-token cold prompt needs about 85 s of prefill, so raise `stream_timeout` before lowering it. The spend log shows which backend answered each call. Removing or renaming the `deepseek-v4-flash` database entry breaks both `local-first`'s fallback and `frontier`.

## Embeddings

`gemini-embedding-2` (Google Gemini API free tier, key at Vault `services/gemini/litellm`, Git-managed entry) serves `/v1/embeddings` at 768 dimensions for kagent agent memory. The entry caps itself below the free tier's reported 100 RPM / 30K TPM. Text sent for embedding leaves the cluster to Google.

## Pricing

Every local entry uses the same **internal accounting rates**. They are not actual cost: $0.10/1M uncached input, $0.01/1M cache-read input, and $1.00/1M output, set in `model_info`. Cache reads are discounted only if the backend reports `prompt_tokens_details.cached_tokens`.

## Switching models

The B60 has room for one inference Deployment at a time (`gpu.intel.com/xe: 1`; a second pod stays Pending).

1. Add the new backend (Deployment, Service, PVC) in `clusters/titania/apps/llm-serving-intel-llama/` at zero replicas, and add a versioned `model_list` entry with the exact served alias, limits and pricing.
2. Scale the current backend to zero and confirm its pod has exited. Then scale the new one to one and wait for Ready. Use separate commits.
3. Send a benign request to the versioned LiteLLM name.
4. Point `router_settings.model_group_alias.qwen-intel` and `sensitive` at the new entry and move the `&local-backend` and `&local-model-info` anchors to it, in the same commit. `local-first` follows the anchors; only its `max_parallel_requests` needs a look (it matches the server's `--parallel`).
5. Remove the old backend and its `model_list` entry, or keep them stopped if you need a rollback.

## kagent

kagent ([plan 0019](../../../../plans/0019-kagent-deployment.md)) reaches LiteLLM in-cluster with its own virtual key (alias `kagent`, Vault path `apps/litellm/kagent`). `clusters/titania/apps/kagent/model-config.yaml` defines one `ModelConfig` per router (`default-model-config` = `local-first`, plus `sensitive` and `frontier`); both agents use the default (before 2026-10-30 it was pinned to `deepseek-v4-flash`). External providers such as DeepSeek and Anthropic are configured in the LiteLLM Admin UI and stored in its database, not in this repository. Verify a router change with `GET /router/settings` (`fallbacks`, `retry_policy` and the alias map present) and the LiteLLM spend log for the `kagent` key. During a B60 autoresearch session `local-first` traffic runs on DeepSeek while `qwen-intel` restarts.

## Alias drift (`STORE_MODEL_IN_DB=True`)

LiteLLM persists Router Settings in its database and deep-merges them over the HelmRelease values at startup: a key stored in the database wins, a key never written through the UI or `/config/update` comes from Git (`fallbacks` and `retry_policy` were not stored as of 2026-10-30). A persisted `model_group_alias` overrides the HelmRelease value after a Helm upgrade; this happened on every alias change so far, most recently on 2026-10-25 (plan 0018 promotion: the alias kept pointing at the stopped Ornith backend and `qwen-intel` returned HTTP 500 until corrected). After any alias change:

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
