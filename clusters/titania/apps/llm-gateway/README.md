# LLM gateway

The public OpenAI-compatible endpoint is `https://llm.cosmos.cboxlab.com/v1`.
Clients select the stable `chat-default` alias; its vLLM backend can be changed
without changing the client base URL.

Before Flux reconciles this app, create `apps/llm-gateway/core` in Vault with an
`api_key` property through the approved non-logging secret-import workflow, and
apply the matching `llm-gateway` Vault Kubernetes-auth role from `homelab-iac`.
The key is sent by OpenAI-compatible clients as `Authorization: Bearer <key>`.
No secret value belongs in this repository.

To add a model, create another `Backend` and `AIServiceBackend`, then add an
`AIGatewayRoute` rule for a new stable alias. Preserve the existing alias until
clients have migrated or its replacement has been validated.
