#!/usr/bin/env bash
# Validate a workspace copy the way the repository's CI does. Removes nothing but its own scratch files.
# Usage: validate.sh <homelab-k8s|homelab-iac> [path ...]
set -uo pipefail

REPO="${1:-}"; shift || true
WORKSPACE="${WORKSPACE:-/workspace}"
BIN="$WORKSPACE/bin"
ROOT="$WORKSPACE/$REPO"
CRD_CATALOG="https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"
BUILD="$WORKSPACE/.validate.build.yaml"
ERR="$WORKSPACE/.validate.err"

case "$REPO" in homelab-k8s|homelab-iac) ;; *) echo "usage: validate.sh <homelab-k8s|homelab-iac> [path ...]" >&2; exit 2 ;; esac
[ -d "$ROOT" ] || { echo "no workspace at $ROOT; run setup.sh $REPO first" >&2; exit 2; }

paths=()
for a in "$@"; do paths+=("${a#"$ROOT"/}"); done

case "$REPO" in
  homelab-k8s)
    cd "$ROOT" || exit 2
    if [ "${#paths[@]}" -eq 0 ]; then
      while IFS= read -r kz; do paths+=("$(dirname "$kz")"); done < <(find clusters -name kustomization.yaml | sort)
    fi
    rc=0
    for dir in "${paths[@]}"; do
      [ -f "$dir/kustomization.yaml" ] || { echo "SKIP $dir: no kustomization.yaml"; continue; }
      if grep -Eq '^[[:space:]]*-[[:space:]]*(https?://|ssh://|git@|github\.com/)' "$dir/kustomization.yaml"; then
        echo "SKIP $dir: remote base needs git, which this image lacks; CI validates it"; continue
      fi
      if ! "$BIN/kustomize" build "$dir" > "$BUILD" 2> "$ERR"; then
        echo "FAIL $dir: kustomize build"; sed 's/^/    /' "$ERR"; rc=1; continue
      fi
      if ! "$BIN/kubeconform" -strict -ignore-missing-schemas -schema-location default -schema-location "$CRD_CATALOG" -summary "$BUILD" > "$ERR" 2>&1; then
        echo "FAIL $dir: kubeconform"; sed 's/^/    /' "$ERR"; rc=1; continue
      fi
      echo "OK   $dir ($(grep -c '^kind:' "$BUILD") objects)"
    done
    rm -f -- "$BUILD" "$ERR"
    exit $rc ;;
  homelab-iac)
    cd "$ROOT" || exit 2
    rc=0
    while IFS= read -r py; do
      python3 -m py_compile "$py" 2>/dev/null || { echo "FAIL $py: python syntax"; rc=1; }
    done < <(find . -name '*.py' -not -path './.git/*' | sort)
    echo "homelab-iac has no local validator here: CI runs terraform fmt; the operator runs terraform plan or make after merge. Python files checked: ok=$([ $rc -eq 0 ] && echo yes || echo no)."
    exit $rc ;;
esac
