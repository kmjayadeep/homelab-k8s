# Plan 0030: GPU portal

- Status: Draft
- Owner: operator
- Related ADR: [ADR 0009](../adrs/0009-gpu-portal-runtime-selection.md)

## Goal and scope

Switch the B60 between validated configs from `gpu.cosmos.cboxlab.com`, and show the active config, VRAM, power, temperature and workload stats.

In scope: the portal, `gpu-stats`, Ornith and ComfyUI as catalog entries, and basic auth on the portal, `imagine` and `comfyui`. Out of scope: restoring Swift Q3_K_M, which needs its own PR and an ADR 0004 update because that ADR forbids stopped LLM Deployments.

## Starting state and prerequisites

Verified:

- `flux build` with the patches in this PR renders the right `replicas` and leaves the shell variables in ComfyUI's init script and nginx config unchanged.
- The Ornith pod's fdinfo reports `drm-resident-vram0`, and hwmon reports temperature, energy and fan.
- `portal/app.py` and `portal/gpu_stats.py` passed a local test against a stub Kubernetes API and a fake `/proc`.

Unverified until deployed: `gpu-stats` reading other processes' fdinfo with `hostPID` and `SYS_PTRACE`, and the RBAC in practice.

Approvals needed: the Terraform apply and password import below. Merging restarts nothing on the GPU, but it adds a login to `imagine` and `comfyui`.

## Steps and gates

1. **Vault.** Merge the `homelab-iac` PR, run `terraform apply` in `vault-config`, then import a generated password with `import-gpu-portal-ui-basic-auth.sh` over stdin. Gate: the metadata for `apps/gpu-portal/ui-basic-auth` exists. Do this first, because an Ingress whose auth Secret is missing returns 503.
2. **Merge this PR.** Gate: `flux get ks -n gpu-portal` Ready, `llm-serving-intel-llama` and `comfyui` Ready with unchanged replicas (Ornith 1, ComfyUI 0), `ui-basic-auth` Ready in both namespaces.
3. **Read-only check.** Log in. Gate: the page shows Ornith Ready and a plausible VRAM figure (about 23 GiB with Ornith loaded).
4. **Switch to ComfyUI and back.** Gate: each direction reaches Ready, the page shows each step, and `qwen-intel` answers through LiteLLM afterwards.
5. **Autoresearch lock.** Confirm the portal refuses to switch during the next real session. Do not suspend Flux just to test it.

## Validation and rollback

- Manifests: `kustomize build clusters/titania/apps/gpu-portal | kubectl apply --dry-run=client -f -`, and the same for `comfyui` and `llm-serving-intel-llama`.
- Rollback: revert the PR. The manifests return to plain `replicas` (Ornith 1, ComfyUI 0), whatever the portal last selected.
- If the portal is down, the active choice can be changed with `kubectl patch configmap gpu-active` in each namespace, followed by a Flux reconcile.

## Outcome

Not started.
