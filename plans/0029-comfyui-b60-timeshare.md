# Plan 0029: ComfyUI image generation on the B60, time-shared with the LLM

- Status: Draft
- Owner: operator
- Related ADR: [ADR 0008](../adrs/0008-comfyui-b60-timeshare.md)

## Goal and scope

Run ComfyUI on the Intel Arc Pro B60 for image generation, reachable at `comfyui.cosmos.cboxlab.com`, without changing the LLM serving decision in [ADR 0004](../adrs/0004-llamacpp-sycl-b60-behind-litellm.md). The GPU is time-shared through Git: a PR sets `replicas` on both Deployments.

In scope: the `comfyui` app and bootstrap Kustomization, the first switch to ComfyUI, SDXL 1.0 base as the first model, first measurements. Out of scope: GPU sharing (`-shared-dev-num>1`), video models, LoRA training, Open WebUI or LiteLLM integration, changes to the LLM Deployment other than `replicas`.

## Starting state and prerequisites

Verified in the repo:

- `clusters/titania/infra/intel-gpu-plugin/daemonset.yaml` runs `intel/intel-gpu-plugin:0.37.1` with default sharing (`xe: 1`).
- `clusters/titania/apps/llm-serving-intel-llama/deployment-ornith.yaml` requests `gpu.intel.com/xe: 1`, limits 16 Gi, on `gpu.intel.com/product: arc-pro-b60`.
- Ingresses use the `cosmos-cboxlab-cert` wildcard and nginx.

Unverified in the cluster: free disk under `local-path` on `titania-gpu` (needs about 80 Gi for the two PVCs plus the 7 GB image), that `intel/llm-scaler-omni:0.2.0-b2` starts on this node's kernel/driver (the image is AOT-compiled for Battlemage and documents `--device=/dev/dri` only), and the published performance estimates.

Approvals needed: merging to `main` stops Ornith and starts ComfyUI, and creates the namespace, PVCs (storage allocation), Service and Ingress. `qwen-intel` and `sensitive` go down with no fallback, so merge when agents are idle.

## Steps and gates

1. **Merge** this plan, ADR 0008, `clusters/titania/apps/comfyui/`, `clusters/titania/bootstrap/apps/comfyui.yaml` and the `replicas: 0` on Ornith. Gate: `kubectl -n comfyui get pvc` Bound once the pod schedules.
2. **First start.** Expect: Ornith pod gone (ComfyUI stays `Pending` until then), image pull, init container downloads SDXL (6.94 GB, sha256-verified), ComfyUI Ready within the Kustomization's 30m timeout. Gate: `flux get ks -n comfyui` Ready, `/system_stats` through the Ingress lists one XPU device; `kubectl -n comfyui logs deploy/comfyui` shows `xpu` as the torch device and no fallback to CPU.
3. **First generation.** In the ComfyUI UI, load the default SDXL text-to-image template, 1024², 25–30 steps, Euler. Record wall time of the first (cold) and third (warm) generation, container working set (`kubectl top pod -n comfyui`), node free memory and `xpu-smi` VRAM if available. Gate: an image, and node memory not within 2 GiB of the limit.
4. **Hand back when needed.** A follow-up PR sets ComfyUI to `replicas: 0` and Ornith to `replicas: 1`. Gate: ComfyUI pod gone, Ornith Ready, `qwen-intel` answers through LiteLLM.
5. **Record** measurements in the Outcome section, replace the estimates in ADR 0008 with them, set ADR 0008 Accepted and this plan Completed.

Follow-ups, each a routine manifest change once step 5 is done: add Z-Image-Turbo (6B, fits comfortably, Intel ships tuned workflows) or a Flux.1 GGUF via the image's GGUF-XPU loader; try the DynamicVRAM-off direct launch (`--disable-dynamic-vram` with `OMNIXPU_PROVIDER_BOOTSTRAP=auto`) and compare warm time; a Grafana panel for the GPU owner.

## Validation and rollback

- Manifests: `kustomize build clusters/titania/apps/comfyui | kubectl apply --dry-run=client -f -` and the same for `clusters/titania/apps/llm-serving-intel-llama`.
- Rollback if ComfyUI fails to start: the hand-back PR in step 4. Ornith's model PVC is untouched.
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

Cold start after a switch: about a minute to Ready, then 30–60 s on the first generation to stage the 7 GB checkpoint through host RAM.

## Outcome

2026-11-09: merged and running, with ComfyUI as the GPU owner. SDXL base at 1024², 25 steps, Euler: 16 s cold, about 7 s warm, on `xpu:0`, pod working set about 4.9 GiB afterwards.

`imagine.cosmos.cboxlab.com` is a one-page prompt-to-image frontend (`clusters/titania/apps/comfyui/imagine/`), using RealVisXL V5.0 fp16 with the settings from its model card. It proxies only `/prompt`, `/history` and `/view`.

Open risk: neither Ingress has authentication yet, and the host has a global AAAA record. Basic auth needs a Vault path, a policy in `homelab-iac` and a `SecretStore` in the `comfyui` namespace.
