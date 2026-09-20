# LLM gateway

The public OpenAI-compatible endpoint is `https://llm-gateway.cosmos.cboxlab.com/v1`.
Clients select the stable `chat-default` alias; its vLLM backend can be changed
without changing the client base URL.


`chat-smollm2-code` currently shares the `chat-default` vLLM predictor and
uses `modelNameOverride: chat-default`, so its route can be exercised before
the Code model is deployed. When
`InferenceService/smollm2-135m-code-vllm` is available, change its Backend
endpoint to `smollm2-135m-code-vllm-predictor` and remove the override after
vLLM is configured with `--served-model-name=chat-smollm2-code`.

After validation, switch `chat-default` to the candidate by changing only its
`AIGatewayRoute` backend reference. Clients retain `model: chat-default` and
the same base URL.

`qwen` routes to `Qwen2.5-7B-Instruct`, which has vLLM automatic tool
calling enabled with the Hermes parser. Clients can send OpenAI-compatible
`tools` and `tool_choice: "auto"` fields; tool execution remains the client's
responsibility.
