# Plan 0008: Trial Tiel Coder 35B-A3B MTP on the sole B60

- Status: Active trial
- Owner: Homelab operator
- Related: [B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md), [client performance profile](0007-local-llm-performance-comparison.md)

## Goal and scope

Switch the sole B60 from Intel Qwen3.8-27B Q4_K_M to a separate, pinned Tiel Coder 35B-A3B GGUF MTP predictor, then select Tiel behind LiteLLM's stable `qwen-intel` alias after a versioned smoke test. Preserve both caches and workloads for rollback. The operator approved the live interruption, staged GitOps commits/pushes, and **80K configured context**; this does not authorize an 80K active-prompt stress test, removal of PVCs, or simultaneous GPU claimants.

## Starting state and prerequisites

- Before the switch, `intel-llama-qwen38-autoround-trial` was the sole GPU claimant, with 80K/Q8 K/V, no MTP, and `qwen-intel` targeting its versioned LiteLLM entry. The older `intel-llama` Qwen3.6-35B-A3B manifest provides a reference for Q8 K/V, Flash Attention, one slot and `draft-mtp` width 2. Verify live Flux revisions and node health at each stage rather than relying on these historical statements.
- [Publisher card](https://huggingface.co/peculiar-ragdoll/Tiel-Coder-35B-A3B-GGUF-MTP) describes a dynamically quantized Ornith-1.5 derivative with a Sharp chat template and embedded MTP head. Select `Tiel-Coder-35B-A3B-MTP-UD-IQ4_XS.gguf` at revision `bbe9e566f39e4fc9652ac66b71968289a03c520a` (18,119,933,792 bytes, HF LFS SHA-256 `96b4c5430b5a693447a0aafce58840466829e1788e46fc037b23dfbafab009bf`). This is **not** the old Unsloth 35B checkpoint. A 40Gi node-local PVC allows checksum-verified download with a partial file. Node root had about 157 GiB available before the change.
- Start with `--ctx-size 81920`, `q8_0` K/V, Flash Attention on, `--parallel 1`, full GPU offload, `--jinja` for the bundled template, `--spec-type draft-mtp` and `--spec-draft-n-max 2`. The installed llama.cpp binary's help listed these flags, but startup and B60 performance with these weights remain unverified. Do not assume publisher task or speed claims hold locally. No vision projector is part of this text-only trial; do not advertise vision or untested tool reliability.
- An earlier Ornith 64K run reportedly caused memory-pressure eviction on this node. Startup at 80K is a **configuration target**, not proof of safe near-limit requests. Watch GPU VRAM, host available memory, node pressure, restarts, and eviction events; stop promptly on trouble.
- Uncommitted performance runner/report/result edits predate this trial; do not stage, rewrite or discard them as part of the model switch.

## Steps and gates

1. Register a LiteLLM versioned entry `tiel-coder-35b-a3b-intel` with the distinct internal Service and the existing internal accounting rates; keep `qwen-intel` unchanged. Validate the LiteLLM build/dry-run. Verify Flux applied this registration and the HelmRelease is Ready (not evidence that Tiel is running).
2. Commit/push the Qwen3.8 predictor at zero replicas. Confirm the exact revision was applied and its pod exited before any new Deployment requests the GPU. The stable alias will be unavailable until the new model is ready. Do not remove its PVC or Service.
3. In a later revision add a separate Tiel PVC, stopped-to-running Deployment and Service to `llm-serving-intel-llama`, and retarget that Flux Kustomization's health check to Tiel. Avoid staging an unbound `WaitForFirstConsumer` PVC at zero replicas under `wait: true`: the last trial blocked Flux until a pod scheduled. Build/dry-run the serving entry point and bootstrap Flux resource. Reconcile source/bootstrap and serving, and verify download checksum by init exit code (not raw logs), pod readiness, correct model alias, node health, and observed GPU/host headroom. If startup fails or headroom is poor, stop Tiel, verify GPU release, restore the prior Qwen3.8 predictor and verify its versioned LiteLLM request before any alias change.
4. Make a benign short request through `tiel-coder-35b-a3b-intel` in LiteLLM. Only after it succeeds, change Git's `qwen-intel` alias to that entry. Confirm LiteLLM HelmRelease Ready, inspect the effective database-backed `/router/settings` mapping using an in-process credential with **no secret/config dumps**, align the complete alias map with authenticated `/config/update` if necessary, then confirm a benign alias request.
5. If healthy, run the fixed short/medium/~25K synthetic client profile separately from historical model runs, monitor pressure between requests and (if possible) sample during load. Keep all prior numeric results. Do not claim 80K active-context safety, MTP speedup, tool quality, or equivalence to the publisher benchmarks from a successful startup or small prompt.

## Validation and rollback

Use `kustomize build <serving-or-litellm-path> | kubectl apply --dry-run=client -f -`, the bootstrap Flux resource client dry-run, `git diff --check`, and the Python performance runner tests for any runner changes. Report exact source/applied revision, actual readiness, alias routing and validation failures; never treat dry-run as live evidence. For rollback, update the stable alias away from a broken backend only after restoring a healthy versioned route: stop Tiel (leave cache intact), verify its pod exited, resume Qwen3.8 on the sole GPU, confirm its versioned request, then restore Git **and** persisted LiteLLM alias and confirm `qwen-intel` works. Never prune/delete retained PVCs as a shortcut.

## Outcome

Pending live trial. Record measured readiness, memory, request behavior, and whether the trial was left running or rolled back. Keep numeric performance evidence in `automation/llm-performance/results/` if a full valid run completes; do not fabricate missing samples.
