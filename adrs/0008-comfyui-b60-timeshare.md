# ADR 0008: Time-share the B60 between the local LLM and ComfyUI

- Status: Proposed
- Date: 2026-11-09
- Related plan: [0029 ComfyUI on the B60](../plans/0029-comfyui-b60-timeshare.md)
- Amends: [ADR 0004](0004-llamacpp-sycl-b60-behind-litellm.md) (a second B60 Deployment exists in Git, at 0 replicas; "one inference Deployment" still holds for LLMs)

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM and 8 vCPUs. `intel-llama-ornith` holds the GPU and, per ADR 0004, idles at 82–93% VRAM because the 128K KV cache is preallocated. The same ADR records that VRAM exhaustion spills into host RAM outside the pod limit and has taken the node down (host OOM, k3s loss). The Intel GPU plugin runs with the default `-shared-dev-num=1`, so `gpu.intel.com/xe` is 1 and a second GPU pod cannot schedule.

Image generation on Battlemage is now a supported path: upstream ComfyUI runs on native `torch.xpu`, and Intel publishes `intel/llm-scaler-omni:0.2.0-b2`, a ComfyUI-only B60/B70 image with its own XPU attention and GEMM kernels, GGUF and nunchaku XPU loaders, and DynamicVRAM. Published estimates for the B60 are roughly 8 s for SDXL 1024² at 30 steps and 4–20 s for Flux variants; none of this is measured here yet.

## Decision

- Add `clusters/titania/apps/comfyui/` running the pinned Intel image as a plain Deployment with `gpu.intel.com/xe: 1`, a `local-path` model PVC filled by a checksum-verified init container (SDXL 1.0 base first), an Ingress at `comfyui.cosmos.cboxlab.com`, and `replicas: 0` in Git.
- Keep `-shared-dev-num=1`. The scheduler is the guard against co-residency; it is not a limitation to work around.
- Swap ownership for a session with `automation/gpu-owner/gpu-owner.sh`: suspend Flux for both apps with a marker, scale the LLM to 0 and ComfyUI to 1; hand back by scaling ComfyUI to 0 and resuming Flux, so Git state (LLM up) is the rollback. The same marker pattern as the autoresearch loop (ADR 0006), and the two refuse to take over each other's suspension.
- Open WebUI points its image-generation engine at the ComfyUI Service with the built-in checkpoint workflow. It works only while ComfyUI owns the GPU; chat is unaffected otherwise.

## Alternatives considered

- **Co-residency with `-shared-dev-num=2`.** Both pods would schedule, but Ornith would have to drop to about 32K context to leave VRAM, host RAM (24 GiB, Ornith limit 16 Gi, ComfyUI needs ~7 GiB to stage SDXL) does not fit both, and a spill repeats the documented node loss. Rejected.
- **Community images** (`yanwk/comfyui-boot:xpu`, `ghcr.io/haasanen/comfyui-arc`). Plain PyTorch XPU without Intel's kernels; Intel's own measurements and a third-party rebuild show the omni kernels ahead. Rejected for the default, acceptable fallback if the Intel image misbehaves.
- **Scaling through Git commits** (PR flips replicas). Slow for an interactive session and leaves Git describing a transient state. Rejected.
- **Giving the LLM a smaller context when ComfyUI is up.** Reconsider if image sessions become long and the LLM must stay reachable; `local-first` already falls back to DeepSeek.

## Consequences

- `qwen-intel` and `sensitive` are down during an image session; agents on them are degraded. `local-first` keeps working via its DeepSeek fallback.
- First ComfyUI start costs a 7 GB image pull and a 6.94 GB model download; later starts about a minute, plus 30–60 s to stage the checkpoint on the first generation.
- A second GPU Deployment in Git is a deliberate exception to ADR 0004's "exactly one"; it is not an LLM and is 0 replicas by default. The rule for LLM Deployments is unchanged.
- Performance, host-memory behaviour and OOM behaviour of the Intel image on this node are unmeasured until plan 0029 records them. Treat the published estimates as hypotheses.
- The Intel image runs as root and ComfyUI Manager can install nodes at runtime; those changes live in the pod's writable layer and vanish on restart. Reproducible node changes go through the image tag.

## Implementation status

Manifests, the swap script and the Open WebUI wiring are in this repository as of 2026-11-09 (plan 0029). Nothing has been applied to the cluster; check `flux get ks -n comfyui` and `kubectl -n comfyui get deploy,pvc` for live state.
