# LLM gateway

The public OpenAI-compatible endpoint is `https://llm-gateway.cosmos.cboxlab.com/v1`.
Clients select the stable `chat-default` alias; its vLLM backend can be changed
without changing the client base URL.

API-key authentication is temporarily deferred. Do not expose this
unauthenticated endpoint beyond trusted network boundaries. Before general use,
restore the Vault-backed API-key policy; no secret value belongs in this
repository.

To add a model, create another `Backend` and `AIServiceBackend`, then add an
`AIGatewayRoute` rule for a new stable alias. Preserve the existing alias until
clients have migrated or its replacement has been validated.
