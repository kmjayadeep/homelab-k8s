# Longhorn Restore Runbook

## Backup Configuration

- **Schedule**: Daily at 04:00 UTC (`daily-backup`)
- **Retention**: 3 backups retained
- **Concurrency**: 1 backup at a time
- **Labels**: `cluster: cosmos`, `backup: daily`

## Prerequisites

- Longhorn UI access or `lhctl` / `kubectl` with `longhorn-system` access
- Network access to Longhorn backup targets (S3-compatible object storage or NFS)
- `kubectl` with cluster admin access

## Restore Procedures

### 1. Manual backup creation

If you need a point-in-time backup before making risky changes:

```bash
# List current volumes
kubectl get volumeattachment -n longhorn-system

# Create a manual backup via Longhorn UI:
#   Longhorn UI → Volumes → select volume → More → Create Snapshot
#   Then: More → Create Backup

# Or via kubectl (if lhctl is available):
lhctl backup-create <volume-name> --labels cluster=cosmos,backup=manual
```

### 2. Restore from snapshot

For volume-level restore:

```bash
# List available snapshots
kubectl get snapshot -n longhorn-system

# Create a new volume from a snapshot via UI:
#   Longhorn UI → Snapshots → select volume → select snapshot → More → Restore to volume
#   Provide a new volume name

# Or via kubectl:
kubectl create -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: <new-volume-name>
  namespace: longhorn-system
spec:
  fromBackup: <backup-url>
  size: <size-in-GB>
  numberOfReplicas: 3
  staleReplicaTimeout: 30
  engineImage: <engine-image>
EOF
```

### 3. Restore from backup URL (S3/NFS)

If the backup target is accessible:

```bash
# Get backup URL from existing volume
kubectl get volume <volume-name> -n longhorn-system -o jsonpath='{.spec.fromBackup}'

# Restore using the backup URL
lhctl restore <backup-url> <new-volume-name>
```

### 4. Reconcile from GitOps (recommended)

For most restore scenarios, the GitOps approach is preferred:

1. Identify the state you want to restore to (specific commit or manifest state)
2. If the state is already in Git, reconcile that revision:
   ```bash
   # Find the commit with the desired state
   git log --oneline -- clusters/titania/apps/<app>/
   
   # Switch Flux to that revision (via branch or tag)
   flux set source git flux-system --revision=<commit-hash>
   ```
3. Flux will reconcile the desired state automatically

### 5. PostgreSQL restore (wallabag, beancount, etc.)

For database-specific restores:

```bash
# Connect to the PostgreSQL pod
kubectl exec -it -n <namespace> <postgres-pod> -- psql -U <user> -d <database>

# Or restore from a PostgreSQL dump:
kubectl exec -i -n <namespace> <postgres-pod> -- psql -U <user> -d <database> < backup.sql
```

## Verification

After any restore:

1. **Check pod status**:
   ```bash
   kubectl get pods -n <namespace> -l app.kubernetes.io/name=<app>
   ```

2. **Check ESO secret readiness** (if the app uses Vault secrets):
   ```bash
   kubectl get externalsecret -n <namespace>
   ```

3. **Check Longhorn volume status**:
   ```bash
   kubectl get volume -n longhorn-system
   ```

4. **Verify application health**:
   - Check ingress routing
   - Verify TLS certificate
   - Test application endpoint

## Rollback

If a restore goes wrong:

1. Delete the restored volume/secret/manifest
2. Revert to the previous Git revision
3. Reconcile Flux

## Recovery Tests

Run these tests periodically:

1. **Test backup integrity**: Create a manual backup and verify it exists in the backup target
2. **Test volume restore**: Create a test volume from a snapshot and verify data integrity
3. **Test GitOps recovery**: Deploy to a test namespace and verify the full app stack comes up

## Contacts

- Cluster admin: `jayadeep`
- Longhorn docs: https://longhorn.io/docs/
