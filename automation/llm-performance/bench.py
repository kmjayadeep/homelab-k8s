#!/usr/bin/env python3
"""Run safe streaming performance probes and render a standalone HTML comparison.

No prompt text, response content, authentication value, or error body is saved.
This measures client-observed performance through LiteLLM, not engine prefill or VRAM.
"""

import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import random
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
DEFAULT_ENDPOINT = "https://litellm.cosmos.cboxlab.com/v1"
PROFILE = (("short", 0), ("medium", 260), ("long", 780))
DEFAULT_CANDIDATES = (
    ("qwen3.6-35b-a3b-intel", "No stored run"),
    ("qwen3.8-27b-intel-test", "Stopped trial in Git"),
    ("qwen3.6-27b-intel", "Stopped vLLM trial in Git"),
)


def synthetic_prompt(nlines, trial):
    """Match the original seeded synthetic prompts; only the short one is shared."""
    rng = random.Random(17700 + trial + 3 * nlines)
    lines = [
        f"Entry {i:04d}: synthetic item {rng.randrange(100000000, 999999999)} "
        f"belongs to group {i % 13}; description uses neutral filler words."
        for i in range(nlines)
    ]
    rng.shuffle(lines)
    return (
        "Read these synthetic entries, then produce a numbered list of mundane "
        "household objects. Do not reproduce the entries.\n" + "\n".join(lines)
    )


def load_key(pass_entry):
    # Never place the token in argv, a shell expression, an environment variable,
    # an error message, a result file, or the report. This process holds it only
    # in memory for the outgoing HTTPS Authorization header.
    result = subprocess.run(
        ["pass", "show", pass_entry], capture_output=True, check=True, timeout=15
    )
    key = result.stdout.splitlines()[0].strip().decode("utf-8")
    if not key or "\n" in key or "\r" in key:
        raise ValueError("Invalid pass entry")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward an Authorization header across hosts or downgrade to HTTP.
        return None


SAFE_OPENER = urllib.request.build_opener(NoRedirect())


def probe(endpoint, model, key, name, nlines, trial, max_tokens):
    if not endpoint.startswith("https://"):
        raise ValueError("HTTPS is required")
    data = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": synthetic_prompt(nlines, trial)}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=data,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        start = time.monotonic()
        first = last = None
        chunks = 0
        usage = {}
        finish = None
        try:
            with SAFE_OPENER.open(request, timeout=300) as response:
                for raw in response:
                    if not raw.startswith(b"data: "):
                        continue
                    value = raw[6:].strip()
                    if value == b"[DONE]":
                        break
                    try:
                        event = json.loads(value)
                    except (UnicodeDecodeError, ValueError):
                        continue
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    for choice in event.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content") or delta.get("reasoning_content"):
                            chunks += 1
                            if first is None:
                                first = time.monotonic()
                            last = time.monotonic()
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
            if (first is None or last is None
                    or not isinstance(usage.get("prompt_tokens"), int)
                    or not isinstance(usage.get("completion_tokens"), int)
                    or usage["completion_tokens"] < 2):
                raise ValueError("missing_stream_or_usage")
            output = usage["completion_tokens"]
            decode = last - first
            if decode <= 0:
                raise ValueError("insufficient_stream_timing")
            return {
                "case": name, "trial": trial,
                "prompt_tokens": usage.get("prompt_tokens"),
                "output_tokens": output,
                "ttft_s": round(first - start, 3),
                "decode_s": round(decode, 3),
                "total_s": round(time.monotonic() - start, 3),
                "decode_tps": round((output - 1) / decode, 2) if decode > 0 and output > 1 else None,
                "finish_reason": finish, "chunks": chunks,
            }
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return {"case": name, "trial": trial, "error": "http_" + str(exc.code)}
        except (OSError, ValueError, TimeoutError) as exc:
            # Exception messages can contain server data; never retain or print them.
            return {"case": name, "trial": trial, "error": type(exc).__name__}
    raise AssertionError("unreachable")


