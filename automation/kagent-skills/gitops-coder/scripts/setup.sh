#!/usr/bin/env bash
# Prepare the gitops-coder workspace: pinned validators plus a fresh copy of one repository.
# Usage: setup.sh <homelab-k8s|homelab-iac> [ref]
#
# Removal safety: the only directories ever removed are ones this script created itself, recognised by
# a marker file, and only when they sit under an absolute, non-root $WORKSPACE.
set -euo pipefail

REPO="${1:-}"
REF="${2:-main}"
OWNER="kmjayadeep"
WORKSPACE="${WORKSPACE:-/workspace}"
MARKER=".gitops-coder-owned"

KUSTOMIZE_VERSION="v5.8.3"
KUSTOMIZE_SHA256="cb9e31198d3f63b44848bd0afc4c8efc56e6cfef9c93a4a39a211940e6decd61"
KUBECONFORM_VERSION="v0.7.0"
KUBECONFORM_SHA256="c31518ddd122663b3f3aa874cfe8178cb0988de944f29c74a0b9260920d115d3"

die() { echo "setup.sh: $*" >&2; exit 2; }

case "$REPO" in
  homelab-k8s|homelab-iac) ;;
  *) die "usage: setup.sh <homelab-k8s|homelab-iac> [ref]" ;;
esac
case "$REF" in
  ""|*/*|*..*|-*|*[!A-Za-z0-9._-]*) die "refusing ref '$REF'" ;;
esac
# $WORKSPACE must be an absolute path with at least one component, no '..', not '/'.
case "$WORKSPACE" in
  ""|/|//*|*/|*..*|*[[:space:]]*) die "refusing WORKSPACE='$WORKSPACE'" ;;
  /?*) ;;
  *) die "WORKSPACE must be absolute, got '$WORKSPACE'" ;;
esac

# Remove a directory only if it is strictly inside $WORKSPACE and carries our marker file.
remove_owned_dir() {
  local d="$1"
  case "$d" in
    "$WORKSPACE"/?*) ;;
    *) die "refusing to remove '$d': not inside $WORKSPACE" ;;
  esac
  case "$d" in *..*) die "refusing to remove '$d': contains '..'" ;; esac
  [ -L "$d" ] && die "refusing to remove '$d': symlink"
  [ -e "$d" ] || return 0
  [ -d "$d" ] || die "refusing to remove '$d': not a directory"
  [ -f "$d/$MARKER" ] || die "refusing to remove '$d': no $MARKER marker (not created by this script)"
  rm -rf -- "$d"
}

BIN="$WORKSPACE/bin"
mkdir -p "$BIN" "$WORKSPACE/.orig"
tmp="$(mktemp -d "$WORKSPACE/.tmp.XXXXXX")"
: > "$tmp/$MARKER"
trap 'remove_owned_dir "$tmp"' EXIT

fetch_checked() { # url sha256 dest
  curl -fsSL --retry 3 -o "$tmp/dl" "$1"
  echo "$2  $tmp/dl" | sha256sum -c - >/dev/null
  mv -- "$tmp/dl" "$3"
}

if [ ! -x "$BIN/kustomize" ]; then
  fetch_checked "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" "$KUSTOMIZE_SHA256" "$tmp/kustomize.tgz"
  tar -xzf "$tmp/kustomize.tgz" -C "$BIN" kustomize
fi
if [ ! -x "$BIN/kubeconform" ]; then
  fetch_checked "https://github.com/yannh/kubeconform/releases/download/${KUBECONFORM_VERSION}/kubeconform-linux-amd64.tar.gz" "$KUBECONFORM_SHA256" "$tmp/kubeconform.tgz"
  tar -xzf "$tmp/kubeconform.tgz" -C "$BIN" kubeconform
fi

sha="$(curl -fsSL --retry 3 -H 'Accept: application/vnd.github.sha' "https://api.github.com/repos/$OWNER/$REPO/commits/$REF" || true)"
curl -fsSL --retry 3 -o "$tmp/repo.tgz" "https://codeload.github.com/$OWNER/$REPO/tar.gz/$REF"
mkdir -p "$tmp/x"
tar -xzf "$tmp/repo.tgz" -C "$tmp/x" --strip-components=1
: > "$tmp/x/$MARKER"

dest="$WORKSPACE/$REPO"
orig="$WORKSPACE/.orig/$REPO"
remove_owned_dir "$dest"
remove_owned_dir "$orig"
cp -a -- "$tmp/x" "$orig"
mv -- "$tmp/x" "$dest"
printf '%s\n' "${sha:-unknown}" > "$WORKSPACE/$REPO.sha"

echo "workspace: $dest ($REPO@$REF, commit ${sha:-unknown})"
echo "pristine:  $orig"
echo "tools:     kustomize $("$BIN/kustomize" version 2>/dev/null | head -1), kubeconform $("$BIN/kubeconform" -v 2>/dev/null)"
