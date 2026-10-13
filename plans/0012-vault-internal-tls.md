# Plan 0012: Vault internal TLS

- Status: Draft
- Owner: homelab operator
- Related ADR: [ADR 0001](../adrs/0001-vault-external-secrets.md); follow-up from [plan 0001](0001-sealed-secrets-to-vault.md)

## Goal and scope

Serve the Vault API only over TLS signed by a private in-cluster CA. Every External Secrets `SecretStore`, the raft peers, the backup CronJob and the ingress backend must validate that CA. This is the deferred step 1 of the ADR 0001 migration.

In scope:

- `clusters/titania/infra/trust-manager/`: trust-manager HelmRelease in `cert-manager`.
- `clusters/titania/infra/vault-pki/`:
  - self-signed root `vault-internal-ca`, with its key Secret kept in `cert-manager`;
  - ClusterIssuer `vault-internal-ca`;
  - trust-manager `Bundle` `vault-ca-cert`, which publishes only the CA certificate as ConfigMap `vault-ca-cert` (key `ca.crt`) in every namespace.
- `clusters/titania/apps/vault/`:
  - listener certificate `vault-tls-cert`, covering service, `vault-active`, `*.vault-internal`, `localhost` and `127.0.0.1`;
  - chart values: `global.tlsDisable: false`, a TLS listener, `leader_ca_cert_file` on each `retry_join`, `VAULT_CACERT`, and an HTTPS ingress backend;
  - backup CronJob switched to HTTPS with `VAULT_CACERT`.
- Every `SecretStore` points at `https://vault.vault.svc.cluster.local:8200` with `caProvider` ConfigMap `vault-ca-cert`.

This plan does not cover Vault internal raft cluster TLS (port 8201), which Vault already manages itself. It also does not cover auto-unseal or certificate-rotation automation.

## Starting state and prerequisites

- The repository defines the manifests above. None of this is verified in the cluster.
- The chart's `server.updateStrategyType` is `OnDelete`. Flux updates the StatefulSet template, but running pods keep the old HTTP listener until each one is deleted. A restarted pod comes back sealed and needs a manual unseal with operator-held key shares.
- **Expected disruption:** once Flux reconciles, the HTTPS SecretStores and backup job fail until the Vault pods are restarted onto TLS. ESO keeps existing Kubernetes Secrets, but nothing refreshes during this window. Be ready to roll the pods right after the merge.
- Approvals needed: deleting the Vault pods, which is a destructive restart, and the unseal operations.

## Steps and gates

1. Merge, then confirm that the Flux Kustomizations `trust-manager` and `vault-pki` are Ready.
2. Gate: ClusterIssuer `vault-internal-ca` is Ready. Certificate `vault/vault-tls` is Ready. ConfigMap `vault-ca-cert` exists in `vault` and in one application namespace, checking key names only.
3. Gate: the `vault` Kustomization and HelmRelease are Ready. The StatefulSet template now mounts `/vault/userconfig/vault-tls-cert`.
4. With approval, delete one standby pod, wait for it to start, unseal it, and confirm it rejoins raft (`vault operator raft list-peers`). Repeat for the second standby, then step down the active node and roll it last.
5. Gate: all three pods are Ready over HTTPS (the readiness probe runs `vault status`). `vault status` succeeds inside a pod without `-tls-skip-verify`.
6. Gate: every SecretStore reports `Valid`/Ready and ExternalSecrets show a fresh sync. The `vault-active` ServiceMonitor target is up. `https://vault.cosmos.cboxlab.com` serves the UI.
7. Trigger the backup CronJob manually and confirm the snapshot is uploaded.
8. Complete the recovery gates from ADR 0001 step 1: restore a snapshot to a scratch instance, and run seal/unseal drills.

## Validation and rollback

- Client-side: `kustomize build` plus `kubectl apply --dry-run=client` for `infra/trust-manager`, `infra/vault-pki` (after the trust-manager CRD exists), `apps/vault` and each affected app.
- Rollback: revert the PR, which restores `tls_disable = 1` and HTTP store URLs. Then roll the Vault pods again with approval, since `OnDelete` still applies. Leave the CA and Bundle in place; they are harmless.

## Certificate renewal

- The listener certificate lasts one year and renews 30 days before expiry. Vault reloads listener certificates only at startup or on `SIGHUP`. After renewal, send `SIGHUP` to each Vault server process (or restart and unseal each pod) before the old certificate expires.
- The CA lasts 10 years. If it is rotated, the Bundle publishes the new certificate immediately, so `vault-tls-cert` must be reissued and reloaded at the same time.

## Outcome

Pending.
