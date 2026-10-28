#!/usr/bin/env python3
"""Session tooling for the B60 autoresearch loop (see program.md).

  start    preflight, suspend Flux for llm-serving-intel-llama (with marker)
  apply    validate the manifest edit, apply it, wait for rollout + LiteLLM
  run      apply, then evaluate.py (redirect to run.log)
  record   append the latest run to results.tsv
  verdict  print KEEP / DISCARD / CRASH for the latest run
  archive  move the session's results into results/<tag>/ (tracked) for the PR
  finish   resume Flux (production returns to the Git main config)
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
import evaluate  # noqa: E402

NS = "llm-serving"
KS = "llm-serving-intel-llama"
DEPLOY = "intel-llama-ornith"
CONTAINER = "llama-server"
APP_DIR = REPO / "clusters/titania/apps/llm-serving-intel-llama"
MANIFEST = "clusters/titania/apps/llm-serving-intel-llama/deployment-ornith.yaml"
MARKER = "llm-autoresearch.cboxlab.com/suspended-by"
RESULTS = ROOT / "results.tsv"
RUNS = ROOT / "runs"
ARCHIVE = ROOT / "results"
COLUMNS = ["commit", "passed", "total", "quality_seconds", "decode_tps", "ttft_8k_s",
           "prefill_tps_24k", "mtp_accept", "decode_tps_100k", "prefill_tps_100k", "min_free_gib",
           "status", "description"]

# Never changed by the loop: identity/routing, and anything that would shrink the
# usable context production relies on (the eval only probes ~24K).
PROTECTED = {"--model", "--mmproj", "--alias", "--host", "--port", "--metrics", "--jinja",
             "--ctx-size", "--parallel", "--n-gpu-layers"}
MAX_CHANGED_FLAGS = 2  # one idea; allows coupled pairs such as cache-type-k/v

# Flags that should change speed but not answers. Scores still move by about +-2 tasks
# between runs of such configs (oct14), so these are judged on time, with quality
# only as a guard against the session baseline.
SPEED_ONLY = {"--batch-size", "--ubatch-size", "--threads", "--threads-batch", "--flash-attn",
              "--poll", "--cache-reuse"}
SPEED_ONLY_PREFIXES = ("--spec-",)
NOISE = 2           # tasks; observed run-to-run spread on answer-neutral changes
QUALITY_GAIN = 3    # tasks over the reference for a quality keep (> NOISE)
REFERENCE_RUNS = 3  # reference quality = mean passed of the last N keeps, smoothing single-run noise
SPEED_GAIN = 0.05   # fraction of quality_seconds saved for a speed keep
DEEP_GAIN = 0.08    # decode_tps_100k gain for a deep-decode keep (a rate, so less noisy than wall time)
DEEP_LOSS = 0.10    # decode_tps_100k loss that vetoes any keep


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(*args, stdin=None, timeout=300):
    proc = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} {args[1] if len(args) > 1 else ''} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def kget(kind, name):
    return json.loads(sh("kubectl", "-n", NS, "get", kind, name, "-o", "json"))


def kustomization():
    return kget("kustomizations.kustomize.toolkit.fluxcd.io", KS)


def patch_kustomization(patch):
    sh("kubectl", "-n", NS, "patch", "kustomizations.kustomize.toolkit.fluxcd.io", KS, "--type=merge",
       "--field-manager=flux-client-side-apply", "-p", json.dumps(patch))


def manifest_args(revision):
    """Return llama-server args of the Deployment at a git revision ('WORKTREE' for the file on disk)."""
    text = (REPO / MANIFEST).read_text() if revision == "WORKTREE" else sh("git", "-C", str(REPO), "show", f"{revision}:{MANIFEST}")
    doc = json.loads(sh("kubectl", "create", "--dry-run=client", "-o", "json", "-f", "-", stdin=text))
    container = next(c for c in doc["spec"]["template"]["spec"]["containers"] if c["name"] == CONTAINER)
    return doc, container.get("args", [])


def flags(args):
    out, i = {}, 0
    while i < len(args):
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            out[args[i]] = args[i + 1]
            i += 2
        else:
            out[args[i]] = None
            i += 1
    return out


def validate():
    """The edit must touch only llama-server args, never protected flags, one idea at a time."""
    main_doc, main_args = manifest_args("main")
    head_doc, head_args = manifest_args("WORKTREE")
    for doc in (main_doc, head_doc):
        next(c for c in doc["spec"]["template"]["spec"]["containers"] if c["name"] == CONTAINER)["args"] = []
    if main_doc != head_doc:
        raise SystemExit("REJECTED: only llama-server args may change in the Deployment manifest")
    base, new = flags(main_args), flags(head_args)
    for flag in PROTECTED:
        if base.get(flag, "<absent>") != new.get(flag, "<absent>"):
            raise SystemExit(f"REJECTED: {flag} is protected")
    if sh("git", "-C", str(REPO), "status", "--porcelain", "--", MANIFEST).strip():
        raise SystemExit("REJECTED: commit the experiment before running it")
    # HEAD is the experiment commit; its parent is the last kept config (or main).
    _, kept_args = manifest_args("HEAD~1") if _has_parent_experiment() else (None, head_args)
    kept = flags(kept_args)
    changed = sorted(k for k in set(kept) | set(new) if kept.get(k, "<absent>") != new.get(k, "<absent>"))
    if len(changed) > MAX_CHANGED_FLAGS:
        raise SystemExit(f"REJECTED: {len(changed)} flags changed ({', '.join(changed)}); change one idea at a time")
    return changed


def _has_parent_experiment():
    branch = sh("git", "-C", str(REPO), "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not branch.startswith("autoresearch/"):
        raise SystemExit("REJECTED: run on an autoresearch/<tag> branch")
    ahead = int(sh("git", "-C", str(REPO), "rev-list", "--count", "main..HEAD").strip())
    return ahead >= 1


def require_suspended():
    ks = kustomization()
    if not ks["spec"].get("suspend") or MARKER not in ks["metadata"].get("annotations", {}):
        raise SystemExit("REJECTED: Flux is not suspended by this loop; run `experiment.py start` first")


def pod_problem(selector, since):
    pods = json.loads(sh("kubectl", "-n", NS, "get", "pods", "-l", selector, "-o", "json"))["items"]
    for pod in pods:
        if pod["metadata"]["creationTimestamp"] < since:
            continue
        for cs in pod["status"].get("containerStatuses", []) + pod["status"].get("initContainerStatuses", []):
            term = cs.get("lastState", {}).get("terminated") or cs.get("state", {}).get("terminated")
            if term and term.get("reason") not in (None, "Completed"):
                return f"{cs['name']} terminated: {term.get('reason')} (exit {term.get('exitCode')})"
            if cs.get("restartCount", 0) > 0:
                return f"{cs['name']} restarted"
        if pod["status"].get("reason") == "Evicted":
            return "pod evicted"
    return None


def apply(skip_validate=False):
    require_suspended()
    changed = [] if skip_validate else validate()
    if changed:
        log(f"changed vs kept config: {', '.join(changed)}")
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    rendered = sh("kustomize", "build", str(APP_DIR))
    sh("kubectl", "apply", "--server-side", "--field-manager=llm-autoresearch", "--force-conflicts", "-f", "-", stdin=rendered)
    deploy = kget("deployment", DEPLOY)
    selector = ",".join(f"{k}={v}" for k, v in sorted(deploy["spec"]["selector"]["matchLabels"].items()))
    log("applied; waiting for rollout (Recreate + checksum init takes a few minutes)")
    started, min_free = time.monotonic(), None
    while True:
        if time.monotonic() - started > 1500:
            return fail("rollout did not become available within 25 minutes")
        try:
            free = evaluate.free_memory_bytes()
        except Exception:  # noqa: BLE001
            free = None
        if free is not None:
            min_free = free if min_free is None else min(min_free, free)
            if free < evaluate.MIN_FREE_BYTES:
                return fail(f"titania-gpu free memory {free / 2**30:.2f} GiB during startup")
        problem = pod_problem(selector, since)
        if problem:
            return fail(problem)
        d = kget("deployment", DEPLOY)
        st = d.get("status", {})
        if (st.get("observedGeneration", 0) >= d["metadata"]["generation"] and st.get("updatedReplicas") == 1
                and st.get("availableReplicas") == 1 and not st.get("unavailableReplicas")):
            break
        time.sleep(10)
    client = evaluate.Client(evaluate.bench.load_key("litellm/evals"), evaluate.MODEL, evaluate.Guard())
    for _ in range(30):
        try:
            message, rec = client.chat([{"role": "user", "content": "Reply with OK."}], seed=0, max_tokens=8, thinking=False)
            if message is not None:
                break
        except evaluate.Abort:
            pass
        time.sleep(10)
    else:
        return fail("LiteLLM route not answering after rollout")
    log(f"serving via LiteLLM after {time.monotonic() - started:.0f}s (min free {min_free / 2**30 if min_free else 0:.1f} GiB)")
    return 0


def fail(reason):
    log(f"CRASH: {reason}")
    print("---\nstatus:           crash\nreason:           " + reason)
    evaluate_runs = ROOT / "runs"
    evaluate_runs.mkdir(exist_ok=True)
    (evaluate_runs / "latest.json").write_text(json.dumps({"status": "crash", "reason": reason, "summary": {"status": "crash"}}) + "\n")
    return 2


def start():
    _has_parent_experiment()  # enforces the autoresearch/<tag> branch
    if sh("git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("REJECTED: working tree has uncommitted tracked changes")
    ks = kustomization()
    if ks["spec"].get("suspend") and MARKER not in ks["metadata"].get("annotations", {}):
        raise SystemExit("REJECTED: Flux is suspended by someone else; not taking over")
    deploy = kget("deployment", DEPLOY)
    if deploy.get("status", {}).get("availableReplicas", 0) < 1:
        raise SystemExit("REJECTED: production Deployment is not available")
    if read_rows():
        raise SystemExit("REJECTED: results.tsv holds an unarchived session; run `experiment.py archive --tag <old tag>` first")
    free = evaluate.free_memory_bytes()
    if free is None or free < 2 * evaluate.MIN_FREE_BYTES:
        raise SystemExit("REJECTED: titania-gpu has less than 4 GiB free")
    branch = sh("git", "-C", str(REPO), "rev-parse", "--abbrev-ref", "HEAD").strip()
    patch_kustomization({"metadata": {"annotations": {MARKER: branch}}, "spec": {"suspend": True}})
    if not RESULTS.exists():
        RESULTS.write_text("\t".join(COLUMNS) + "\n")
    log(f"Flux suspended for {KS} by {branch}; results in {RESULTS.relative_to(REPO)}")


def archive(tag=None):
    """Move the working session files into results/<tag>/ so they can be committed.

    results.tsv stays untracked during the loop because discards run `git reset --hard`.
    Non-smoke run summaries are kept with it; completions and smoke runs go to the
    git-ignored runs/archive/<tag>/.
    """
    if not tag:
        branch = sh("git", "-C", str(REPO), "rev-parse", "--abbrev-ref", "HEAD").strip()
        if not branch.startswith("autoresearch/"):
            raise SystemExit("REJECTED: pass --tag or run on an autoresearch/<tag> branch")
        tag = branch.removeprefix("autoresearch/")
    if not read_rows():
        raise SystemExit("REJECTED: results.tsv has no rows to archive")
    dest = ARCHIVE / tag
    if dest.exists():
        raise SystemExit(f"REJECTED: {dest.relative_to(REPO)} already exists")
    local = RUNS / "archive" / tag
    (dest / "runs").mkdir(parents=True)
    local.mkdir(parents=True, exist_ok=True)
    RESULTS.rename(dest / "results.tsv")
    kept = 0
    for f in sorted(RUNS.glob("*.json*")):
        if f.name == "latest.json":
            continue
        if f.suffix == ".json" and not json.loads(f.read_text()).get("smoke"):
            f.rename(dest / "runs" / f.name)
            kept += 1
        else:
            f.rename(local / f.name)
    log(f"archived {tag}: results.tsv and {kept} run summaries in {dest.relative_to(REPO)}; "
        f"completions in {local.relative_to(REPO)} (untracked)")


def finish():
    ks = kustomization()
    if MARKER not in ks["metadata"].get("annotations", {}):
        log("Flux was not suspended by this loop; nothing to resume")
        return
    patch_kustomization({
        "metadata": {"annotations": {MARKER: None, "reconcile.fluxcd.io/requestedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}},
        "spec": {"suspend": False},
    })
    log("Flux resumed; waiting for the Deployment to roll back to the Git main config...")
    _, main_args = manifest_args("main")
    for _ in range(120):
        d = kget("deployment", DEPLOY)
        st = d.get("status", {})
        live_args = next(c for c in d["spec"]["template"]["spec"]["containers"] if c["name"] == CONTAINER).get("args", [])
        # The old pod stays available until Flux reapplies, so also require main's args and a finished rollout.
        if (live_args == main_args and st.get("observedGeneration", 0) >= d["metadata"]["generation"]
                and st.get("updatedReplicas") == 1 and st.get("availableReplicas") == 1 and not st.get("unavailableReplicas")):
            log("production available on the main config")
            return
        time.sleep(10)
    raise SystemExit("production not back on the main config 20 minutes after resume; check `flux get ks -n llm-serving`")


def read_rows():
    if not RESULTS.exists():
        return []
    lines = RESULTS.read_text().splitlines()
    return [dict(zip(COLUMNS, line.split("\t"))) for line in lines[1:] if line.strip()]


def record(status, description):
    latest = json.loads((ROOT / "runs" / "latest.json").read_text())
    if latest.get("smoke"):
        raise SystemExit("REJECTED: smoke runs are not recorded")
    s = latest.get("summary", {})
    commit = sh("git", "-C", str(REPO), "rev-parse", "--short=7", "HEAD").strip()
    row = [commit] + [str(s.get(c)) if s.get(c) is not None else "0" for c in COLUMNS[1:-2]] + [status, description.replace("\t", " ")]
    if not RESULTS.exists():
        RESULTS.write_text("\t".join(COLUMNS) + "\n")
    with open(RESULTS, "a") as f:
        f.write("\t".join(row) + "\n")
    log(f"recorded {commit} {status}")


def speed_only(changed):
    return bool(changed) and all(f in SPEED_ONLY or f.startswith(SPEED_ONLY_PREFIXES) for f in changed)


def decide(s, keeps, changed):
    """Keep rule (see program.md). keeps are the session's keep rows, baseline first."""
    p, basep = s["passed"], int(keeps[0]["passed"])
    recent = [int(r["passed"]) for r in keeps[-REFERENCE_RUNS:]]
    ref = sum(recent) / len(recent)
    qs, bqs = s["quality_seconds"], float(keeps[-1]["quality_seconds"])
    status = f"quality {p} (reference {ref:.1f}, baseline {basep}), time {qs:.0f}s vs kept {bqs:.0f}s ({qs / bqs - 1:+.0%})"
    if (s.get("min_free_gib") or 0) < 3:
        return "DISCARD", f"only {s.get('min_free_gib')} GiB free on titania-gpu (need >= 3 GiB headroom)"
    faster = qs <= (1 - SPEED_GAIN) * bqs
    deep, bdeep = float(s.get("decode_tps_100k") or 0), float(keeps[-1].get("decode_tps_100k") or 0)
    if deep and bdeep:
        status += f", decode@100k {deep:.1f} vs {bdeep:.1f} tok/s"
        if deep < (1 - DEEP_LOSS) * bdeep:
            return "DISCARD", f"{status}; decode at 100K dropped more than {DEEP_LOSS:.0%}"
    deep_faster = bool(deep and bdeep and deep >= (1 + DEEP_GAIN) * bdeep and qs <= 1.10 * bqs)
    if speed_only(changed):
        if (faster or deep_faster) and p >= ref - NOISE and p >= basep - NOISE:
            return "KEEP", f"speed-only ({', '.join(changed)}): {status}"
        return "DISCARD", (f"speed-only ({', '.join(changed)}): {status}; needs >={SPEED_GAIN:.0%} faster "
                           f"with quality >= reference-{NOISE} and baseline-{NOISE}")
    if p >= ref + QUALITY_GAIN and qs <= 1.15 * bqs:
        return "KEEP", f"better: {status}"
    if (faster or deep_faster) and p >= ref - 1 and p >= basep - 1:
        return "KEEP", f"faster: {status}"
    return "DISCARD", (f"{status}; needs reference+{QUALITY_GAIN} within +15% time, "
                       f"or >={SPEED_GAIN:.0%} faster within -1 of reference and baseline")


