# Plan 0029: ComfyUI image generation on the B60, time-shared with the LLM

- Status: Draft
- Owner: operator
- Related ADR: [ADR 0008](../adrs/0008-comfyui-b60-timeshare.md)

## Goal and scope

Run ComfyUI on the Intel Arc Pro B60 for image generation, reachable at `comfyui.cosmos.cboxlab.com` and as Open WebUI's image backend, without disturbing the LLM serving decision in [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md). The GPU is time-shared: the LLM owns it by default and `automation/gpu-owner/gpu-owner.sh` swaps for a session.

In scope: the `comfyui` app and bootstrap Kustomization, the swap script, Open WebUI env, SDXL 1.0 base as the first model, first measurements. Out of scope: GPU sharing (`-shared-dev-num>1`), video models, LoRA training, changes to the LLM Deployment.

## Starting state and prerequisites

Verified in the repo:

- `clusters/titania/infra/intel-gpu-plugin/daemonset.yaml` runs `intel/intel-gpu-plugin:0.37.1` with default sharing (`xe: 1`).
- `clusters/titania/apps/llm-serving-intel-llama/deployment-ornith.yaml` requests `gpu.intel.com/xe: 1`, limits 16 Gi, on `gpu.intel.com/product: arc-pro-b60`.
- `open-webui` uses `ENABLE_PERSISTENT_CONFIG=False`, so image settings are env-driven.
- Ingresses use the `cosmos-cboxlab-cert` wildcard and nginx.

Unverified in the cluster: free disk under `local-path` on `titania-gpu` (needs about 80 Gi for the two PVCs plus the 7 GB image), that `intel/llm-scaler-omni:0.2.0-b2` starts on this node's kernel/driver (the image is AOT-compiled for Battlemage and documents `--device=/dev/dri` only), and the published performance estimates.

Approvals needed: merging to `main` creates the namespace, PVCs (storage allocation), Service and Ingress; the Deployment stays at 0 replicas. The first `gpu-owner.sh comfyui` interrupts `qwen-intel`; run it when agents are idle.

## Steps and gates

1. **Merge** this plan, ADR 0008, `clusters/titania/apps/comfyui/`, `clusters/titania/bootstrap/apps/comfyui.yaml`, `automation/gpu-owner/`, and the Open WebUI env change. Gate: `flux get ks -n comfyui` Ready, `kubectl -n comfyui get deploy comfyui` shows `0/0`, PVCs Bound (local-path binds on first consumer, so `Pending` until step 2 is also acceptable), Open WebUI rolled.
2. **First swap.** `automation/gpu-owner/gpu-owner.sh comfyui`. Expect: Ornith pod gone, image pull, init container downloads SDXL (6.94 GB, sha256-verified), ComfyUI Ready. Gate: `/system_stats` through the Ingress lists one XPU device; `kubectl -n comfyui logs deploy/comfyui` shows `xpu` as the torch device and no fallback to CPU.
3. **First generation.** In the ComfyUI UI, load the default SDXL text-to-image template, 1024², 25–30 steps, Euler. Record wall time of the first (cold) and third (warm) generation, container working set (`kubectl top pod -n comfyui`), node free memory and `xpu-smi` VRAM if available. Gate: an image, and node memory not within 2 GiB of the limit.
4. **Open WebUI.** Enable the image button in a chat and generate once. Gate: image returned; Open WebUI logs show it called `COMFYUI_BASE_URL`. If the built-in workflow fails on this ComfyUI version, export the working UI workflow as API JSON and set `COMFYUI_WORKFLOW` and `COMFYUI_WORKFLOW_NODES` explicitly.
5. **Hand back.** `automation/gpu-owner/gpu-owner.sh llm`. Gate: ComfyUI pod gone, both Kustomizations un-suspended, Ornith Ready, `qwen-intel` answers through LiteLLM.
6. **Record** measurements in the Outcome section, replace the estimates in ADR 0008 with them, set ADR 0008 Accepted and this plan Completed.

Follow-ups, each a routine manifest change once step 6 is done: add Z-Image-Turbo (6B, fits comfortably, Intel ships tuned workflows; needs a split loader so Open WebUI would need a custom workflow) or a Flux.1 GGUF via the image's GGUF-XPU loader; try the DynamicVRAM-off direct launch (`--disable-dynamic-vram` with `OMNIXPU_PROVIDER_BOOTSTRAP=auto`) and compare warm time; a Grafana panel for the GPU owner.

## Validation and rollback

- Manifests: `kustomize build clusters/titania/apps/comfyui | kubectl apply --dry-run=client -f -` and the same for `clusters/titania/apps/open-webui` (the authoring session had no `kustomize`/`kubectl`; YAML was parsed but the dry-run is still owed before merge).
- Swap rollback: `gpu-owner.sh llm`, or `flux resume ks -n llm-serving llm-serving-intel-llama && flux resume ks -n comfyui comfyui`. Git state is the LLM up, ComfyUI at 0.
- Full rollback: revert the merge. Deleting the two PVCs removes the downloaded model and outputs and needs explicit approval.
- Co-residency guard: never raise `-shared-dev-num`; if both pods are ever Running at once, stop ComfyUI first.

## Expected performance (hypotheses, replace with measurements)

| Workload | Published estimate for the B60 | Source |
| --- | --- | --- |
| SDXL base 1024², 30 steps | ~8 s/image (RTX 3090 ~6 s) | gigagpu.com B60/ComfyUI pages |
| Flux.1 Schnell 1024², 4 steps | ~4 s | same |
| Flux.1 Dev Q4 GGUF, 28 steps | ~14 s | same |
| Z-Image-Turbo 1024², 8–9 steps | 15–20 s on comparable cards | community reports |
| Intel omni kernels vs plain torch XPU | ~17% faster on one workflow (5.3 s vs 6.4 s) | IdealPhaseLLC/ComfyUI_for_IntelARC |

Cold start after a swap: about a minute to Ready, then 30–60 s on the first generation to stage the 7 GB checkpoint through host RAM.

## Outcome

Not started.
