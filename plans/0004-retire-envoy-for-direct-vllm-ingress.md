# Plan 0004: Retire Envoy LLM gateway for direct KServe vLLM ingress

- Status: Completed
- Date: 2026-09-20
- Scope: Remove Envoy Gateway, Envoy Agent Router, and their LLM Gateway resources. Use the existing KServe-generated vLLM ingress.

## Endpoint

The local-network OpenAI-compatible endpoint is:

`https://smollm2-135m-vllm-llm-serving.cosmos.cboxlab.com/v1`

Clients use `model: chat-default`, which is served directly by vLLM. No additional authentication is required because this endpoint is restricted to the local network.

## Changes

1. Remove the LLM gateway Flux Kustomization and all Gateway API, Envoy, and Agent Router route resources.
2. Remove Envoy Gateway and Agent Router Flux Kustomizations and Helm resources after their consumers are removed.
3. Remove the LLM UI dependency on the retired gateway.
4. Retain KServe, ingress-nginx, and the KServe-created direct ingress.
5. Remove unused ExternalDNS Gateway/HTTPRoute discovery and RBAC while retaining Ingress discovery.

## Rollout and verification

Reconcile through Flux only after approval. Confirm the direct KServe ingress, TLS, DNS, predictor readiness, and a non-sensitive `/v1/models` or completion request before and after retirement. Confirm Flux pruned the retired workloads and no Gateway API resources remain in use.

## Rollback

Restore the retired Git manifests and reconcile Envoy Gateway, Agent Router, and the LLM gateway in dependency order. The direct vLLM ingress remains available throughout.
