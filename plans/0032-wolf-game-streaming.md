# Plan 0032: Trial Wolf game streaming on the B60

- Status: Draft
- Owner: operator
- Related ADR: [ADR 0010](../adrs/0010-wolf-game-streaming-b60.md)

## Goal and scope

Find out whether `titania-gpu` can stream games to Moonlight clients well enough to keep as a GPU portal entry. A plan is needed because the pod is privileged, takes the GPU from the LLM, and several assumptions about the node are unchecked.

In scope: the `wolf` app, its bootstrap Kustomization, the portal catalog entry and RBAC, pairing one client, one Steam game. Out of scope: access from outside the LAN, Wake-on-LAN, more than one simultaneous client, custom Wolf apps, reducing privileges.

## Starting state and prerequisites

Verified in the repo on 2026-11-15: manifests build, pass `kubectl apply --dry-run=client` against titania and pass `kubeconform -strict`. The Deployment is at `replicas: 0` and the `gpu-active` default is `"0"`, so merging starts nothing on the GPU.

Verified read-only in the cluster on 2026-11-15: MetalLB `main-pool` is `192.168.1.180-199` with only `.183` assigned; `192.168.1.184` did not answer a ping; `titania-gpu` has 8 CPUs, about 20 GiB allocatable memory and a 495 GiB disk; Swift is the active GPU workload; no `wolf` namespace exists.

Verified on the node on 2026-11-15, read from sysfs through the `gpu-stats` pod: `renderD128` is the B60 (`xe`; `card0` is the VM's `bochs-drm` adapter and has no render node), so the default `WOLF_RENDER_NODE` is right. `uinput` is registered (misc device 10:223).

Not verified:

- `/dev/uhid` exists on `titania-gpu`. The `uhid` module was not loaded on 2026-11-15. The kernel normally loads it when the device node is first opened; if it does not, only DualSense (PS5 controller) emulation is affected.
- Docker-in-Docker starts under k3s on this node (cgroup v2, overlay on `local-path`).
- Wolf's virtual input devices reach containers started by the nested daemon.
- The B60 encodes and runs games acceptably under `xe`.

Approvals needed: merging the PR, and the first switch to Wolf in the portal, which stops the local LLM.

## Steps and gates

1. **Node checks.** Done on 2026-11-15 for the render node and `uinput` (see above). Remaining: after the first start, check the `wolf` container log for a `/dev/uhid` error. If there is one, load the `uhid` module persistently through the node's own configuration.
2. **Merge.** Flux creates the namespace, PVCs, Service and NetworkPolicy; the Deployment stays at 0. Gate: `kubectl -n wolf get svc wolf` shows `192.168.1.184`; the portal lists "Wolf game streaming" and still reports the active LLM as ready. The portal restarts once for the new catalog and may show errors until the `wolf` namespace and its `gpu-active` ConfigMap exist.
3. **Switch to Wolf in the portal.** Gate: the pod is `2/2` Ready. `kubectl -n wolf logs deploy/wolf -c dind` shows the daemon listening on the Unix socket only; `kubectl -n wolf exec deploy/wolf -c dind -- netstat -ltn` shows no `2375` or `2376`.
4. **Pair.** Add `192.168.1.184` in Moonlight by address (mDNS discovery does not cross into the cluster). Moonlight shows a PIN; `kubectl -n wolf logs deploy/wolf -c wolf` prints a pairing URL. Open it with `192.168.1.184` as the host and enter the PIN. Do not paste the URL anywhere; its fragment is the pairing secret.
5. **First session.** Start Wolf UI, then Steam. The first start of each app pulls its image, so a black screen for some minutes is expected; follow the `wolf` container log. Gate: picture, sound and controller input all work.
6. **Measure.** One controller game at the client's native resolution: frame rate, Moonlight's latency overlay, `kubectl top pod -n wolf`, VRAM in the portal. Record them under Outcome.
7. **Switch back** to the LLM in the portal. Gate: the Wolf pod is gone and the LLM is ready. Switch to Wolf again and confirm pairing, Steam login and installed games survived.

## Validation and rollback

- Local: `kustomize build clusters/titania/apps/wolf | kubectl apply --dry-run=client -f -`, and the same for `gpu-portal`.
- Stop: switch to another entry in the portal. This frees the GPU and keeps both PVCs.
- If the pod harms the node: switch away first; if the portal cannot, set `WOLF_REPLICAS` to `"0"` in the `gpu-active` ConfigMap in `wolf` and reconcile the `wolf` Kustomization.
- Revert: revert the PR. This prunes the namespace contents, including both PVCs and the game library. It is destructive and needs explicit approval.

## Outcome

In progress.

- 2026-11-15: merged (PR 623) and switched to Wolf. Steps 2 and 3 passed: the Service got `192.168.1.184`, the pod went `2/2` Ready 47 s after the switch, Docker-in-Docker runs under k3s with no TCP listener, and Wolf chose VA-API encoders for H.264, HEVC and AV1 with its zero-copy path on `renderD128`.
- 2026-11-15: step 4 passed; a client paired and the built-in test ball streamed. Step 5 failed: Wolf UI showed a black screen and exited after about half a second. Cause: the dind entrypoint mounts a tmpfs over `/tmp`, hiding the shared `/tmp/sockets`, so app containers were given empty directories instead of the Wayland, PulseAudio and Wolf API sockets. Fixed by sharing `/run/user/wolf` instead. Steps 5 to 7 remain.
- 2026-11-15: with that fix (PR 624) Wolf UI works. Steam's first start downloaded its client and exited with code 0, as a first run does. The second start came up but its UI failed: apps use `IpcMode: host` and so share the dind container's `/dev/shm`, which was the 64Mi Kubernetes default and 96% full; Steam logged `AllocateRingBuffer() failed` and disabled GPU acceleration. Fixed with a 4Gi memory-backed `/dev/shm` on the sidecar.
