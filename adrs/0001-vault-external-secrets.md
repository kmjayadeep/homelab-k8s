# ADR 0001: Use Vault with External Secrets for application secrets

- Status: Accepted
- Date: 2026-08-28

## Context

This repository currently uses Sealed Secrets to keep encrypted Kubernetes Secret values in Git. The cluster also runs HashiCorp Vault from `clusters/titania/apps/vault/`, and the External Secrets Operator (ESO) is installed from `clusters/titania/infra/external-secrets/`.

Sealed Secrets is simple and remains useful during bootstrap, but routine rotation requires creating and committing a new sealed value. It also makes Git history the long-term store for every encrypted value. Vault provides centralized access control, auditing, and rotation, while ESO translates values from Vault into Kubernetes Secrets consumed by existing workloads.

ESO is a reconciler, not a secret store. Installing the operator alone does not move or create any application secrets. Vault integration and individual `ExternalSecret` resources must be configured separately.

## Decision

Vault will be the source of truth for application secrets. ESO will synchronize those values into ordinary Kubernetes Secrets.

Sealed Secrets will remain available only for bootstrap data that cannot be obtained from Vault. Existing sealed secrets will be migrated incrementally rather than removed in bulk.

### Secret locations

Secret material is stored in these locations:

1. **Vault KV v2** stores application values under `secret/apps/<namespace>/<application>/...`.
2. **Kubernetes etcd** holds the Kubernetes Secrets materialized by ESO. Encryption at rest must be enabled and maintained for the cluster datastore.
3. **An offline password manager** stores Vault recovery/unseal material and the initial root token. These values must never be stored in this repository or in a Kubernetes Secret managed by ESO.

Git stores only non-secret declarations:

- `SecretStore` resources describing how a namespace authenticates to Vault.
- `ExternalSecret` resources containing Vault paths and key mappings.
- ServiceAccounts and non-secret Vault role names.
- Vault policy/configuration automation that contains no credentials.

Vault paths and property names can disclose system structure. Treat this metadata as internal even though it is not secret material.

### Authentication and authorization

ESO must use Vault's Kubernetes authentication method. Long-lived Vault tokens must not be placed in Git or used as the normal controller credential.

Use a namespaced `SecretStore` and a dedicated ServiceAccount for each application or trust boundary. Bind that ServiceAccount to a narrowly scoped Vault role and policy. A policy should permit reading only the application's path, for example `secret/data/apps/<namespace>/<application>/*` and the corresponding KV metadata path when required.

A broad, shared `ClusterSecretStore` is not the default because any permitted `ExternalSecret` could otherwise request secrets belonging to another application. Any exception requires an explicit security review and documentation of the shared trust boundary.

Vault Kubernetes-auth configuration and policies are administered directly in Vault until declarative Vault configuration management is introduced. They must not contain static credentials in Git.

### TLS

ESO must connect to Vault over TLS and validate Vault's CA. The CA certificate may be stored in a ConfigMap because it is public material. Certificate private keys remain Kubernetes Secrets managed by cert-manager or another bootstrap-safe mechanism.

The current Vault configuration uses `tls_disable = 1`; therefore Vault must be given a trusted internal TLS configuration before ESO is used for production application secrets. Plain HTTP is not an accepted steady state.

### GitOps layout

- `clusters/titania/apps/vault/`: Vault deployment.
- `clusters/titania/infra/external-secrets/`: ESO Helm deployment and CRDs.
- `clusters/titania/apps/<application>/`: application ServiceAccount, `SecretStore`, and `ExternalSecret` resources.
- `clusters/titania/bootstrap/`: Flux Kustomizations and ordering dependencies.

Application Flux Kustomizations using an `ExternalSecret` should depend on the Vault and External Secrets Kustomizations where practical. Workloads must tolerate the target Secret being absent while Vault or ESO is unavailable.

An application declaration should follow this shape, with no real values in Git:

```yaml
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata:
  name: vault
spec:
  provider:
    vault:
      server: https://vault.vault.svc.cluster.local:8200
      path: secret
      version: v2
      auth:
        kubernetes:
          mountPath: kubernetes
          role: <application-role>
          serviceAccountRef:
            name: external-secrets-vault
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: <application-secret>
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: SecretStore
    name: vault
  target:
    name: <application-secret>
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: <kubernetes-key>
      remoteRef:
        key: apps/<namespace>/<application>
        property: <vault-property>
```

The exact Vault service DNS name and CA reference must be verified when TLS is implemented.

### Migration procedure

Migrate one application at a time:

1. Enable Vault TLS and verify backup, restore, seal, and unseal procedures.
2. Configure the Vault Kubernetes auth method.
3. Create a least-privilege Vault policy and role for the application.
4. Write the secret value to Vault through a secure operator workflow. Never pass it through agent output, shell history, logs, or Git.
5. Add the ServiceAccount, `SecretStore`, and `ExternalSecret` manifests.
6. Validate that ESO reports the store and external secret as ready and that the application remains healthy.
7. After explicit human approval, remove the superseded SealedSecret in a separate change.

Never delete or replace a working SealedSecret during the same unverified rollout that introduces its `ExternalSecret` replacement.

## Consequences

### Benefits

- Values can be rotated in Vault without committing new ciphertext.
- Vault provides centralized audit logs and scoped access policies.
- Applications continue consuming standard Kubernetes Secrets.
- Git contains desired-state references rather than encrypted secret payloads.

### Costs and risks

- Vault and ESO become runtime dependencies for creating and refreshing Secrets.
- Vault authentication, TLS, backup, and disaster recovery add operational complexity.
- ESO-created values still exist in Kubernetes etcd and in pod environments or mounted volumes.
- A compromised ESO identity can read every Vault path allowed by its policies.
- Vault outages do not normally erase existing Kubernetes Secrets, but they prevent refresh and can block new deployments.

## Implementation status

- Vault Helm deployment: present.
- External Secrets Operator Helm deployment: present.
- Vault internal TLS: required before production use.
- Vault Kubernetes authentication: not yet configured.
- Application `SecretStore` and `ExternalSecret` resources: not yet configured.
- Existing SealedSecret migrations: not started by this decision.
