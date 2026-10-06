# Plan 0009: Swift-Qwen3.8-27B Q4_K_S trial on the sole B60

- Status: Active trial
- Owner: Homelab operator
- Related: [B60 evaluation](0005-intel-arc-b60-llm-serving-evaluation.md), [Tiel trial](0008-tiel-coder-b60-trial.md), [performance comparison](0007-local-llm-performance-comparison.md)

## Goal and scope

With operator approval, temporarily stop the sole B60 Tiel predictor, serve a separate pinned Swift Qwen3.8 Q4_K_S GGUF at **128K configured context**, test its versioned LiteLLM route, and then move the persistent `qwen-intel` alias to Swift only if healthy. Retain all Tiel and earlier PVCs, workloads, versioned routes, and uncommitted performance work. Outage of `qwen-intel` is expected between stopping Tiel and verifying Swift; do not run both GPU claimants at once. This approval does not cover cache deletion, 128K active-prompt stress, or executing publisher scripts.

## Starting state and risks

- [Publisher card](https://huggingface.co/ukisai/Swift-Qwen3.8-27B-GGUF) recommends llama.cpp with `--jinja`, Flash Attention, full GPU offload, temperature 1, top-p 0.95, top-k 20, min-p 0, presence penalty 0, repeat penalty 1, and optional MTP draft width 3. Use 128K (`131072`), one slot and Q8 K/V to reduce memory relative to F16 while retaining the user's requested context. Runtime sampling defaults apply to calls without explicit request parameters; the fixed benchmark explicitly uses temperature 0 and is not the publisher's benchmark. Do not advertise image handling: the separate mmproj is outside this text-only trial. Verify argument support in the installed runtime.
- Pin `Swift-Qwen3.8-27B-Q4_K_S.gguf` to revision `98a6100719e3aafa186041089b71c7b48390dbe1`, length 16,575,850,592 bytes and HF LFS SHA-256 `974812e92df1ce82d91aa7aafa466ef1b707c91fdd3074dfb29438aa59d279d3`. HEAD returned HTTP 200 and the expected length without authentication, despite the card's gated-access wording. License is Swift Open License v1.0 with revenue conditions; verify suitability before any wider distribution.
- 128K/Q8 KV is approximately 4 GiB before other GPU allocations; weights are ~15.4 GiB, plus runtime and MTP overhead. The B60 has ~24 GiB VRAM; memory pressure or launch failure is possible. Do not infer 128K active safety from successful startup or short requests. The previous Tiel cache and a separate 40Gi node-local cache must remain intact; the GPU node root had about 140 GiB free before the trial.

## Ordered rollout and rollback gates

1. Add versioned `swift-qwen3.8-27b-q4ks-intel` LiteLLM model at a distinct Service with 114,688 input plus 16,384 output token metadata, without changing `qwen-intel`. Validate and push. Verify Flux applied it and LiteLLM HelmRelease Ready; this does not mean Swift serves traffic yet.
2. Scale Tiel to zero **in Git** and push; verify Flux applied that exact revision and the Tiel pod exited before creating a Swift GPU claimant. Keep the Tiel PVC and Service. At this point `qwen-intel` is unavailable. If GPU release cannot be confirmed, stop.
3. Add a separate Swift PVC, checksum-verifying init, Deployment and Service. Retarget Flux health to the running Swift Deployment in the same revision; avoid unbound `WaitForFirstConsumer` PVCs under `wait: true`. Client dry-run both serving and bootstrap. After pushing/reconciling, check checksum init exit status, 1/1 readiness, node Ready/no MemoryPressure, VRAM and host memory, and zero unexpected restarts. If startup fails or headroom is unsafe, scale Swift to zero first, verify its pod exited, restore Tiel from Git, and verify its versioned request before restoring alias availability.
4. Send a benign short request to the Swift **versioned** LiteLLM route. Only after success, change Git alias `qwen-intel` to Swift, confirm LiteLLM HelmRelease Ready, check the effective persisted Router Settings mapping and align the complete alias map via authenticated `/config/update` if Helm did not update it; do not print credentials/config dumps. Confirm benign alias traffic and sample memory again. Preserve rollback by switching back to healthy Tiel in strict reverse sole-GPU order if necessary.
5. If stable, run bounded short/medium/~25K profile through the versioned entry and update the standalone HTML while preserving previous result files and all uncommitted user changes. Do not claim active 128K capacity, quality improvements, tool reliability or publisher speedups from these throughput checks.

## Validation and outcome

Use `kustomize build <entry> | kubectl apply --dry-run=client -f -` with `pipefail`, `git diff --check`, exact Flux revisions, and narrowly filtered Kubernetes conditions. Record failures and observed limits here. Do not delete any PVC, model files or prior benchmark work.

Pending live trial.
