#!/usr/bin/env python3
"""Fixed evaluator for the B60 autoresearch loop. The agent must NOT edit this file.

Measures whatever is currently serving behind LiteLLM: tool calls, long-context
retrieval, homelab manifests and HumanEval+ code (graded in a network-less
Docker sandbox), plus a fixed-size speed probe. Prints a grep-able summary.

The LiteLLM key is read in-process from `pass litellm/evals` (see
automation/llm-performance/bench.py); it is never printed or written.
"""

import argparse
import gzip
import json
import random
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "llm-performance"))
import bench  # noqa: E402  (load_key, SAFE_OPENER)

ENDPOINT = "https://litellm.cosmos.cboxlab.com/v1"
MODEL = "qwen-intel"
REQUEST_TIMEOUT = 600
MAX_TOKENS = 4096
SPEED_DEPTHS = (0, 8000, 24000)
SPEED_TRIALS = 2
LONGCTX_TOKENS = 16000
# One request near LiteLLM's 114,688-token input cap: decode there is the binding target
# (>= 30 tok/s), and it was 21.8-22.7 tok/s at 105-111K on 2026-10-14 (ADR 0004).
DEEP_TOKENS = 100_000
FILLER_TOKENS_PER_LINE = 28.5  # measured through LiteLLM; the "~17" used by speed() undercounts
PROM_PATH = "/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query"
MEMORY_QUERY = 'node_memory_MemAvailable_bytes{instance="192.168.1.145:9100"}'
MIN_FREE_BYTES = 2 * 2**30
SANDBOX_IMAGE = "llm-autoresearch-sandbox:local"

FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\n(.*?)```", re.S)
THINK = re.compile(r"<think>.*?</think>", re.S)


class Abort(RuntimeError):
    pass


# --- guard -----------------------------------------------------------------


def free_memory_bytes():
    url = PROM_PATH + "?" + urllib.parse.urlencode({"query": MEMORY_QUERY})
    out = subprocess.run(["kubectl", "get", "--raw", url], capture_output=True, text=True, timeout=20, check=True)
    result = json.loads(out.stdout)["data"]["result"]
    return float(result[0]["value"][1]) if result else None


class Guard(threading.Thread):
    """Abort if titania-gpu runs low on memory (a past 128K trial OOMed the host)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.min_free = None
        self.reason = None
        self.halt = threading.Event()

    def run(self):
        last_seen = time.monotonic()
        while not self.halt.is_set():
            try:
                value = free_memory_bytes()
            except Exception:  # noqa: BLE001
                value = None
            if value is not None:
                last_seen = time.monotonic()
                self.min_free = value if self.min_free is None else min(self.min_free, value)
                if value < MIN_FREE_BYTES:
                    self.reason = f"titania-gpu free memory {value / 2**30:.2f} GiB below 2 GiB"
            elif time.monotonic() - last_seen > 90:
                self.reason = "titania-gpu memory not observable for 90s"
            if self.reason:
                return
            self.halt.wait(10)


# --- client ----------------------------------------------------------------


class Client:
    def __init__(self, key, model, guard):
        self.key = key
        self.model = model
        self.guard = guard
        self.failures = 0

    def chat(self, messages, *, seed, max_tokens=MAX_TOKENS, thinking=None, tools=None):
        if self.guard.reason:
            raise Abort(self.guard.reason)
        payload = {"model": self.model, "messages": messages, "max_tokens": max_tokens, "seed": seed}
        if thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": thinking}
        if tools:
            payload["tools"] = tools
        request = urllib.request.Request(
            ENDPOINT + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            started = time.monotonic()
            try:
                with bench.SAFE_OPENER.open(request, timeout=REQUEST_TIMEOUT) as resp:
                    body = json.load(resp)
                break
            except urllib.error.HTTPError as exc:
                error = f"http_{exc.code}"
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
            except (OSError, ValueError, TimeoutError) as exc:
                # Exception text can contain server data; keep only the type.
                error = type(exc).__name__
            self.failures += 1
            if self.failures >= 3:
                raise Abort(f"3 consecutive request failures ({error})")
            return None, {"error": error}
        self.failures = 0
        choice = body["choices"][0]
        timings = body.get("timings") or {}
        return choice.get("message") or {}, {
            "finish_reason": choice.get("finish_reason"),
            "prompt_tokens": (body.get("usage") or {}).get("prompt_tokens"),
            "completion_tokens": (body.get("usage") or {}).get("completion_tokens"),
            "wall_s": round(time.monotonic() - started, 3),
            "timings": {k: timings[k] for k in (
                "prompt_n", "prompt_ms", "prompt_per_second", "predicted_n",
                "predicted_per_second", "draft_n", "draft_n_accepted") if k in timings},
        }


def seed_for(task_id):
    return zlib.crc32(task_id.encode()) & 0x7FFFFFFF


def answer_text(message):
    return THINK.sub("", (message or {}).get("content") or "").strip()


def extract_block(text, langs):
    blocks = FENCE.findall(text)
    preferred = [body for lang, body in blocks if lang.lower() in langs]
    return preferred[-1] if preferred else (blocks[-1][1] if blocks else text)


# --- suites ----------------------------------------------------------------

COLORS = ["red", "blue", "green", "amber", "violet", "cyan", "white", "black"]


def filler(n_lines, seed):
    rng = random.Random(seed)
    return "\n".join(
        f"Entry {i}: sensor {rng.choice(COLORS)}-{rng.randint(100, 999)} reported "
        f"{rng.randint(0, 9999)} units at {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}."
        for i in range(n_lines)
    )


def speed(client, smoke):
    out = []
    depths = SPEED_DEPTHS[:1] if smoke else SPEED_DEPTHS
    for depth in depths:
        for trial in range(1 if smoke else SPEED_TRIALS):
            # Unique first line per call defeats the prompt cache; ~17 tokens per line.
            prompt = "Write a detailed 250-word explanation of how a hash map resolves collisions."
            if depth:
                prompt = (f"Run {time.time_ns()}. Here is a sensor log.\n\n" + filler(depth // 17, f"{depth}-{trial}")
                          + "\n\nIn about 250 words, describe what kinds of entries this log contains.")
            _, rec = client.chat([{"role": "user", "content": prompt}], seed=trial, max_tokens=256, thinking=False)
            out.append({"id": f"depth-{depth}-t{trial}", "depth": depth, **rec})
    return out


def deep(client):
    """Prefill and decode near the context limit, with a cache-busting first line."""
    prompt = (f"Run {time.time_ns()}. Here is a sensor log.\n\n"
              + filler(int(DEEP_TOKENS / FILLER_TOKENS_PER_LINE), "deep")
              + "\n\nIn about 250 words, describe what kinds of entries this log contains.")
    _, rec = client.chat([{"role": "user", "content": prompt}], seed=0, max_tokens=256, thinking=False)
    return [{"id": "deep-100k", **rec}]


def match(value, rule):
    if "eq" in rule:
        if isinstance(rule["eq"], str):
            return isinstance(value, str) and value.strip().lower() == rule["eq"].lower()
        return value == rule["eq"]
    if "icontains" in rule:
        return isinstance(value, str) and rule["icontains"].lower() in value.lower()
    if "startswith" in rule:
        return isinstance(value, str) and value.startswith(rule["startswith"])
    if "in" in rule:
        return isinstance(value, str) and value.strip().lower() in [v.lower() for v in rule["in"]]
    raise ValueError(rule)


def grade_tool_call(message, task):
    calls = (message or {}).get("tool_calls") or []
    expect = task.get("expect")
    if expect is None:
        text = answer_text(message)
        return not calls and bool(text) and all(s.lower() in text.lower() for s in task.get("content_contains", []))
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != expect["name"]:
        return False
    try:
        args = json.loads(calls[0]["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        return False
    return all(match(args.get(k), rule) for k, rule in expect["args"].items())


def tools(client, spec, completions):
    out = []
    for task in spec["tasks"]:
        message, rec = client.chat([{"role": "user", "content": task["prompt"]}], seed=seed_for(task["id"]), tools=spec["tools"])
        completions.append({"key": f"tools/{task['id']}", "message": message})
        ok = message is not None and rec.get("finish_reason") != "length" and grade_tool_call(message, task)
        out.append({"id": task["id"], "pass": ok, **rec})
    return out


def longctx(client):
    rng = random.Random("longctx-needles")
    lines = filler(LONGCTX_TOKENS // 17, "longctx").split("\n")
    needles = []
    for frac, animal in zip((0.1, 0.5, 0.9), rng.sample(["otter", "heron", "lynx", "badger", "falcon", "marmot"], 3)):
        code = str(rng.randint(10000, 99999))
        lines.insert(int(len(lines) * frac), f"Note: the access code for the {animal} enclosure is {code}.")
        needles.append((animal, code, frac))
    doc = "\n".join(lines)
    out = []
    for animal, code, frac in needles:
        prompt = f"{doc}\n\nWhat is the access code for the {animal} enclosure? Answer with the number only."
        message, rec = client.chat([{"role": "user", "content": prompt}], seed=seed_for(animal), max_tokens=64, thinking=False)
        out.append({"id": f"needle-{int(frac * 100)}", "pass": code in answer_text(message), **rec})
    return out


YAML_HELPERS = '''
def find(kind, name=None):
    for d in DOCS:
        if isinstance(d, dict) and d.get("kind") == kind and (name is None or d.get("metadata", {}).get("name") == name):
            return d
    raise AssertionError(f"no {kind} {name or ''}")


def get(d, path, default=None):
    for part in path.split("."):
        if isinstance(d, list):
            d = d[int(part)] if part.isdigit() and int(part) < len(d) else default
        elif isinstance(d, dict):
            d = d.get(part, default)
        else:
            return default
    return d
'''


def yaml_program(task, text):
    doc = extract_block(text, ("yaml", "yml"))
    return f"import yaml\nDOCS = [d for d in yaml.safe_load_all({doc!r}) if d is not None]\n{YAML_HELPERS}\n{task['check']}\n"


def code_program(task, text):
    entry = task["entry_point"]
    code = extract_block(text, ("python", "py", "python3"))
    body = task["prompt"] + ("\n\n" + code if re.search(rf"^\s*def {re.escape(entry)}\s*\(", code, re.M) else code)
    return f"{body}\n\n{task['test']}\n\ncheck({entry})\n"


def sandboxed(client, suite, tasks, prompt_fn, program_fn, programs, completions):
    out = []
    for task in tasks:
        message, rec = client.chat([{"role": "user", "content": prompt_fn(task)}], seed=seed_for(task["id"]))
        completions.append({"key": f"{suite}/{task['id']}", "message": message})
        item = {"id": task["id"], "pass": False, **rec}
        if message is not None and rec.get("finish_reason") == "length":
            item["note"] = "truncated"
        elif message is not None:
            item["pass"] = None
            programs.append({"key": f"{suite}/{task['id']}", "program": program_fn(task, answer_text(message))})
        out.append(item)
    return out


def run_sandbox(programs):
    if not programs:
        return {}
    subprocess.run(["docker", "build", "-q", "-t", SANDBOX_IMAGE, str(ROOT / "sandbox")], check=True, stdout=subprocess.DEVNULL)
    proc = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", "--read-only",
         "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--memory", "1g", "--memory-swap", "1g",
         "--pids-limit", "256", "--cpus", "2", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
         "--user", "65534:65534", SANDBOX_IMAGE, "python", "-I", "/opt/run_programs.py"],
        input="".join(json.dumps(p) + "\n" for p in programs), capture_output=True, text=True, timeout=3600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sandbox exited {proc.returncode}")
    return {r["key"]: r for r in map(json.loads, proc.stdout.splitlines())}


# --- main ------------------------------------------------------------------


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def rounded(x, digits):
    return round(x, digits) if x is not None else None


def summarize(result):
    q = [i for s in ("tools", "longctx", "homelab", "code") for i in result["suites"].get(s, [])]
    graded = [i for i in q if i.get("pass") is not None]
    # deep is reported separately so decode_tps/mtp_accept stay comparable with earlier sessions.
    timed = [i.get("timings", {}) for name, s in result["suites"].items() if name != "deep" for i in s]
    deep_t = (result["suites"].get("deep") or [{}])[0].get("timings", {})
    draft = sum(t.get("draft_n", 0) for t in timed)
    speed_by_depth = {}
    for i in result["suites"].get("speed", []):
        speed_by_depth.setdefault(i["depth"], []).append(i.get("timings", {}))
    rate = lambda s: f"{sum(1 for i in result['suites'].get(s, []) if i.get('pass'))}/{len(result['suites'].get(s, []))}"  # noqa: E731
    return {
        "passed": sum(1 for i in graded if i["pass"]),
        "total": len(q),
        "code_passed": rate("code"),
        "homelab_passed": rate("homelab"),
        "tools_passed": rate("tools"),
        "longctx_passed": rate("longctx"),
        "quality_seconds": round(sum(i.get("wall_s", 0) for i in q), 1),
        "decode_tps": rounded(median(t.get("predicted_per_second") for t in timed if t.get("predicted_n", 0) >= 32), 1),
        "mtp_accept": round(sum(t.get("draft_n_accepted", 0) for t in timed) / draft, 3) if draft else None,
        "ttft_8k_s": rounded(median((t.get("prompt_ms") or 0) / 1000 or None for t in speed_by_depth.get(8000, [])), 2),
        "prefill_tps_24k": rounded(median(t.get("prompt_per_second") for t in speed_by_depth.get(24000, [])), 0),
        "decode_tps_100k": rounded(deep_t.get("predicted_per_second"), 1),
        "prefill_tps_100k": rounded(deep_t.get("prompt_per_second"), 0),
        "min_free_gib": round(result["min_free_bytes"] / 2**30, 2) if result.get("min_free_bytes") else None,
        "status": result["status"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--smoke", action="store_true", help="One item per suite; pipeline check only, never for keep/discard")
    args = parser.parse_args()

    tasks_dir = ROOT / "tasks"
    with gzip.open(tasks_dir / "humaneval" / "tasks.jsonl.gz", "rt") as f:
        code_tasks = [{**json.loads(line), "id": json.loads(line)["task_id"]} for line in f]
    homelab_tasks = json.loads((tasks_dir / "homelab" / "tasks.json").read_text())["tasks"]
    tool_spec = json.loads((tasks_dir / "tools" / "tasks.json").read_text())
    if args.smoke:
        code_tasks, homelab_tasks = code_tasks[:1], homelab_tasks[:1]
        tool_spec = {**tool_spec, "tasks": tool_spec["tasks"][:1]}

    guard = Guard()
    guard.start()
    client = Client(bench.load_key("litellm/evals"), args.model, guard)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    result = {"started": stamp, "model": args.model, "smoke": args.smoke, "suites": {}, "status": "ok"}
    programs, completions = [], []
    started = time.monotonic()
    try:
        # Warm-up after a restart (graph/kernels); not measured.
        client.chat([{"role": "user", "content": "Hi"}], seed=0, max_tokens=8, thinking=False)
        result["suites"]["speed"] = speed(client, args.smoke)
        if not args.smoke:
            result["suites"]["deep"] = deep(client)
        result["suites"]["tools"] = tools(client, tool_spec, completions)
        result["suites"]["longctx"] = longctx(client)[: 1 if args.smoke else None]
        result["suites"]["homelab"] = sandboxed(
            client, "homelab", homelab_tasks,
            lambda t: t["prompt"] + "\n\nReply with only the YAML manifest(s) in a single ```yaml code block.",
            yaml_program, programs, completions)
        result["suites"]["code"] = sandboxed(
            client, "code", code_tasks,
            lambda t: ("Complete the following Python function. Reply with the complete function, including any "
                       "imports it needs, in a single ```python code block.\n\n```python\n" + t["prompt"] + "```"),
            code_program, programs, completions)
    except Abort as exc:
        result["status"] = "crash"
        result["reason"] = str(exc)
    finally:
        guard.halt.set()
    result["min_free_bytes"] = guard.min_free
    graded = run_sandbox(programs)
    for suite in ("homelab", "code"):
        for item in result["suites"].get(suite, []):
            g = graded.get(f"{suite}/{item['id']}")
            if g is not None:
                item["pass"] = g["pass"]
    result["eval_seconds"] = round(time.monotonic() - started)
    result["summary"] = summarize(result)

    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    (runs / f"{stamp}.json").write_text(json.dumps(result, indent=2) + "\n")
    with open(runs / f"{stamp}-completions.jsonl", "w") as f:
        f.writelines(json.dumps(c) + "\n" for c in completions)
    (runs / "latest.json").write_text(json.dumps(result, indent=2) + "\n")

    print("---")
    if args.smoke:
        print("smoke:            true")
    if result.get("reason"):
        print(f"reason:           {result['reason']}")
    for k, v in result["summary"].items():
        print(f"{k + ':':<18}{v if v is not None else 'n/a'}")
    print(f"{'eval_seconds:':<18}{result['eval_seconds']}")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