def verdict():
    latest = json.loads((ROOT / "runs" / "latest.json").read_text())
    s = latest.get("summary", {})
    rows = [r for r in read_rows() if r["status"] == "keep"]
    if latest.get("status") != "ok" or s.get("status") != "ok":
        print(f"CRASH: {latest.get('reason', 'run failed')}")
        return
    if not rows:
        print("KEEP: first run is the baseline")
        return
    # HEAD is the experiment commit; HEAD~1 is the last kept config.
    kept, new = flags(manifest_args("HEAD~1")[1]), flags(manifest_args("HEAD")[1])
    changed = sorted(k for k in set(kept) | set(new) if kept.get(k, "<absent>") != new.get(k, "<absent>"))
    result, reason = decide(s, rows, changed)
    print(f"{result}: {reason}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start")
    a = sub.add_parser("apply")
    a.add_argument("--restore", action="store_true", help="Re-apply the kept config after a reset (skips edit checks)")
    sub.add_parser("run")
    r = sub.add_parser("record")
    r.add_argument("status", choices=["keep", "discard", "crash"])
    r.add_argument("description")
    sub.add_parser("verdict")
    ar = sub.add_parser("archive")
    ar.add_argument("--tag", help="Session tag (defaults to the autoresearch/<tag> branch)")
    sub.add_parser("finish")
    args = parser.parse_args()
    if args.cmd == "start":
        start()
    elif args.cmd == "apply":
        return apply(skip_validate=args.restore)
    elif args.cmd == "run":
        code = apply()
        if code:
            return code
        return subprocess.run([sys.executable, str(ROOT / "evaluate.py")]).returncode
    elif args.cmd == "record":
        record(args.status, args.description)
    elif args.cmd == "verdict":
        verdict()
    elif args.cmd == "archive":
        archive(args.tag)
    elif args.cmd == "finish":
        finish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
