# Plan 0001: Incremental SealedSecret to ExternalSecret rollout

- Status: Completed with follow-up work
- Related ADR: `adrs/0001-vault-external-secrets.md`
- Vault-side plan: `homelab-iac/plans/0001-vault-secret-migration.md`

The phase checklists below preserve the original rollout procedure. The
completion summary and remaining gates at the end are the authoritative current
status.

## Goal

Replace active SealedSecrets incrementally with namespaced ExternalSecrets. The
canonical value remains in Vault and may be consumed by Kubernetes, VMs, or
other systems through separate least-privilege identities. A Kubernetes
namespace is an authentication boundary, not part of a Vault path.

## Safe rollout pattern

Use this sequence for every migration. Do not let Sealed Secrets and ESO manage
the same Kubernetes Secret name simultaneously.

1. Complete and apply the matching Vault path, policy, and Kubernetes auth role
from the infrastructure repository.
2. Add a dedicated `external-secrets-vault` ServiceAccount, namespaced
`SecretStore`, and `ExternalSecret` that initially creates `<old-name>-vault`.
3. Map canonical Vault property names to the exact keys/files expected by the
workload. Use an ESO target template for derived formats such as database URLs,
Docker config JSON, or object-store YAML.
4. Confirm `SecretStore` and `ExternalSecret` are Ready. Validate expected key
names and Secret type without printing values.
5. Update the consumer to use `<old-name>-vault`. Reconcile and observe normal
operation for the phase-specific window.
6. Keep the original SealedSecret and old consumer reference available for
rollback during the observation window.
7. In a later change, remove `secret-sealed.yaml` from the Kustomization and
remove the file. Do not rename the ESO Secret merely to recover the old name.
8. Remove decrypted local/source artifacts according to the repository's secret
handling workflow.

Rollback restores the old Secret reference and workload revision. Deleting the
ExternalSecret or Vault value is not part of rollback.

## Phase 0: Prerequisites and canary

**Impact:** no production secret changes.

- [ ] Vault serves trusted internal TLS and ESO has its CA reference.
- [ ] Vault and External Secrets Flux Kustomizations are healthy and ordered
before consumers.
- [ ] The Vault Kubernetes auth backend is applied and TokenReview works.
- [ ] Verify Kubernetes datastore encryption at rest.
- [ ] Create a temporary namespace, ServiceAccount, SecretStore, and
ExternalSecret for a non-sensitive canary value.
- [ ] Confirm successful synchronization and denial of an unrelated Vault path;
then remove all canary resources.
- [ ] Document readiness checks and reconciliation commands without commands
that print Secret values.

## Phase 1: Cloudflare

**Priority:** first because rotation currently requires updating two
SealedSecrets. This is a high-impact change affecting DNS and certificate
issuance, so it gets a dedicated rollout and rollback window.

Both controllers intentionally share the zone-scoped identity at
`services/cloudflare/dns-cboxlab`. Future Cloudflare credentials with different
permissions, zones, or rotation boundaries use sibling paths under
`services/cloudflare/`.

### 1A: cert-manager

- [ ] Add `external-secrets-vault`, a `SecretStore`, and an `ExternalSecret` in
`cert-manager`.
- [ ] Materialize `cloudflare-api-token-vault` with key `api-token` from Vault
property `api_token`.
- [ ] Change `ClusterIssuer.spec.acme.solvers[].dns01.cloudflare.apiTokenSecretRef`
to `cloudflare-api-token-vault`.
- [ ] Reconcile and issue a temporary test Certificate for the DNS zone.
- [ ] Confirm the DNS-01 challenge completes and the existing wildcard
Certificate remains Ready.
- [ ] Observe at least one successful issuance before deleting the old
`cloudflare-api-token` SealedSecret in a separate commit.

Rollback restores the ClusterIssuer reference to `cloudflare-api-token`.
Existing issued certificates continue serving during this test.

### 1B: external-dns

Start only after 1A is stable.

- [ ] Add `external-secrets-vault`, a `SecretStore`, and an `ExternalSecret` in
`external-dns`.
- [ ] Materialize `cloudflare-creds-vault` with key `api_token` from Vault
property `api_token`.
- [ ] Change the Deployment's `CF_API_TOKEN` Secret reference.
- [ ] Reconcile, confirm the pod is Ready, and verify a controlled DNS record
create/update through the normal GitOps source.
- [ ] Confirm unrelated records are unchanged.
- [ ] Observe at least one normal external-dns reconciliation before deleting
`cloudflare-creds` and its SealedSecret in a separate commit.

Rollback restores the Deployment reference to `cloudflare-creds`.

### 1C: rotation proof

- [ ] After both consumers are stable, rotate each selected Cloudflare identity
through Vault.
- [ ] Confirm ESO refreshes the target Secret and restart/reconcile consumers if
required because environment variables do not update in running pods.
- [ ] Repeat certificate and DNS update checks, then revoke old Cloudflare
tokens.

## Phase 2: Shared/high-toil service identities

Migrate one row per pull request. When two workloads intentionally share a Vault
document, each namespace or trust boundary still has its own SecretStore and
Vault role.

