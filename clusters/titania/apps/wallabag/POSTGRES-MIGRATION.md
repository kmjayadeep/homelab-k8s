# Wallabag PostgreSQL cutover

Wallabag uses PostgreSQL through `pdo_pgsql`, connecting to Helios at `postgres.cosmos.cboxlab.com:5432` as the dedicated `wallabag` role.

The existing SQLite data is intentionally not migrated. The `wallabag-data` PVC is removed as part of this cutover; image assets remain on the `wallabag-images` PVC.

## Required order

1. Apply the Helios PostgreSQL catalog change to create the `wallabag` database and role and include it in hourly backups.
2. Apply the Vault policy change granting the Wallabag ESO role access to `services/postgresql/wallabag`.
3. Generate a dedicated password outside Git, import it with `vault-config/import-wallabag-postgres-password.sh` through stdin, then set the Helios `wallabag` role to the identical value through a secure administrator session.
4. Confirm a Kubernetes pod can resolve `postgres.cosmos.cboxlab.com` and reach TCP/5432. Helios permits the LAN source range; verify the Kubernetes egress source address is permitted.
5. Reconcile the Wallabag application. It initializes a new empty PostgreSQL database. The `wallabag-config-vault` ExternalSecret supplies the password, and Reloader restarts the Deployment when that secret changes.
6. Verify the application and the next Helios database backup.

## Recovery

If PostgreSQL connectivity fails, repair the PostgreSQL configuration or restore the Wallabag database from the Helios backup. The SQLite database is intentionally removed and is not a rollback source.
