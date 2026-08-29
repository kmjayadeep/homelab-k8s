# ADR 0001: Use Vault with External Secrets for application secrets

- Status: Accepted
- Date: 2026-08-28

## Context

This repository previously used Sealed Secrets to keep encrypted Kubernetes Secret values in Git. The migration described by this ADR is complete: HashiCorp Vault is now the source of truth and the External Secrets Operator (ESO) materializes application and infrastructure Secrets.

Sealed Secrets was simple, but routine rotation required creating and committing a new sealed value and made Git history the long-term store for encrypted values. Vault provides centralized access control, auditing, and rotation, while ESO translates values from Vault into Kubernetes Secrets consumed by workloads.

ESO is a reconciler, not a secret store. Installing the operator alone does not move or create any application secrets. Vault integration and individual `ExternalSecret` resources must be configured separately.

## Decision

Vault will be the source of truth for application secrets. ESO will synchronize those values into ordinary Kubernetes Secrets.

No active SealedSecret resources or manifests remain. The Sealed Secrets controller is retained temporarily but must not be used for new secrets unless an explicit bootstrap exception is documented and approved. Its eventual removal is a separate operational decision.

### Secret locations

Secret material is stored in these locations:

1. **Vault KV v2** stores secret values in the existing `homelab/kv` mount under owner-based `apps/`, `services/`, and `platform/` paths.
2. **Kubernetes etcd** holds the Kubernetes Secrets materialized by ESO. Encryption at rest must be enabled and maintained for the cluster datastore.
3. **An offline password manager** stores Vault recovery/unseal material and the initial root token. These values must never be stored in this repository or in a Kubernetes Secret managed by ESO.

Git stores only non-secret declarations:

- `SecretStore` resources describing how a Kubernetes namespace authenticates to Vault.
- `ExternalSecret` resources containing Vault paths and key mappings.
- ServiceAccounts and non-secret Vault role names.
- Vault policy/configuration automation that contains no credentials.

Vault paths and property names can disclose system structure. Treat this metadata as internal even though it is not secret material.

### Path ownership

Paths identify who owns or issues a credential, not where it is consumed:

- `apps/<application>/<set>` contains secrets owned and rotated with an application.
- `services/<service>/<identity>` contains credentials issued by another service, such as PostgreSQL, GitHub, Cloudflare, or an object store.
- `platform/<component>/<set>` contains operational configuration with secret material that does not have a better application or service owner.

There is no generic `shared/` path. When Kubernetes and a VM intentionally use the same credential, their separate policies grant access to the same owner-based path. Values must not be duplicated solely because consumers use different platforms. Independently rotated or differently scoped identities remain in separate KV documents under the same owner prefix, for example `services/cloudflare/read-only` and `services/cloudflare/dns-cboxlab`. Limited duplication is acceptable when distinct credentials reduce permissions or blast radius.

Database connection components and similar source values are stored once. ESO target templates or application configuration may render consumer-specific formats such as connection URLs without storing a second copy in Vault. KV custom metadata records non-secret operational context such as description, origin, owner, management method, and rotation dates; it must never contain credential material. The detailed path and metadata rules and migration map are maintained in `homelab-iac/vault-config/PATHS.md`.

### Authentication and authorization

ESO must use Vault's Kubernetes authentication method. Long-lived Vault tokens must not be placed in Git or used as the normal controller credential.

Use a Kubernetes-namespaced `SecretStore` and a dedicated ServiceAccount for each application or trust boundary. Bind that ServiceAccount to a narrowly scoped Vault role and policy. A policy should permit reading only the application's path, for example `homelab/kv/data/apps/<application>` and its descendants, plus the corresponding KV metadata paths when required.

This deployment uses Vault OSS and does not use Vault Enterprise namespaces. References to namespaces in Kubernetes resources and auth-role bindings mean Kubernetes namespaces only; they are not part of the Vault secret path.

The KV mount is not used as an access-control boundary. Kubernetes workloads and non-Kubernetes consumers such as VMs may read the same application path when they legitimately share a secret. Each consumer must authenticate through an appropriate Vault auth method and receive an explicit least-privilege policy; secret values should not be copied into a second mount merely to serve a different platform.

A broad, shared `ClusterSecretStore` is not the default because any permitted `ExternalSecret` could otherwise request secrets belonging to another application. Any exception requires an explicit security review and documentation of the shared trust boundary.

Vault Kubernetes-auth configuration, application roles, and policies are managed declaratively in `homelab-iac/vault-config/`. This configuration contains no static credentials or secret values. Secret values are written through a separate secure operator workflow.

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
      path: homelab/kv
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
        key: apps/<application>
        property: <vault-property>
```

The exact Vault service DNS name and CA reference must be verified when TLS is implemented.

### Completed migration procedure

The migration followed steps 2–7 below. The operator explicitly deferred step 1 because Vault initially contained little data; internal TLS and full recovery verification therefore remain open gates rather than completed work.

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
- Vault Kubernetes authentication and least-privilege application roles: deployed and managed by `homelab-iac/vault-config/`.
- Application `SecretStore` and `ExternalSecret` resources: deployed for all active application and infrastructure Secrets inventoried during this migration.
- Existing SealedSecret migrations: complete; no SealedSecret resources or manifests remain in the cluster configuration.
- Sealed Secrets controller: retained temporarily until a separate removal decision.
- Vault internal TLS: still required; ESO currently uses the explicitly accepted temporary HTTP endpoint.
