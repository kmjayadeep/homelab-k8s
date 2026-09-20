# LLM gateway

The public OpenAI-compatible endpoint is `https://llm-gateway.cosmos.cboxlab.com/v1`.
Clients select the stable `chat-default` alias; its vLLM backend can be changed
without changing the client base URL.


The prepared `chat-smollm2-code` alias expects a future
`InferenceService/smollm2-135m-code-vllm`, whose predictor Service will be
`smollm2-135m-code-vllm-predictor`. Configure that vLLM deployment with
`--served-model-name=chat-smollm2-code` before testing the alias.

After validation, switch `chat-default` to the candidate by changing only its
`AIGatewayRoute` backend reference. Clients retain `model: chat-default` and
the same base URL.
