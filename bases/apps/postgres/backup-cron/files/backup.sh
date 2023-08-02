set -e

ls /backup

restic backup /backup

restic forget --keep-monthly 12 --keep-last 10 --keep-daily 10 --prune

restic snapshots
