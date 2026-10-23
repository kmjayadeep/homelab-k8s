# Plan 0016: Upgrade Longhorn 1.9.2 → 1.13.x one minor at a time

- Status: Active
- Owner: operator (kmjayadeep), executed with the repository agent
- Related ADR: none yet; [plan 0006](0006-longhorn-restore-runbook.md) is the restore runbook

## Goal and scope

Bring the `longhorn` HelmRelease (`clusters/titania/infra/longhorn/helm-release.yaml`) from chart 1.9.2 to the newest 1.13.x through 1.10.x, 1.11.x and 1.12.x, merging the Renovate PR for each minor only after the previous one is healthy. Longhorn enforces the one-minor-at-a-time path and refuses downgrades, so skipping is not an option.

Also in scope: volume engines. On 2026-10-23 all 19 volumes still ran engine v1.9.1 while the manager was 1.9.2 because `concurrent-automatic-engine-upgrade-per-node-limit` was 0. Engines lagging more than one minor behind the manager are not supported, so every minor step needs the engines upgraded before the next step. This plan enables Longhorn's automatic engine upgrade (`defaultSettings.concurrentAutomaticEngineUpgradePerNodeLimit: 3`, the upstream-recommended value) so engines follow each manager upgrade without manual UI work.

Out of scope: the V2 data engine (not used), Kubernetes upgrades, storage class changes.

## Starting state and prerequisites

Verified 2026-10-23 before step 1:

- Chart 1.9.2, manager `longhornio/longhorn-manager:v1.9.2`, two Longhorn nodes (`titania-master`, `titania-worker1`) Ready and schedulable.
- 19 volumes: 16 attached/healthy, 3 detached. All use the `blockdev` frontend (live engine upgrade is unsupported only for `iscsi`). No faulted volumes, no backing images, no V2 volumes.
- All 22 Longhorn CRDs have `storedVersions: ["v1beta2"]`, which is the mandatory pre-1.10 migration check from the Longhorn 1.10 important notes.
- Backup target `nfs://truenas.cosmos.cboxlab.com:/mnt/main/k8s/longhorn-backup` available; recurring `daily` backup group selected via the storage class.
- Longhorn 1.10 removes the `longhorn.io/v1beta1` API and `replica.status.evictionRequested`; nothing in this repo references either.
- Kubernetes v1.33 (k3s) satisfies every minor's requirement.

Approvals: merging Renovate PRs and letting Flux reconcile is authorised for this work. Any `kubectl delete`, volume detach, or restore step still needs explicit approval.

## Steps and gates

Per-step gate ("healthy"): HelmRelease Ready at the target chart; `longhorn-manager`, `longhorn-csi-plugin` DaemonSets and all deployments rolled out; every volume `attached/healthy` or `detached` as before; `kubectl -n longhorn-system get engineimages.longhorn.io` shows the new engine image `deployed` and, once auto-upgrade finishes, the old one at `REFCOUNT 0`; Vault (`vault.cosmos.cboxlab.com/v1/sys/health` → 200) and the other Longhorn-backed workloads still serving.

1. **Enable automatic engine upgrade** (this PR). Merge, confirm the setting reads `3`, then watch the 16 attached volumes live-upgrade and the 3 detached ones offline-upgrade from engine v1.9.1 to v1.9.2. Gate: all volumes at v1.9.2, `ei` for v1.9.1 at refcount 0.
2. **System backup before 1.10.** Create a `SystemBackup` (`volumeBackupPolicy: if-not-present`) and wait for `Ready`. Keep it until the whole chain is done.
3. **1.10.x** (Renovate PR #298). Read the 1.10 release notes first: the only extra is the `backing-image-manager` HTTP-proxy hotfix, irrelevant here. Merge, gate, confirm engines auto-upgrade to v1.10.x.
4. **1.11.x**, **1.12.x**, **1.13.x**: approve the Renovate branch on the Dependency Dashboard one at a time, read each version's important notes and release notes, merge, gate, confirm engine auto-upgrade. Pay attention to settings consolidation (`{"v1": ...}` JSON format from 1.10) in case a `defaultSettings` key we set changes format.

## Validation and rollback

- Validation commands: `flux get helmrelease -n longhorn-system longhorn`, `kubectl -n longhorn-system get volumes.longhorn.io -o custom-columns=NAME:.metadata.name,STATE:.status.state,ROBUST:.status.robustness,IMAGE:.status.currentImage`, `kubectl -n longhorn-system get engineimages.longhorn.io`, `kubectl -n longhorn-system get settings.longhorn.io concurrent-automatic-engine-upgrade-per-node-limit -o jsonpath='{.value}'`.
- A failed engine live upgrade leaves `spec.image` ≠ `status.currentImage` and Longhorn retries; after `limit` failures on a node it stops. Investigate the engine/replica logs before touching anything.
- Longhorn does not support downgrading. If a manager upgrade fails before the pre-upgrade checker passes, Helm rolls back automatically and nothing changed. If it fails afterwards, follow [plan 0006](0006-longhorn-restore-runbook.md) and the 1.10 important notes "Troubleshooting CRD Upgrade Failures" section; both require explicit approval.

## Outcome

Record each step's date, chart version, engine image and any anomaly here.

| Date | Step | Result |
| --- | --- | --- |
| 2026-10-23 | 0: prerequisites | verified as listed above |
| 2026-10-23 | 1: enable auto engine upgrade (#323) | ConfigMap rendered `3` but the live setting stayed `0`: longhorn-manager rejected the whole `longhorn-default-setting` ConfigMap because `replica-auto-balance: true` is not a valid value (`Customized settings are invalid, will give up using them`). Live `default-replica-count` was still 3 and `priority-class` empty for the same reason. Fixed by setting `replicaAutoBalance: least-effort`. |
