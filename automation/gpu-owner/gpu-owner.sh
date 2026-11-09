#!/usr/bin/env bash
# Swap which Deployment owns the single Intel Arc Pro B60 on titania-gpu.
#
#   gpu-owner.sh status    show who holds the GPU and whether Flux is suspended
#   gpu-owner.sh comfyui   suspend Flux for both apps, scale the LLM to 0, ComfyUI to 1
#   gpu-owner.sh llm       scale ComfyUI to 0, resume Flux (Git state: LLM 1, ComfyUI 0)
#
# Git is the default state (ADR 0004: the LLM owns the GPU). "comfyui" is a deviation that
# only exists while Flux is suspended with our marker; "llm" is simply a Flux resume, so the
# rollback path is Flux itself. The GPU plugin advertises exactly one gpu.intel.com/xe, so
# even a mistake here cannot make both pods run at once: the second stays Pending.
#
# Requires kubectl with operator access (flux CLI not needed). Plan 0029, ADR 0008.
set -euo pipefail

MARKER="gpu-owner.cboxlab.com/suspended-by"
LLM_NS=llm-serving; LLM_KS=llm-serving-intel-llama; LLM_DEPLOY=intel-llama-ornith
IMG_NS=comfyui;     IMG_KS=comfyui;                 IMG_DEPLOY=comfyui
AUTORESEARCH_MARKER="llm-autoresearch.cboxlab.com/suspended-by"
KS_KIND=kustomizations.kustomize.toolkit.fluxcd.io

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

ks_json() { kubectl -n "$1" get "$KS_KIND" "$2" -o json; }
ks_suspended() { ks_json "$1" "$2" | python3 -c 'import json,sys; print(str(bool(json.load(sys.stdin)["spec"].get("suspend"))).lower())'; }
ks_marker() { ks_json "$1" "$2" | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata'].get('annotations',{}).get('$3',''))"; }

patch_ks() { # ns name json
  kubectl -n "$1" patch "$KS_KIND" "$2" --type=merge --field-manager=flux-client-side-apply -p "$3" >/dev/null
}

available() { kubectl -n "$1" get deploy "$2" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0; }

status() {
  printf '%-28s %-10s %-9s %s\n' DEPLOYMENT AVAILABLE FLUX MARKER
  for t in "$LLM_NS $LLM_KS $LLM_DEPLOY" "$IMG_NS $IMG_KS $IMG_DEPLOY"; do
    set -- $t
    s=$(ks_suspended "$1" "$2"); [ "$s" = true ] && f=suspended || f=active
    a=$(available "$1" "$3")
    printf '%-28s %-10s %-9s %s\n' "$1/$3" "${a:-0}" "$f" "$(ks_marker "$1" "$2" "$MARKER")"
  done
  kubectl get node -l gpu.intel.com/product=arc-pro-b60 -o custom-columns='NODE:.metadata.name,XE_ALLOCATABLE:.status.allocatable.gpu\.intel\.com/xe' --no-headers | sed 's/^/node: /'
}

to_comfyui() {
  if [ -n "$(ks_marker "$LLM_NS" "$LLM_KS" "$AUTORESEARCH_MARKER")" ]; then
    echo "REJECTED: an autoresearch session holds $LLM_KS; finish it first" >&2; exit 1
  fi
  for t in "$LLM_NS $LLM_KS" "$IMG_NS $IMG_KS"; do
    set -- $t
    if [ "$(ks_suspended "$1" "$2")" = true ] && [ -z "$(ks_marker "$1" "$2" "$MARKER")" ]; then
      echo "REJECTED: Flux Kustomization $1/$2 is suspended by someone else; not taking over" >&2; exit 1
    fi
  done
  who="${USER:-operator}@$(hostname -s 2>/dev/null || echo host)"
  log "suspending Flux for $LLM_KS and $IMG_KS (marker $MARKER=$who)"
  patch_ks "$LLM_NS" "$LLM_KS" "{\"metadata\":{\"annotations\":{\"$MARKER\":\"$who\"}},\"spec\":{\"suspend\":true}}"
  patch_ks "$IMG_NS" "$IMG_KS" "{\"metadata\":{\"annotations\":{\"$MARKER\":\"$who\"}},\"spec\":{\"suspend\":true}}"
  log "stopping $LLM_DEPLOY (qwen-intel/sensitive go down; local-first falls back to DeepSeek)"
  kubectl -n "$LLM_NS" scale deploy "$LLM_DEPLOY" --replicas=0
  kubectl -n "$LLM_NS" wait --for=delete pod -l app.kubernetes.io/name="$LLM_DEPLOY" --timeout=5m
  log "starting $IMG_DEPLOY"
  kubectl -n "$IMG_NS" scale deploy "$IMG_DEPLOY" --replicas=1
  kubectl -n "$IMG_NS" rollout status deploy "$IMG_DEPLOY" --timeout=30m
  log "ComfyUI owns the B60: https://comfyui.cosmos.cboxlab.com"
}

to_llm() {
  log "stopping $IMG_DEPLOY"
  kubectl -n "$IMG_NS" scale deploy "$IMG_DEPLOY" --replicas=0
  kubectl -n "$IMG_NS" wait --for=delete pod -l app.kubernetes.io/name="$IMG_DEPLOY" --timeout=5m
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  for t in "$LLM_NS $LLM_KS" "$IMG_NS $IMG_KS"; do
    set -- $t
    if [ "$(ks_suspended "$1" "$2")" = true ] && [ -z "$(ks_marker "$1" "$2" "$MARKER")" ]; then
      log "leaving $1/$2 suspended: it was not suspended by this script"; continue
    fi
    log "resuming Flux for $2"
    patch_ks "$1" "$2" "{\"metadata\":{\"annotations\":{\"$MARKER\":null,\"reconcile.fluxcd.io/requestedAt\":\"$now\"}},\"spec\":{\"suspend\":false}}"
  done
  log "waiting for Flux to restore $LLM_DEPLOY from Git"
  for _ in $(seq 1 60); do
    [ "$(available "$LLM_NS" "$LLM_DEPLOY")" = 1 ] && { log "LLM owns the B60 again (qwen-intel up)"; return; }
    sleep 10
  done
  echo "LLM not available 10 minutes after resume; check: flux get ks -n $LLM_NS" >&2; exit 1
}

case "${1:-}" in
  status) status ;;
  comfyui) to_comfyui ;;
  llm) to_llm ;;
  *) sed -n '2,13p' "$0" >&2; exit 2 ;;
esac
