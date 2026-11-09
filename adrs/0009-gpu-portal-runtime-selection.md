# ADR 0009: Select the B60 owner at runtime through a portal

- Status: Proposed
- Date: 2026-11-09
- Related plan: [0030 GPU portal](../plans/0030-gpu-portal.md)
- Amends: [ADR 0008](0008-comfyui-b60-timeshare.md) (switching through `replicas` PRs is replaced)

## Context

ADR 0008 switches the single B60 between Ornith and ComfyUI with one PR per switch, so Git always shows the running state. The operator wants to switch on demand from a phone, with no workstation, and see what is running and how much VRAM it uses.

## Decision

- Git holds the catalog of validated configs: their workloads, and `portal/configs.json`.
- The active choice is a `gpu-active` ConfigMap in each workload namespace. Flux `substituteFrom` reads the ConfigMap in the Kustomization's own namespace, so there is one per namespace. Flux creates each only if absent (`ssa: IfNotPresent`) and never overwrites it.
- Each Flux Kustomization patches `spec.replicas` to a variable with a safe default. Plain `replicas` values stay in the manifests so CI schema validation still passes.
- The portal changes only those ConfigMaps and requests a reconcile. Flux remains the only actor that changes workloads.
- The portal's ServiceAccount is limited by `resourceNames` to those ConfigMaps, Kustomizations and Deployments, plus listing pods in the two namespaces.
- `-shared-dev-num` stays 1, so the scheduler still prevents two GPU workloads running at once.
- Basic auth from Vault protects the portal, `imagine` and `comfyui`.

## Alternatives considered

- **A Git commit per click.** Keeps history and keeps Git as the record of what runs. Rejected because the portal would hold write access to a repository Flux applies, on an unprotected `main`, so compromising the portal would compromise the cluster.
- **The portal scaling Deployments directly.** Rejected because Flux would have to stop owning `replicas`, and a mistake could leave workloads outside reconciliation.
- **A PR per switch (ADR 0008).** Needs a workstation or GitHub for each switch.

## Consequences

- Git no longer shows which config is active. Check the portal or the `gpu-active` ConfigMaps.
- A cluster rebuild restores the defaults: Ornith at 1, ComfyUI at 0.
- `gpu-stats` runs with `hostPID` and `SYS_PTRACE` on the GPU node, because the xe driver's per-process fdinfo is the only in-cluster VRAM source found.
- The portal authenticates callers only at the Ingress. A pod inside the cluster could call its Service and switch between catalog entries.
- The portal refuses to switch while a Kustomization is suspended, which covers autoresearch sessions (ADR 0006). Start an autoresearch session only while Ornith is active.

## Implementation status

Manifests are proposed in plan 0030. Check `kubectl -n gpu-portal get deploy,ds` and `flux get ks -n gpu-portal` for live state.