| Order | Current Secret | Vault path | Validation |
|---|---|---|---|
| 1 | `baskit-metrics-firebase` plus Firebase data in `baskit-backup` | `services/firebase/baskit`, if securely verified identical | Metrics succeeds and a backup plus restore test completes |
| 2 | `actions-runner-secret` | `services/github/actions-runner` | A disposable workflow job is accepted and completes |
| 3 | `ghcr-secret` | `services/ghcr/baskit-pull` | Force a test image pull after rendering a `kubernetes.io/dockerconfigjson` Secret |
| 4 | AdGuard property in `glance-secret` | `services/adguard/glance` | Glance widget/API check succeeds |
| 5 | Immich property in `glance-secret` | `services/immich/glance` | Glance widget/API check succeeds |

For Glance, one ExternalSecret may compose properties from the two exact Vault
paths into `glance-secret-vault`; the source values remain independently
rotatable.

## Phase 3: Isolated application secrets

**Impact:** one application each. Use the standard parallel-Secret pattern.

1. Beancount: `fava-auth` from `apps/beancount/auth`.
2. Dotbintask: `dotbintask-secret` from `apps/dotbintask/api`.
3. Psuite wiki: `psuite-wiki-creds` from `apps/psuite/wiki`.
4. Wallabag: `wallabag-config` from `apps/wallabag/core`.
5. OTPCloud application key from `apps/otpcloud/core`.
6. LiteLLM master and salt keys from `apps/litellm/core`.

Do not combine database credentials into application-owned paths. OTPCloud and
LiteLLM may temporarily compose application and database paths into one target
Kubernetes Secret when their database phases are complete.

## Phase 4: PostgreSQL credentials

**Impact:** application outage if formatting, rotation, or restart is wrong.
Migrate and rotate one database role at a time:

1. Shoppinglist — `services/postgresql/shoppinglist`
2. Taskplanner — `services/postgresql/taskplanner`
3. OTPCloud — `services/postgresql/otpcloud`
4. LiteLLM — `services/postgresql/litellm`

- [ ] Store canonical connection components in Vault.
- [ ] Render `POSTGRES_PASSWORD`, `DATABASE_URL`, or `DB_CONNECTION_STRING` in
ESO without storing duplicate URL values.
- [ ] Verify the generated Secret has all expected keys without logging values.
- [ ] Restart the workload after Secret refresh; environment variables are not
updated in existing containers.
- [ ] Exercise a write and read transaction, then monitor database errors.
- [ ] Rotate the database credential only after the source migration is stable.

## Phase 5: Object storage and backups

**Impact:** data durability. Require restore/read validation before cleanup.

| Order | Current Secret | Vault path | Required proof |
|---|---|---|---|
| 1 | object-storage fields in `baskit-backup` | `services/object-storage/baskit-backup` | New backup and restore into a temporary location |
| 2 | `loki-minio-creds` | `services/object-storage/loki` | Query historical logs across the cutover |
| 3 | `thanos-s3` | `services/object-storage/thanos` | Render `objstore.yml`; query historical metrics |
| 4 | `restic-config` | `platform/backup/restic-exporter` | Repository check and temporary restore |
| 5 | `psuite-restic-creds` | `services/object-storage/psuite-restic` | First confirm it is active and add it to GitOps intentionally |

Do not merge object-store identities merely because endpoints or property names
match. Separate bucket-scoped identities under `services/object-storage/` are
preferred.

## Phase 6: Deluge VPN material

Migrate OpenVPN and WireGuard separately:

- `openvpn-config` from `services/vpn/deluge-openvpn`
- `wg-config` from `services/vpn/deluge-wireguard`

For each method, verify pod readiness, tunnel establishment, external egress IP,
DNS behavior, and kill-switch behavior. Keep the alternate VPN method untouched
as an operational fallback.

## Phase 7: Monitoring secrets

Migrate last so monitoring remains available during earlier phases:

1. `grafana-creds` from `platform/monitoring/grafana-admin`.
2. `alertmanager-config` from `platform/monitoring/alertmanager`.

For Alertmanager, validate configuration parsing and send a test alert through
each configured receiver before removing the old SealedSecret.

## Deferred and excluded

- `cosmos-cboxlab-cert` remains cert-manager-managed and is not an ESO target.
- Vault recovery/unseal material and the initial root token remain offline.
- `k8s-ai-sre-env` is referenced but not declared; inventory it before planning
migration.
- The inactive `psuite-restic-creds` value was preserved in Vault without a
Kubernetes role; it remains unreferenced.
- Sealed Secrets remains installed temporarily even though no SealedSecret
resources remain. Removing the controller is a separate final decision.

## Completion summary

All active SealedSecrets inventoried by this plan were migrated to Vault-backed
ExternalSecrets and removed from Git and the cluster. Flux Kustomizations,
ExternalSecrets, Helm releases, and workloads were verified healthy after the
cutover. Local decrypted YAML artifacts were removed. Follow-up work consists of
Vault internal TLS, upstream credential rotation/expiry, restore drills, and a
separate decision about removing the now-unused Sealed Secrets controller.

## Outcome and remaining gates

- [x] Every migrated workload has a Ready namespaced SecretStore and ExternalSecret.
- [x] ESO identities use exact-path Vault policies.
- [x] All old SealedSecrets were removed in post-validation commits.
- [x] No SealedSecret resources or manifests remain.
- [ ] Enable trusted internal Vault TLS and update all SecretStores.
- [ ] Extend scoped Reloader coverage or document GitOps restarts for remaining
  environment-variable consumers before their next rotation.
- [ ] Remove the unused Sealed Secrets controller in a separate approved change.
