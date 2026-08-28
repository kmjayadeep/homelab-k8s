# AGENTS.md

## Repository

Kubernetes homelab managed through FluxCD GitOps. Cluster manifests live under `clusters/titania/`; Kustomize manages manifests. Vault with External Secrets is the target architecture for application secrets, while Sealed Secrets remains available for bootstrap and unmigrated secrets.

## Safety rules

- **Never read plaintext secrets into agent context.** `*-decrypted.yaml` is a non-encrypted plaintext secret: do not use `read`, `cat`, `grep`, decode commands, logs, or `kubectl get` to display its values, and never commit it. For debugging, use tools to extract only the required YAML structure or non-secret metadata; never echo secret values.
- `*-sealed.yaml` is a Sealed Secret and is the version to commit. Handle decrypted files only through file-to-file pipelines (for example, `kubectl create secret ... --from-file=... | kubeseal ...`).
- Use `kubeseal` with `kubeseal/pub-sealed-secrets.pem` to generate sealed secrets. Create the Kubernetes Secret from the decrypted file and pipe it directly to `kubeseal`; never print or decode the plaintext:
  ```bash
  kubectl create secret generic <name> -n <namespace> --from-file=<key>=<decrypted-file> --dry-run=client -o yaml | kubeseal --format=yaml --cert kubeseal/pub-sealed-secrets.pem > <name>-sealed.yaml
  ```
- **Never perform destructive operations without explicit human approval.** This includes `rm`, `kubectl delete`, pruning/removing Flux resources, force operations, database/data deletion, and destructive rewrites. Explain the impact and wait for approval.
- Do not apply or reconcile changes to the cluster unless explicitly requested.

## Vault and External Secrets

- Before changing Vault, the External Secrets Operator, `SecretStore`/`ClusterSecretStore` resources, `ExternalSecret` resources, or migrating a SealedSecret, read and follow `adrs/0001-vault-external-secrets.md`.
- Store application secret values in Vault, never in Git. Git may contain only non-secret references, policies, roles, and External Secrets manifests.
- Use Vault Kubernetes authentication and least-privilege namespaced stores by default; do not introduce static Vault tokens or a broad `ClusterSecretStore` without explicit approval.
- Keep Vault recovery/unseal material and the initial root token outside both Git and the cluster.
- Do not remove a working SealedSecret during migration until the replacement ExternalSecret is verified and removal is explicitly approved.

## Conventions

- Use 2-space YAML indentation. Put `apiVersion` and `kind` first.
- Keep app-specific manifests in `clusters/titania/apps/<app>/` with a `kustomization.yaml`.
- Define resource requests and limits, plus readiness and liveness probes, for workloads.
- Use standard Kubernetes labels, including `app.kubernetes.io/name` and `app.kubernetes.io/instance`.
- Use TLS for ingresses where certificates are available.

## Validation

```bash
# Build and validate an app or infrastructure kustomization
kustomize build clusters/titania/apps/<app> | kubectl apply --dry-run=client -f -
kustomize build clusters/titania/infra/<component> | kubectl apply --dry-run=client -f -

# Inspect Flux state when requested
flux get all -n flux-system
```

Run the relevant Kustomize build and client dry-run after manifest changes. Report validation results and any remaining risks.
