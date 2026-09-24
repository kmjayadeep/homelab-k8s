# Portkey AI Gateway

The OpenAI-compatible endpoint is `https://portkey.cosmos.cboxlab.com/v1`.

The public ingress supplies the Portkey OpenAI provider and exposes these
backend routes:

| Client base URL | Upstream | Model |
| --- | --- | --- |
| `https://portkey.cosmos.cboxlab.com/v1` | `smollm2-135m-vllm-predictor.llm-serving.svc.cluster.local/v1` | `chat-default` |
| `https://portkey.cosmos.cboxlab.com/intel-llama/v1` | `intel-llama.llm-serving.svc.cluster.local:8080/v1` | `qwen3.8-27b-intel` |

The gateway supplies a placeholder upstream API key; the current in-cluster
backends do not validate client API keys.

These are initial, single-backend routes. They have no client authentication,
rate-limiting, provider credentials, retries, or fallback configuration. Add
those controls before exposing them to untrusted clients or adding external
providers.
