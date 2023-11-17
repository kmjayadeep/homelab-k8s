#!/bin/sh

set -e

echo "backing up";
restic --verbose backup /data /config
echo "backup successful"
echo "cleaning up old snapshots"
restic forget --keep-monthly 6 --keep-last 7 --keep-daily 10 --prune
echo "current snapshots:"
restic snapshots
