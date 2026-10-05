# Reusable LiteLLM performance profile

See [plan 0007](../../plans/0007-local-llm-performance-comparison.md) for evidence, limits, and approvals. This is **client-observed performance**, not a quality evaluation or GPU stress test. No cluster mutations or live-model switches are performed.

## Run an already available model

Requirements: Python 3.10+, `pass` with `litellm/evals`, HTTPS access to LiteLLM. From the repo root:

```bash
python3 automation/llm-performance/bench.py run \
  --model qwen3.8-27b-autoround-intel \
  --configuration 'Verified model/revision and runtime flags, if independently checked'
python3 automation/llm-performance/bench.py report
```

Use the **versioned model ID**, not the `qwen-intel` alias. The Intel Qwen3.8 AutoRound Q4_K_M trial is declared running in Git, and earlier Intel predictors are stopped; verify live readiness before re-running. Git maps the stable `qwen-intel` alias to the Qwen3.8 entry, but use the versioned ID for reproducible comparisons and verify effective database-backed routing. The `--configuration` value must be a non-secret note, never a token or a claim of live verification based only on Git. An HTTPS endpoint is mandatory. The token is taken in-process from the first line of `pass show litellm/evals`; it is not passed through a shell, command argument, log, environment variable, result JSON, or HTML. Never use `set -x`, print environment variables, or run through an HTTP redirect. If auth fails, inspect only status/error classes, not secret-bearing response bodies.

The runner saves each run as a new, non-overwriting numeric-only JSON file in `results/` and prints only metrics/error categories; review before staging. The report command regenerates **one standalone** `report.html` from stored runs, picking the newest run per model. Retain prior runs for comparison/audit; do not treat a stopped model as zero. Both files should be reviewed before committing. No run is committed automatically.

The default profile makes three sequential streaming calls each with 0, 260, and 780 lines of seeded, shuffled synthetic entries (historically 31, 8,411, and 25,171 actual reported prompt tokens for the Qwen3.6 test), temperature 0, max 256 output tokens and `stream_options.include_usage`. Record actual usage because tokenizer output may differ among models. The short prompt is identical across runs; it may benefit from warm cache. First-to-last streamed time excludes TTFT; reported output tokens can include reasoning. A `finish_reason=length` is acceptable for **throughput only**, not an answer-quality success. Streaming success, errors, and finish reason are retained separately. No prompt or completion text is persisted.

For a different model, first obtain explicit approval for any single-B60 GPU-owner change and endpoint interruption; verify artifact, readiness and the exact LiteLLM model ID. Do not point this script at a stopped backend. Run the same profile and report command, then compare only compatible settings. The script will never scale or reconcile a workload. No VRAM/host-RAM, pressure, or server-side prefill data is collected. Do not extrapolate these 25K requests to 128K.

Local validation (does not call the endpoint):

```bash
python3 -m unittest discover -s automation/llm-performance/tests -v
python3 automation/llm-performance/bench.py report
# Inspect the resulting report.html and git diff before committing.
```
