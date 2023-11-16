#!/bin/sh

set -e

echo "Starting syncthing"

BASE=/syncthing
CONFIG_DIR=/syncthing/config
DATA_DIR=/syncthing/data

l=$(restic snapshots --latest 1 --json)
if [ "$l" = "[]" ]; then
  echo "No previous backups found, ignoring restore"
  exit 0
fi

if [ "$(ls -A $CONFIG_DIR)" ]; then
 echo "$CONFIG_DIR is not empty, all good"
else
 echo "$CONFIG_DIR is Empty, restoring from backup"
 restic restore latest --path /config --target $BASE
fi

if [ "$(ls -A $DATA_DIR)" ]; then
 echo "$DATA_DIR is not empty, all good"
else
 restic restore latest --path /data --target $BASE
fi
