# ADR 0010: Stream games from the B60 with Wolf as a GPU portal entry

- Status: Proposed
- Date: 2026-11-15
- Related plan: [0032 Wolf game streaming](../plans/0032-wolf-game-streaming.md)
- Amends: [ADR 0009](0009-gpu-portal-runtime-selection.md) (the catalog gains a workload that is neither an LLM nor ComfyUI, with privileged containers and a LoadBalancer Service)

## Context

The operator streams games from a desktop to a TV with Sunshine and Moonlight, and wants the same from `titania-gpu` so the desktop does not have to be on. The node is a headless VM with one Intel Arc Pro B60, 8 vCPUs and about 20 GiB allocatable memory. The B60 is time-shared through the GPU portal ([ADR 0009](0009-gpu-portal-runtime-selection.md)), and `gpu.intel.com/xe` is 1.

Observed on 2026-11-15: MetalLB serves `192.168.1.180-199` and only `.183` (ingress-nginx) is assigned; the node runs Ubuntu 26.04 with kernel 7.0 and k3s on containerd, with no Docker daemon.

Also observed that day from sysfs: `renderD128` is the B60 under `xe`, and `uinput` is registered. The `uhid` module was not loaded.

Assumed, not yet checked: `/dev/uhid` becomes available when Wolf opens it, and the B60 encodes and runs games acceptably under the `xe` driver. Plan 0032 checks these.

Sunshine captures an existing desktop, and this node has no display and no desktop session.

## Decision

- Run [Wolf](https://games-on-whales.github.io/wolf/stable/) (Games on Whales) in `clusters/titania/apps/wolf/`. Wolf speaks the Moonlight protocol and renders each session on a virtual display of its own, so no monitor or dummy plug is needed.
- Wolf starts every app (Steam, Wolf UI and others) as a container through a Docker socket. The pod carries a Docker-in-Docker sidecar for this. The sidecar listens on a Unix socket only and lives in the pod network namespace.
- Both containers are privileged. Wolf needs `/dev/uinput`, `/dev/uhid`, the host `/dev` and `/run/udev` for virtual input devices; Docker-in-Docker needs it to run at all.
- The pod requests `gpu.intel.com/xe: 1` so the scheduler keeps it apart from the LLMs and ComfyUI. `-shared-dev-num` stays 1.
- Wolf is a GPU portal catalog entry with `WOLF_REPLICAS` in a `gpu-active` ConfigMap in its namespace, like ComfyUI. The portal treats a `metrics` endpoint as optional, because Wolf has none.
- A MetalLB LoadBalancer Service at `192.168.1.184` exposes the six GameStream ports. A NetworkPolicy admits only those ports to the pod.
- State lives on two `local-path` PVCs: `/etc/wolf` (config, pairing, app homes and game library) and the sidecar's `/var/lib/docker` (app images).
- This is a trial. Plan 0032 decides whether the entry stays.

## Alternatives considered

- **Sunshine in a pod.** Needs a desktop session and a display to capture, so it would need a headless X server or compositor built into a custom image, or a dummy plug on the passed-through card. Rejected in favour of the tool built for headless hosts.
- **`hostNetwork` for the pod.** Upstream's own example, and it avoids the LoadBalancer. Rejected because the Docker daemon would then create its bridge and iptables rules in the node's network namespace, next to Cilium.
- **Mounting a node Docker socket.** There is none on k3s, and installing Docker on the node would put a second runtime outside GitOps. Rejected.
- **Device access without `privileged`.** Upstream documents only privileged operation for nested setups, and the Intel plugin injects DRM nodes only. Not attempted for the trial; revisit if the entry stays.
- **Keep streaming from the desktop only.** Its GPU is much faster and it already works. This remains the better choice for demanding games; Wolf covers the case where the desktop is off or busy.

## Consequences

- While Wolf owns the GPU, no local LLM and no ComfyUI run: `qwen-intel` and `sensitive` are down, and `local-first` falls back to DeepSeek, as in [ADR 0008](0008-comfyui-b60-timeshare.md). Do not start an autoresearch session in this state.
- Switching away from Wolf kills a running game without saving.
- Two privileged containers run on `titania-gpu`. A compromise of Wolf, of an app container or of a game is a compromise of that node. The NetworkPolicy, the absent ServiceAccount token and LAN-only reachability limit exposure; they do not contain a compromised pod.
- Wolf's HTTP port serves the pairing page without authentication. Anyone on the LAN who has the pairing URL secret from the pod log and a PIN prompt can pair. Paired clients control whatever app they start.
- App images (`ghcr.io/games-on-whales/*`) are pulled by the sidecar at runtime from rolling tags. They are not pinned in Git and Renovate does not see them. The Wolf image itself has rolling tags only and is pinned by digest.
- Games run inside the sidecar's memory limit (14Gi). VRAM exhaustion spilling into host memory has taken this node down before ([ADR 0004](0004-llamacpp-sycl-b60-behind-litellm.md)); a game can do the same.
- The `wolf` namespace is not annotated `prune: disabled`, following ComfyUI. Removing the app from Git deletes both PVCs, including the game library.
- Game performance, encode latency and controller input through the nested setup are unmeasured.

## Implementation status

Manifests, the portal catalog entry and the portal RBAC are in this repository as of 2026-11-15 at `replicas: 0`. Nothing is applied or tested. Check `flux get ks -n wolf` and `kubectl -n wolf get deploy,pvc,svc` for live state.