def summarize(samples, name):
    rows = [r for r in samples if r["case"] == name and "error" not in r]
    if not rows:
        return None
    return {
        "completed": len(rows),
        "prompt_min": min(r["prompt_tokens"] for r in rows),
        "prompt_max": max(r["prompt_tokens"] for r in rows),
        "ttft_s": statistics.median(r["ttft_s"] for r in rows),
        "decode_tps": statistics.median(r["decode_tps"] for r in rows),
        "total_s": statistics.median(r["total_s"] for r in rows),
    }


def run(args):
    if not args.endpoint.startswith("https://"):
        raise ValueError("HTTPS is required for token-bearing requests")
    if not re.fullmatch(r"[\w.:-]+", args.model):
        raise ValueError("Model ID contains unsupported characters")
    key = load_key(args.pass_entry)
    samples = []
    for name, nlines in PROFILE:
        for trial in range(1, args.trials + 1):
            sample = probe(args.endpoint, args.model, key, name, nlines, trial, args.max_tokens)
            samples.append(sample)
            # Only numerical metadata and error classes; never print responses.
            print(json.dumps(sample, sort_keys=True), flush=True)
    result = {
        "schema": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model, "endpoint": args.endpoint,
        "configuration": args.configuration or "Operator supplied; verify live artifact separately",
        "settings": {"temperature": 0, "max_tokens": args.max_tokens,
                     "trials_per_depth": args.trials, "concurrency": 1,
                     "profile_lines": dict(PROFILE)},
        "samples": samples,
    }
    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = args.results_dir / f"{stamp}-{args.model}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("Results (review before staging):", path)


