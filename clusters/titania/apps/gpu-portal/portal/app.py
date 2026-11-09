#!/usr/bin/env python3
"""GPU portal: shows what owns the B60 and switches it between validated configs (ADR 0009).

A switch only updates the gpu-active ConfigMaps and requests a Flux reconcile. Flux is the only
thing that changes the workloads. Standard library only, so the app ships as a ConfigMap.
"""
import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

APP_DIR = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("KUBERNETES_API", "https://kubernetes.default.svc")
SA_DIR = os.environ.get("SA_DIR", "/var/run/secrets/kubernetes.io/serviceaccount")
GPU_STATS_URL = os.environ.get("GPU_STATS_URL", "http://gpu-stats.gpu-portal.svc.cluster.local:9400/stats")
PORT = int(os.environ.get("PORT", "8080"))

FLUX_API = "/apis/kustomize.toolkit.fluxcd.io/v1/namespaces/{ns}/kustomizations/{name}"
CONFIGMAP_API = "/api/v1/namespaces/{ns}/configmaps/gpu-active"
DEPLOYMENT_API = "/apis/apps/v1/namespaces/{ns}/deployments/{name}"
PODS_API = "/api/v1/namespaces/{ns}/pods?labelSelector={selector}"

ANNOTATION_SWITCHED_AT = "gpu-portal.cboxlab.com/switched-at"
ANNOTATION_LAST_GOOD = "gpu-portal.cboxlab.com/last-good"
FAIL_AFTER_SECONDS = 1800
BAD_REASONS = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "CreateContainerError", "RunContainerError"}

with open(os.path.join(APP_DIR, "configs.json"), encoding="utf-8") as handle:
    CATALOG = json.load(handle)
CONFIGS = CATALOG["configs"]
BY_ID = {config["id"]: config for config in CONFIGS}
STATE_NAMESPACE = CATALOG["state_namespace"]

log = logging.getLogger("gpu-portal")
switch_lock = Lock()


def k8s(method, path, body=None):
    with open(os.path.join(SA_DIR, "token"), encoding="utf-8") as handle:
        token = handle.read().strip()
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/merge-patch+json"
    request = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    context = None
    if API.startswith("https"):
        context = ssl.create_default_context(cafile=os.path.join(SA_DIR, "ca.crt"))
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        return json.load(response)


