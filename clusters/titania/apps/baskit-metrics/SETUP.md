# Baskit Metrics Setup Guide

## Prerequisites

- kubeseal installed
- GitHub Personal Access Token with `read:packages` scope

## Setup Steps

### 1. Create GitHub Personal Access Token

1. Go to https://github.com/settings/tokens/new
2. Create a token with the following scope:
   - ✅ `read:packages` (Download packages from GitHub Package Registry)
3. Copy the token (you won't be able to see it again)

### 2. Create GHCR Pull Secret

```bash
cd clusters/titania/apps/baskit-metrics

# Generate base64 encoded credentials
echo -n "your-github-username:ghp_YourTokenHere" | base64

# Edit ghcr-secret-decrypted.yaml and update:
# - username: your GitHub username
# - password: your GitHub token (ghp_...)
# - auth: the base64 string from above
nano ghcr-secret-decrypted.yaml

# Seal the secret
kubeseal --controller-name=sealed-secrets --controller-namespace=sealed-secrets \
  --format=yaml < ghcr-secret-decrypted.yaml > ghcr-secret-sealed.yaml
```

### 3. Create Firebase Credentials Secret

You've already done this! The sealed secret is in `secret-sealed.yaml`.

### 4. Verify and Deploy

```bash
# Check that both sealed secrets exist
ls -la *-sealed.yaml
# Should show:
# - ghcr-secret-sealed.yaml
# - secret-sealed.yaml

# Add to git (DO NOT commit *-decrypted.yaml files)
git add *.yaml
git add SETUP.md

# Verify you're not committing secrets
git diff --cached | grep -i "decrypted" && echo "⚠️  WARNING: decrypted files found!" || echo "✅ Safe to commit"

# Commit and push
git commit -m "Add baskit-metrics with GHCR authentication"
git push
```

### 5. Monitor Deployment

```bash
# Watch the deployment
kubectl -n baskit get pods -w

# Check logs
kubectl -n baskit logs -l app=baskit-metrics

# Verify metrics endpoint
kubectl -n baskit port-forward svc/baskit-metrics 8080:8080
curl http://localhost:8080/metrics
```

## Troubleshooting

### ImagePullBackOff Error

If you see `ImagePullBackOff`:

```bash
# Check the pod events
kubectl -n baskit describe pod -l app=baskit-metrics

# Verify the secret exists
kubectl -n baskit get secret ghcr-secret

# Test pulling the image manually
docker pull ghcr.io/kmjayadeep/baskit/metrics-server:latest
```

Common issues:
- Token doesn't have `read:packages` scope
- Base64 encoding is incorrect (make sure to use `echo -n`)
- Token has expired
- Repository visibility changed

### Firebase Connection Issues

```bash
# Check logs for Firestore errors
kubectl -n baskit logs -l app=baskit-metrics | grep -i firestore

# Verify the secret is mounted
kubectl -n baskit exec -it deploy/baskit-metrics -- ls -la /secrets/

# Test the readiness probe
kubectl -n baskit exec -it deploy/baskit-metrics -- wget -qO- http://localhost:8080/readyz
```

## Alternative: Make GHCR Package Public

If you want to avoid the ImagePullSecret:

1. Go to https://github.com/users/kmjayadeep/packages/container/baskit%2Fmetrics-server/settings
2. Scroll to "Danger Zone"
3. Click "Change visibility"
4. Select "Public"

Then you can remove the `imagePullSecrets` from the deployment.

