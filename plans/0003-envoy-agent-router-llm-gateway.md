# Plan 0003: Complete the Envoy Agent Router LLM gateway rollout

- Status: In progress
- Date: 2026-09-20
- Scope: KServe vLLM exposed through Envoy Gateway and Agent Router (formerly Envoy AI Gateway)

## Goal

Provide one TLS-protected OpenAI-compatible endpoint at
`https://llm.cosmos.cboxlab.com/v1`. Clients use stable aliases such as
`chat-default`; model backend changes do not require a client endpoint change.

## Current implementation

- LiteLLM GitOps manifests and its Vault Kubernetes-auth role were removed.
- Envoy Gateway `v1.8.1` and Agent Router `v1.0.0` are declared through Flux.
- `chat-default` routes to the KServe vLLM predictor Service.
- vLLM is configured to serve the `chat-default` alias.
- The gateway validates an API key materialized from Vault at
  `apps/llm-gateway/core` property `api_key`.
- The controller security-context fix is on
  `fix/agent-router-controller-security-context`; it must be merged before the
  rollout can continue.

## Remaining rollout steps

### 1. Merge the controller fix

Merge `fix/agent-router-controller-security-context` through the normal review
path. It removes the explicit `runAsNonRoot` setting that Kubernetes rejected
because the controller image declares a non-numeric `nonroot` user.

Confirm the Agent Router controller pod becomes Ready. Do not inspect pod logs
for this check; use pod readiness and event metadata only.

### 2. Provision the gateway API key

1. Add one client API key to Vault at `apps/llm-gateway/core`, property
   `api_key`, using the approved non-logging secret-import workflow.
2. Apply the `homelab-iac` Terraform change that creates the least-privilege
   `llm-gateway` Vault Kubernetes-auth role.
3. Confirm the `llm-gateway` `SecretStore` and `ExternalSecret` are Ready using
   status conditions only. Never read the generated Secret value.

The endpoint must not be considered available until API-key enforcement is
active.

### 3. Verify Flux resources and TLS

After the required Git changes are merged and Flux has reconciled:

- Confirm Envoy Gateway, Agent Router CRDs/controller, the Gateway, and the
  generated Envoy data-plane workload are Ready.
- Confirm the reflected `cosmos-cboxlab-cert` is available in `llm-gateway` and
  that the HTTPS listener is programmed.
- Confirm ExternalDNS publishes `llm.cosmos.cboxlab.com` for the generated
  LoadBalancer Service.
- Confirm the KServe vLLM predictor Service remains Ready before testing the
  gateway.

Use resource status, conditions, and object names only; do not expose API keys
or request content in diagnostics.

### 4. Exercise the client contract

From an approved client environment, test:

- `GET /v1/models` includes `chat-default`.
- Authenticated `POST /v1/chat/completions` succeeds with `model` set to
  `chat-default`.
- An unauthenticated request is rejected.
- An unknown model alias is rejected.
- Server-sent-event streaming completes without a gateway timeout.

Use a non-sensitive test prompt and ensure shell commands do not place the API
key in history or command arguments.

### 5. Add model experiments incrementally

For each candidate model:

1. Deploy a separate KServe `InferenceService` with resource requests, limits,
   and probes.
2. Add a cluster-local Envoy `Backend` and `AIServiceBackend`.
3. Add a distinct stable route alias, for example `chat-experimental`.
4. Validate direct KServe readiness, then gateway non-streaming and streaming
   behavior.
5. Change `chat-default` only after the candidate is accepted; retain the prior
   backend as a rollback target until the observation period ends.

Do not add provider fallbacks, weighted routing, token quotas, or llm-d
InferencePools until the single-backend route is stable.

### 6. Observability and access hardening

- Add Prometheus discovery for Envoy Gateway and Agent Router metrics.
- Build dashboards for request count, response status, duration, and time to
  first token. Do not record prompts, completions, or authorization headers.
- Review whether network allowlists, mTLS, or a dedicated identity provider are
  needed in addition to API-key authentication.
- Set explicit request-size and timeout limits after observing normal workload
  characteristics.

### 7. Retire residual LiteLLM data only after verification

After the gateway has operated successfully through an agreed observation
window:

- Confirm no client or Flux resource references LiteLLM.
- Obtain separate explicit approval before deleting the retired Vault values,
  PostgreSQL role/database, or other persistent LiteLLM data.
- Do not delete those values as part of rollback; a rollback should restore a
  known-good gateway or application configuration first.

## Validation requirements

For every manifest update:

```bash
kustomize build clusters/titania/apps/llm-gateway | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/apps/llm-serving | kubectl apply --dry-run=client -f -
```

The first command requires Agent Router and Envoy Gateway CRDs to be installed.
Before that point, a missing-CRD validation failure is expected and must be
reported rather than ignored.
