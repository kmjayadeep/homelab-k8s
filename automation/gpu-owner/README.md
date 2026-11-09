# gpu-owner

`titania-gpu` has one Intel Arc Pro B60, and the GPU plugin advertises exactly one `gpu.intel.com/xe`. Two Deployments request it: `llm-serving/intel-llama-ornith` (the local LLM, [ADR 0004](../../adrs/0004-llamacpp-sycl-b60-behind-litellm.md)) and `comfyui/comfyui` (image generation, [ADR 0008](../../adrs/0008-comfyui-b60-timeshare.md)). Git holds the default: LLM at 1 replica, ComfyUI at 0. This script swaps the owner for a session and hands the GPU back by resuming Flux.

```bash
automation/gpu-owner/gpu-owner.sh status    # who holds the GPU, Flux suspend state, xe allocatable
automation/gpu-owner/gpu-owner.sh comfyui   # LLM → 0, ComfyUI → 1 (Flux suspended for both, with a marker)
automation/gpu-owner/gpu-owner.sh llm       # ComfyUI → 0, Flux resumed → Git restores the LLM
```

## What happens

`comfyui` suspends the two Flux Kustomizations with the annotation `gpu-owner.cboxlab.com/suspended-by=<user@host>`, scales the LLM to 0, waits for its pod to leave, scales ComfyUI to 1 and waits for the rollout (first start: 7 GB image pull plus a 6.94 GB SDXL download into the `comfyui-models` PVC, so allow up to 30 minutes; later starts take about a minute). Open `https://comfyui.cosmos.cboxlab.com`, or use image generation in Open WebUI.

`llm` scales ComfyUI to 0, then removes the marker and un-suspends both Kustomizations with a reconcile request. Flux reapplies Git, which brings the LLM back; the script waits for it to be available (about three minutes with a warm model cache).

Nothing is edited in Git and no manifest changes are applied, so a forgotten swap is undone by `gpu-owner.sh llm` or by `flux resume ks -n llm-serving llm-serving-intel-llama && flux resume ks -n comfyui comfyui`.

## Guards

- Refuses to start if `llm-serving-intel-llama` carries the autoresearch marker (a tuning session owns the GPU; see [`llm-autoresearch`](../llm-autoresearch/README.md)).
- Refuses to take over a Kustomization suspended without its own marker, and on `llm` leaves such a Kustomization suspended.
- Scheduling is the hard guard: with one `xe` resource, a second GPU pod stays `Pending` rather than sharing VRAM. Do not raise `-shared-dev-num` on the plugin to "fix" that; co-residency was ruled out in ADR 0008.

## While ComfyUI owns the GPU

- LiteLLM `qwen-intel` and `sensitive` return errors (backend down). `local-first` falls back to DeepSeek by design (`clusters/titania/apps/litellm/helm-release.yaml`).
- kagent agents on `qwen-intel`, Open WebUI's default chat model and anything else pointed at the local model are degraded. Stop or re-point them for long image sessions.
- Metrics for the LLM stop; the `intel-llama` ServiceMonitor target disappears, which is expected.
