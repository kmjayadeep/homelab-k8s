# ADR 0008: Time-share the B60 between the local LLM and ComfyUI

- Status: Proposed
- Date: 2026-11-09
- Related plan: [0029 ComfyUI on the B60](../plans/0029-comfyui-b60-timeshare.md)
- Amends: [ADR 0004](0004-llamacpp-sycl-b60-behind-litellm.md) (a second B60 Deployment exists in Git and `replicas` selects which one runs; "one inference Deployment" still holds for LLMs)

## Context

`titania-gpu` has one Intel Arc Pro B60 (23.91 GiB VRAM), 24 GiB guest RAM and 8 vCPUs. `intel-llama-ornith` holds the GPU and, per ADR 0004, idles at 82–93% VRAM because the 128K KV cache is preallocated. The same ADR records that VRAM exhaustion spills into host RAM outside the pod limit and has taken the node down (host OOM, k3s loss). The Intel GPU plugin runs with the default `-shared-dev-num=1`, so `gpu.intel.com/xe` is 1 and a second GPU pod cannot schedule.

Image generation on Battlemage is now a supported path: upstream ComfyUI runs on native `torch.xpu`, and Intel publishes `intel/llm-scaler-omni:0.2.0-b2`, a ComfyUI-only B60/B70 image with its own XPU attention and GEMM kernels, GGUF and nunchaku XPU loaders, and DynamicVRAM. Published estimates for the B60 are roughly 8 s for SDXL 1024² at 30 steps and 4–20 s for Flux variants; none of this is measured here yet.

## Decision

- Add `clusters/titania/apps/comfyui/` running the pinned Intel image as a plain Deployment with `gpu.intel.com/xe: 1`, a `local-path` model PVC filled by a checksum-verified init container (SDXL 1.0 base first), and an Ingress at `comfyui.cosmos.cboxlab.com`.
- Keep `-shared-dev-num=1`. The scheduler is the guard against co-residency; it is not a limitation to work around.
- Switch ownership through Git: one PR sets `replicas` on both Deployments, ComfyUI to 1 and `intel-llama-ornith` to 0, or the reverse. Flux applies it, Git always describes the running state, and the PVCs of both apps stay in place across switches. The first switch ships with the PR that adds ComfyUI.
- Open WebUI and LiteLLM are not wired to ComfyUI. Use the ComfyUI UI directly.

## Alternatives considered

- **Co-residency with `-shared-dev-num=2`.** Both pods would schedule, but Ornith would have to drop to about 32K context to leave VRAM, host RAM (24 GiB, Ornith limit 16 Gi, ComfyUI needs ~7 GiB to stage SDXL) does not fit both, and a spill repeats the documented node loss. Rejected.
- **Community images** (`yanwk/comfyui-boot:xpu`, `ghcr.io/haasanen/comfyui-arc`). Plain PyTorch XPU without Intel's kernels; Intel's own measurements and a third-party rebuild show the omni kernels ahead. Rejected for the default, acceptable fallback if the Intel image misbehaves.
- **An imperative swap script** (suspend Flux for both apps, scale by hand, resume). Faster per switch, but Git stops describing the cluster, and a failed swap leaves the LLM stopped with Flux suspended. Rejected; a PR per switch is acceptable for infrequent, longer image periods.
- **Giving the LLM a smaller context when ComfyUI is up.** Reconsider if image sessions become long and the LLM must stay reachable; `local-first` already falls back to DeepSeek.

## Consequences

- `qwen-intel` and `sensitive` are down while ComfyUI owns the GPU, with no fallback by design, so the local-only `finance-curator` agent and Open WebUI's default chat model do not work. `local-first` and the agents on it keep working via its DeepSeek fallback. Do not start an autoresearch session (ADR 0006) in this state.
- First ComfyUI start costs a 7 GB image pull and a 6.94 GB model download; later starts about a minute, plus 30–60 s to stage the checkpoint on the first generation.
- A second GPU Deployment in Git is a deliberate exception to ADR 0004's "exactly one"; it is not an LLM. The rule for LLM Deployments is unchanged.
- Performance, host-memory behaviour and OOM behaviour of the Intel image on this node are unmeasured until plan 0029 records them. Treat the published estimates as hypotheses.
- The Intel image runs as root and ComfyUI Manager can install nodes at runtime; those changes live in the pod's writable layer and vanish on restart. Reproducible node changes go through the image tag.

## Implementation status

Manifests are in this repository as of 2026-11-09 (plan 0029), with ComfyUI as the GPU owner in Git. Check `flux get ks -n comfyui` and `kubectl -n comfyui get deploy,pvc` for live state.
