#!/usr/bin/env bash
# Show what changed in the workspace copy relative to the pristine checkout. Read-only.
# Usage: changed.sh <homelab-k8s|homelab-iac>
set -uo pipefail
REPO="${1:-}"
WORKSPACE="${WORKSPACE:-/workspace}"
case "$REPO" in homelab-k8s|homelab-iac) ;; *) echo "usage: changed.sh <homelab-k8s|homelab-iac>" >&2; exit 2 ;; esac
[ -d "$WORKSPACE/$REPO" ] && [ -d "$WORKSPACE/.orig/$REPO" ] || { echo "no workspace for '$REPO'; run setup.sh first" >&2; exit 2; }
cd "$WORKSPACE" || exit 2
echo "## Files"
diff -rq ".orig/$REPO" "$REPO" | sed -E "s#^Files \.orig/$REPO/(.*) and $REPO/.* differ#M \1#; s#^Only in $REPO/?([^:]*): (.*)#A \1/\2#; s#^Only in \.orig/$REPO/?([^:]*): (.*)#D \1/\2#; s#^A /#A #; s#^D /#D #" | grep -v '\.gitops-coder-owned$' | sort
echo
echo "## Diff"
diff -ruN ".orig/$REPO" "$REPO" | sed -E "s#^--- \.orig/$REPO/#--- a/#; s#^\+\+\+ $REPO/#+++ b/#"
exit 0
