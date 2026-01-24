# AGENTS.md

This file contains guidelines and commands for agentic coding agents working in this homelab Kubernetes repository.

## Repository Overview

This is a Kubernetes homelab repository using FluxCD for GitOps deployment. The repository contains manifests for multiple clusters (currently `titania`) with applications and infrastructure components.

- **GitOps Tool**: FluxCD
- **Manifest Management**: Kustomize
- **Secrets Management**: Sealed Secrets
- **Clusters**: titania (and potentially others)

## Build/Lint/Test Commands

### Single Test Commands
```bash
# Validate a single manifest file
kubectl --dry-run=client apply -f clusters/titania/apps/vaultwarden/deploy.yaml

# Validate a single app's kustomization
kustomize build clusters/titania/apps/<app-name> | kubectl --dry-run=client apply -f -

# Test a single kustomization build
kustomize build clusters/titania/apps/<app-name>

# Validate secret encryption
kubeseal --format=yaml --cert kubeseal/pub-sealed-secrets.pem < secret.yaml | kubectl --dry-run=client apply -f -
```

### Batch Validation
```bash
# Validate all manifests in the repository
find . -name "*.yaml" -type f -exec kubectl --dry-run=client apply -f {} \;

# Validate cluster-specific manifests
find clusters/titania -name "*.yaml" -type f -exec kubectl --dry-run=client apply -f {} \;

# Validate with kubeconform (if available)
kubeconform -summary clusters/titania
```

### FluxCD Operations
```bash
# Check FluxCD status
flux get all -n flux-system

# Reconcile specific kustomization
flux reconcile kustomization <kustomization-name> -n flux-system

# Check Flux logs
flux logs -f
```

## Code Style Guidelines

### YAML Formatting
- Use 2 spaces for indentation (not tabs)
- Ensure consistent spacing in lists and mappings
- Use `apiVersion` and `kind` as the first two fields
- Follow Kubernetes field ordering: metadata, spec, status (if present)

### Resource Naming Conventions
- **Deployments**: Use app name (e.g., `vaultwarden`)
- **Services**: Use app name (e.g., `vaultwarden`)
- **Ingress**: Use `<app-name>-ingress` pattern
- **PVCs**: Use `<app-name>-pvc` pattern
- **Secrets**: Use descriptive names with `-secret` suffix

### Labels and Annotations
```yaml
# Standard labels for applications
labels:
  app.kubernetes.io/name: <app-name>
  app.kubernetes.io/instance: <app-name>
  app.kubernetes.io/component: <component>

# Common annotations for deployments
annotations:
  kubernetes.io/managed-by: FluxCD
  kustomize.toolkit.fluxcd.io/checksum: <checksum>

# For deployments/pods
selector:
  matchLabels:
    app.kubernetes.io/name: <app-name>
```

### Kustomize Structure
- Each app directory should contain: `kustomization.yaml`, `deploy.yaml`, `service.yaml`, `ingress.yaml`
- Use `kustomization.yaml` to define namespace and resources
- Keep cluster-specific overrides in `clusters/<cluster-name>/apps/<app-name>/`
- Use patches for cluster-specific modifications

### Namespace Management
- Define namespace in kustomization.yaml: `namespace: <namespace-name>`
- Create namespace manifests in `clusters/<cluster-name>/bootstrap/infra/`
- Use consistent naming across clusters

### Resource Limits and Requests
- Always define resource requests and limits for containers
- Use reasonable defaults for homelab environments:
  ```yaml
  resources:
    requests:
      cpu: 100m
      memory: 100Mi
    limits:
      cpu: 200m
      memory: 500Mi
  ```

### Ingress Configuration
- Use TLS with wildcard certificates where available
- Follow standard ingress structure:
  ```yaml
  spec:
    tls:
      - hosts:
          - "*.cosmos.cboxlab.com"
        secretName: cosmos-cboxlab-cert
    rules:
      - host: <app-name>.cosmos.cboxlab.com
        http:
          paths:
            - backend:
                service:
                  name: <app-name>
                  port:
                    number: 80
              path: /
              pathType: Prefix
  ```

### Health Checks
- Always define both `livenessProbe` and `readinessProbe` for applications
- Use appropriate paths and ports for each application
- Consider adding `startupProbe` for applications with long startup times
- Include proper timeout, periodSeconds, and failureThreshold values

### Environment Variables
- Use clear, descriptive environment variable names
- Separate words with underscores (e.g., `SIGNUPS_ALLOWED`)
- Use string values for consistency

### Volume Management
- Use descriptive PVC names: `<app-name>-pvc`
- Define appropriate storage classes and sizes
- Use consistent mount paths across similar applications

### Secret Management
- Never commit plaintext secrets to the repository
- Use sealed-secrets for all sensitive data
- Keep decrypted secrets in `secret-decrypted.yaml` (add to .gitignore)
- Store sealed secrets as `secret-sealed.yaml`

### File Organization
- Keep application manifests together in app directories
- Separate infrastructure components from applications
- Use `bootstrap/` for FluxCD and cluster initialization manifests
- Maintain the existing cluster structure: `clusters/<cluster-name>/`

### Git Workflow
- Commit manifests in logical groups (app by app)
- Use descriptive commit messages following existing patterns
- Validate manifests before committing
- Test changes in a non-production cluster first

## Testing Strategy

### Manual Testing
1. Use `kubectl --dry-run=client` to validate manifest syntax
2. Use `kustomize build` to verify kustomization structure
3. Test in a development cluster before production

### Automated Validation (Recommended)
- Set up pre-commit hooks for manifest validation
- Use kubeconform for Kubernetes resource validation
- Implement CI/CD pipeline checks for manifest syntax

## Common Patterns

### Application Deployment
```yaml
# Standard deployment pattern
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <app-name>
  labels:
    app.kubernetes.io/name: <app-name>
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: <app-name>
  template:
    metadata:
      labels:
        app.kubernetes.io/name: <app-name>
    spec:
      containers:
        - name: <app-name>
          image: <image>:<tag>
          ports:
            - name: http
              containerPort: 80
          livenessProbe:
            httpGet:
              path: /
              port: http
            timeoutSeconds: 5
            periodSeconds: 30
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /
              port: http
            timeoutSeconds: 5
            periodSeconds: 10
            failureThreshold: 3
```

### Service Configuration
```yaml
# Standard service pattern
apiVersion: v1
kind: Service
metadata:
  name: <app-name>
  labels:
    app.kubernetes.io/name: <app-name>
spec:
  ports:
    - name: http
      port: 80
      targetPort: 80
  selector:
    app.kubernetes.io/name: <app-name>
  type: ClusterIP
```

## Tools and Dependencies

- **kubectl**: Required for manifest validation
- **kustomize**: Required for building overlays
- **kubeseal**: Required for secret management
- **flux**: Required for GitOps operations
- **kubeconform**: Recommended for additional validation

## Error Handling

- Always validate manifests before applying
- Check FluxCD logs for deployment issues
- Use `kubectl describe` for troubleshooting pod issues
- Verify sealed secrets encryption before committing