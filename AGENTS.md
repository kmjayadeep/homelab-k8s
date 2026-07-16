# AGENTS.md

## Repository

Kubernetes homelab managed through FluxCD GitOps. Cluster manifests live under `clusters/titania/`; Kustomize manages manifests and Sealed Secrets manages sensitive values.

## Safety rules

- **Never read plaintext secrets into agent context.** `*-decrypted.yaml` is a non-encrypted plaintext secret: do not use `read`, `cat`, `grep`, decode commands, logs, or `kubectl get` to display its values, and never commit it. For debugging, use tools to extract only the required YAML structure or non-secret metadata; never echo secret values.
- `*-sealed.yaml` is a Sealed Secret and is the version to commit. Handle decrypted files only through file-to-file pipelines (for example, `kubectl create secret ... --from-file=... | kubeseal ...`).
- Use `kubeseal` with `kubeseal/pub-sealed-secrets.pem` to generate sealed secrets. Create the Kubernetes Secret from the decrypted file and pipe it directly to `kubeseal`; never print or decode the plaintext:
  ```bash
  kubectl create secret generic <name> -n <namespace> --from-file=<key>=<decrypted-file> --dry-run=client -o yaml | kubeseal --format=yaml --cert kubeseal/pub-sealed-secrets.pem > <name>-sealed.yaml
  ```
- **Never perform destructive operations without explicit human approval.** This includes `rm`, `kubectl delete`, pruning/removing Flux resources, force operations, database/data deletion, and destructive rewrites. Explain the impact and wait for approval.
- Do not apply or reconcile changes to the cluster unless explicitly requested.

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