def fetch_text(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.read().decode()
    except (OSError, urllib.error.URLError, ValueError):
        return None


def config_workload(config):
    deployment = k8s("GET", DEPLOYMENT_API.format(ns=config["namespace"], name=config["deployment"]))
    selector = urllib.parse.quote(config["selector"])
    pods = k8s("GET", PODS_API.format(ns=config["namespace"], selector=selector))["items"]
    return {
        "spec_replicas": deployment["spec"].get("replicas", 0),
        "available": deployment["status"].get("availableReplicas", 0),
        "pods": pods,
    }


def pod_detail(pod):
    """Return (bad_reason, phase_text) for one pod."""
    status = pod.get("status", {})
    bad = None
    init_running = False
    for container in status.get("initContainerStatuses", []):
        waiting = container.get("state", {}).get("waiting", {})
        if waiting.get("reason") in BAD_REASONS:
            bad = waiting["reason"]
        if "running" in container.get("state", {}):
            init_running = True
    for container in status.get("containerStatuses", []):
        waiting = container.get("state", {}).get("waiting", {})
        if waiting.get("reason") in BAD_REASONS:
            bad = waiting["reason"]
    if status.get("phase") == "Pending" and init_running:
        return bad, "Downloading or verifying model files"
    if status.get("phase") == "Pending":
        return bad, "Waiting for the GPU"
    return bad, "Loading the model"


def parse_llama_metrics(text):
    values = {}
    for line in text.splitlines():
        if line.startswith("llamacpp:"):
            name, _, value = line.partition(" ")
            try:
                values[name] = float(value)
            except ValueError:
                pass
    return {
        "tokens_per_second": values.get("llamacpp:predicted_tokens_seconds"),
        "in_flight": values.get("llamacpp:requests_processing"),
        "queued": values.get("llamacpp:requests_deferred"),
    }


def active_metrics(config):
    text = fetch_text(config["metrics"]["url"])
    if text is None:
        return None
    if config["metrics"]["type"] == "llama":
        return parse_llama_metrics(text)
    try:
        queue = json.loads(text)
    except ValueError:
        return None
    return {"in_flight": len(queue.get("queue_running", [])), "queued": len(queue.get("queue_pending", []))}


def read_state():
    namespaces = sorted({config["namespace"] for config in CONFIGS})
    configmaps = {ns: k8s("GET", CONFIGMAP_API.format(ns=ns)) for ns in namespaces}
    desired = [c["id"] for c in CONFIGS if configmaps[c["namespace"]].get("data", {}).get(c["variable"]) == "1"]
    annotations = configmaps[STATE_NAMESPACE].get("metadata", {}).get("annotations") or {}

    locked = None
    for name, ns in sorted({(c["kustomization"], c["namespace"]) for c in CONFIGS}):
        if k8s("GET", FLUX_API.format(ns=ns, name=name))["spec"].get("suspend"):
            locked = "Flux is suspended for " + name + ". This usually means an autoresearch session is running."

    workloads = {c["id"]: config_workload(c) for c in CONFIGS}
    target = desired[0] if len(desired) == 1 else None
    phase, step, reason = "unknown", None, None
    if target:
        others_running = [c for c in CONFIGS if c["id"] != target and workloads[c["id"]]["pods"]]
        workload = workloads[target]
        pods = workload["pods"]
        if workload["available"] >= 1 and not others_running:
            phase = "ready"
        else:
            phase = "switching"
            if others_running:
                step = "Stopping " + others_running[0]["name"]
            elif not pods:
                step = "Waiting for Flux to apply the change"
            else:
                bad, step = pod_detail(pods[0])
                if bad:
                    phase, reason = "failed", bad
            switched_at = annotations.get(ANNOTATION_SWITCHED_AT)
            if phase == "switching" and switched_at:
                started = datetime.fromisoformat(switched_at).timestamp()
                if time.time() - started > FAIL_AFTER_SECONDS:
                    phase, reason = "failed", "Not ready after 30 minutes"

    return {
        "desired": target,
        "phase": phase,
        "step": step,
        "reason": reason,
        "locked": locked,
        "switched_at": annotations.get(ANNOTATION_SWITCHED_AT),
        "last_good": annotations.get(ANNOTATION_LAST_GOOD),
        "metrics": active_metrics(BY_ID[target]) if target and phase == "ready" else None,
    }


def public_catalog():
    return [{k: c[k] for k in ("id", "name", "kind", "description", "routes", "stops")} for c in CONFIGS]


def state_payload():
    payload = read_state()
    payload["configs"] = public_catalog()
    stats = fetch_text(GPU_STATS_URL)
    try:
        payload["gpu"] = json.loads(stats) if stats else None
    except ValueError:
        payload["gpu"] = None
    return payload


def switch_to(target_id):
    """Return (http_status, message)."""
    if target_id not in BY_ID:
        return 400, "Unknown config."
    if not switch_lock.acquire(blocking=False):
        return 409, "Another switch is starting."
    try:
        state = read_state()
        if state["locked"]:
            return 423, state["locked"]
        if state["phase"] == "switching":
            return 409, "A switch is already running."
        if state["desired"] == target_id and state["phase"] == "ready":
            return 200, "Already active."

        last_good = state["desired"] if state["phase"] == "ready" else state["last_good"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Stop side first, so the GPU is freed as early as possible.
        ordered = [c for c in CONFIGS if c["id"] != target_id] + [BY_ID[target_id]]
        by_namespace = {}
        for config in ordered:
            by_namespace.setdefault(config["namespace"], {})[config["variable"]] = "1" if config["id"] == target_id else "0"
        for ns, data in by_namespace.items():
            body = {"data": data}
            if ns == STATE_NAMESPACE:
                body["metadata"] = {"annotations": {ANNOTATION_SWITCHED_AT: now, ANNOTATION_LAST_GOOD: last_good}}
            k8s("PATCH", CONFIGMAP_API.format(ns=ns), body)

        requested = {}
        for config in ordered:
            requested[(config["namespace"], config["kustomization"])] = True
        for ns, name in requested:
            k8s("PATCH", FLUX_API.format(ns=ns, name=name), {"metadata": {"annotations": {"reconcile.fluxcd.io/requestedAt": now}}})
        log.info("switch to %s requested", target_id)
        return 202, "Switching."
    finally:
        switch_lock.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "gpu-portal"
    sys_version = ""

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/healthz", "/api/state")):
            log.info("%s %s", self.command, self.path)

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        self.send_body(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self):
        if self.path == "/healthz":
            self.send_body(200, b"ok\n", "text/plain")
        elif self.path == "/":
            with open(os.path.join(APP_DIR, "index.html"), "rb") as handle:
                self.send_body(200, handle.read(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            try:
                self.send_json(200, state_payload())
            except (OSError, urllib.error.URLError, KeyError, ValueError):
                log.exception("state failed")
                self.send_json(502, {"error": "Could not read cluster state."})
        else:
            self.send_body(404, b"not found\n", "text/plain")

    def same_origin(self):
        origin = self.headers.get("Origin", "")
        return bool(origin) and urllib.parse.urlparse(origin).netloc == self.headers.get("Host", "")

    def do_POST(self):
        if self.path != "/api/switch":
            self.send_body(404, b"not found\n", "text/plain")
            return
        if self.headers.get("Content-Type") != "application/json" or not self.same_origin():
            self.send_json(403, {"error": "Request refused."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError
            target = json.loads(self.rfile.read(length))["config"]
            status, message = switch_to(target)
        except (ValueError, KeyError, TypeError):
            self.send_json(400, {"error": "Bad request."})
            return
        except (OSError, urllib.error.URLError):
            log.exception("switch failed")
            self.send_json(502, {"error": "The switch could not be completed. Check the state before trying again."})
            return
        self.send_json(status, {"message": message} if status < 400 else {"error": message})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
