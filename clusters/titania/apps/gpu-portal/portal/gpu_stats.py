#!/usr/bin/env python3
"""Reports B60 VRAM, power, temperature and fan from the host's /proc and sysfs as JSON.

VRAM comes from the xe driver's per-client fdinfo, which is why this pod needs hostPID and
SYS_PTRACE. It exposes totals and process names only.
"""
import glob
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

PROC = os.environ.get("PROC_ROOT", "/proc")
DRM = os.environ.get("DRM_ROOT", "/sys/class/drm")
VRAM_TOTAL = int(os.environ.get("VRAM_TOTAL_BYTES", "25669140480"))
PORT = int(os.environ.get("PORT", "9400"))
CACHE_SECONDS = 2

lock = Lock()
cache = {"at": 0.0, "body": b"{}", "energy": None, "energy_at": 0.0}


def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def parse_fdinfo(text):
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def vram_clients():
    """Sum resident VRAM per process. One DRM client can appear on several fds, so count each once."""
    seen = set()
    totals = {}
    for pid in os.listdir(PROC):
        if not pid.isdigit():
            continue
        fd_dir = os.path.join(PROC, pid, "fd")
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if not os.readlink(os.path.join(fd_dir, fd)).startswith("/dev/dri/"):
                    continue
            except OSError:
                continue
            text = read(os.path.join(PROC, pid, "fdinfo", fd))
            if not text:
                continue
            info = parse_fdinfo(text)
            if info.get("drm-driver") != "xe" or info.get("drm-client-id") in seen:
                continue
            seen.add(info.get("drm-client-id"))
            amount = info.get("drm-resident-vram0", "0 KiB").split()[0]
            comm = read(os.path.join(PROC, pid, "comm")) or "unknown"
            totals[comm] = totals.get(comm, 0) + int(amount) * 1024
    return totals


def hwmon_dir():
    for path in sorted(glob.glob(os.path.join(DRM, "card*/device/hwmon/hwmon*"))):
        if read(os.path.join(path, "name")) == "xe" and os.path.exists(os.path.join(path, "energy1_input")):
            return path
    return None


def package_temperature(path):
    for label in glob.glob(os.path.join(path, "temp*_label")):
        if read(label) == "pkg":
            value = read(label.replace("_label", "_input"))
            return int(value) / 1000 if value else None
    return None


def collect():
    now = time.monotonic()
    clients = vram_clients()
    used = sum(clients.values())
    power = temperature = fan = None
    path = hwmon_dir()
    if path:
        temperature = package_temperature(path)
        value = read(os.path.join(path, "fan1_input"))
        fan = int(value) if value else None
        value = read(os.path.join(path, "energy1_input"))
        if value:
            energy = int(value)
            if cache["energy"] is not None and now > cache["energy_at"] and energy >= cache["energy"]:
                power = round((energy - cache["energy"]) / 1e6 / (now - cache["energy_at"]), 1)
            cache["energy"], cache["energy_at"] = energy, now
    return {
        "vram_used_bytes": used,
        "vram_total_bytes": VRAM_TOTAL,
        "clients": [{"process": name, "vram_bytes": size} for name, size in sorted(clients.items(), key=lambda item: -item[1])],
        "power_watts": power,
        "temperature_celsius": temperature,
        "fan_rpm": fan,
    }


def stats_body():
    with lock:
        if time.monotonic() - cache["at"] >= CACHE_SECONDS:
            cache["body"] = json.dumps(collect()).encode()
            cache["at"] = time.monotonic()
        return cache["body"]


class Handler(BaseHTTPRequestHandler):
    server_version = "gpu-stats"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path == "/stats":
            body = stats_body()
            kind = "application/json"
            status = 200
        elif self.path == "/healthz":
            body, kind, status = b"ok\n", "text/plain", 200
        else:
            body, kind, status = b"not found\n", "text/plain", 404
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