def metrics_table(rows):
    lines = []
    for r in rows:
        if "error" in r:
            values = [r["case"], r["trial"], "—", "—", "—", "—", "—", r["error"]]
        else:
            values = [r["case"], r["trial"], r["prompt_tokens"],
                      f'{r["ttft_s"]:.3f}', f'{r["decode_tps"]:.2f}',
                      f'{r["total_s"]:.3f}', r["output_tokens"], r["finish_reason"]]
        lines.append("<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in values) + "</tr>")
    return "\n".join(lines)


def render(results):
    # Order names for stable comparisons; new models are discovered from the run files.
    names = list(dict(DEFAULT_CANDIDATES))
    names.extend(sorted(set(r["model"] for r in results) - set(names)))
    latest = {model: max((r for r in results if r["model"] == model),
                         key=lambda r: r["created_utc"], default=None) for model in names}
    statuses = dict(DEFAULT_CANDIDATES)
    overview = []
    details = []
    reference = next((r for r in results if r["model"] == "qwen3.6-35b-a3b-intel"),
                     results[0] if results else None)
    for index, model in enumerate(names):
        run_result = latest[model]
        link = f'model-{index}'
        cells = [f'<td><a href="#{link}">{escape(model)}</a></td>']
        if run_result is None:
            cells += [f'<td>{escape(statuses.get(model, "Not tested"))}</td>']
            cells += ["<td>Not tested</td>"] * 4
            details.append(f'<section id="{link}"><h2>{escape(model)}</h2><p>Not tested in this suite. '
                           'A stopped backend must not be started on the sole GPU without explicit approval '
                           'and a rollback plan.</p></section>')
        else:
            rows = run_result["samples"]
            passed = sum("error" not in r for r in rows)
            cells.append(f'<td>{passed}/{len(rows)} completed</td>')
            for case, _ in PROFILE:
                stats = summarize(rows, case)
                if stats:
                    prompt = str(stats["prompt_min"]) if stats["prompt_min"] == stats["prompt_max"] else f'{stats["prompt_min"]}–{stats["prompt_max"]}'
                    cells.append(f'<td>{escape(prompt)} tokens: {stats["ttft_s"]:.2f} s TTFT / {stats["decode_tps"]:.2f} tok/s decode / {stats["total_s"]:.2f} s total ({stats["completed"]} runs)</td>')
                else:
                    cells.append("<td>Not measured</td>")
            configuration = escape(str(run_result.get("configuration", "Unknown")))
            info = escape(str(run_result["created_utc"]))
            comparable = (run_result.get("settings") == reference.get("settings")
                          and run_result.get("endpoint") == reference.get("endpoint"))
            if not comparable:
                cells.append("<td>Different settings/endpoint; do not compare directly</td>")
            else:
                cells.append("<td>Same profile settings</td>")
            details.append(f'''<section id="{link}"><h2>{escape(model)}</h2><p>Run: {info}. Configuration noted at collection: {configuration}
Git metadata and endpoint naming do not independently verify live artifact or runtime flags.</p>
<div class="scroll"><table><thead><tr><th>Case</th><th>Trial</th><th>Prompt tokens</th><th>TTFT (s)</th><th>Decode tok/s</th><th>Total (s)</th><th>Output tokens</th><th>Finish / error class</th></tr></thead><tbody>
{metrics_table(rows)}</tbody></table></div></section>''')
        overview.append("<tr>" + "".join(cells) + "</tr>")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Homelab LLM performance comparison</title>
<style>:root{{color-scheme:dark;font-family:system-ui;background:#121821;color:#eaf0f7}}body{{max-width:1200px;margin:2rem auto;padding:0 1rem;line-height:1.55}}a{{color:#9dd2ff}}table{{width:100%;border-collapse:collapse;margin:1rem 0 1.5rem}}th,td{{border:1px solid #45556a;padding:.6rem;text-align:left;vertical-align:top}}th{{background:#243246}}tbody tr:nth-child(even){{background:#1b2633}}.scroll{{overflow-x:auto}}section{{margin-top:2rem}}.note{{background:#243246;padding:1rem;border-radius:6px}}</style></head>
<body><h1>Homelab LLM performance comparison</h1><p>Performance only. Each measured cell shows actual reported prompt tokens, median client-observed TTFT, median streamed decode rate and median end-to-end duration. Only the latest stored run per model is shown. Unavailable candidates are <strong>not tested</strong>, not zero.</p>
<div class="scroll"><table><thead><tr><th>Model</th><th>Completed</th><th>Short</th><th>Medium</th><th>Long</th><th>Profile settings</th></tr></thead><tbody>{''.join(overview)}</tbody></table></div>
<p class="note">Method: sequential HTTPS LiteLLM chat requests, synthetic shuffled prompts at 0, 260 and 780 lines, temperature 0, 256-token output limit and three repetitions by default. TTFT is request start to first streamed content/reasoning delta. Decode tok/s = (reported completion tokens − 1) / first-to-last streamed-output duration. Completion tokens may include reasoning; finish_reason=length does not imply a finished user-facing answer. Client timings include network, queueing and prompt processing; this does not isolate engine prefill, VRAM, host pressure or 128K safety. The identical short prompt may benefit from caching. Compare runs only when settings match.</p>
{''.join(details)}<footer><small>Self-contained HTML generated from numeric-only JSON. No secrets, prompts, or completions are stored here. Running this script never scales/reconciles GPU workloads.</small></footer></body></html>'''


def report(args):
    results = []
    for path in sorted(args.results_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("samples"), list):
            raise ValueError("Unsupported results schema: " + path.name)
        results.append(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(results) + "\n", encoding="utf-8")
    print("Standalone HTML:", args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("run", help="Run a fixed, benign synthetic streaming profile")
    runner.add_argument("--model", required=True, help="Exact LiteLLM model name, not a mutable alias")
    runner.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    runner.add_argument("--pass-entry", default="litellm/evals")
    runner.add_argument("--configuration", help="Human-verified artifact/settings note (not a live-state claim)")
    runner.add_argument("--trials", type=int, default=3)
    runner.add_argument("--max-tokens", type=int, default=256)
    runner.add_argument("--results-dir", type=Path, default=ROOT / "results")
    reporter = sub.add_parser("report", help="Render latest run per model as one standalone HTML file")
    reporter.add_argument("--results-dir", type=Path, default=ROOT / "results")
    reporter.add_argument("--output", type=Path, default=ROOT / "report.html")
    args = parser.parse_args()
    if args.command == "run":
        if not (1 <= args.trials <= 10 and 2 <= args.max_tokens <= 16384):
            parser.error("trials must be 1–10 and max-tokens 2–16384")
        run(args)
    else:
        report(args)


if __name__ == "__main__":
    main()
