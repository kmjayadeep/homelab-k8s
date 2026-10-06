import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "bench.py"
spec = importlib.util.spec_from_file_location("llm_performance_bench", MODULE_PATH)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class FakeResponse:
    def __init__(self):
        self.lines = [
            b'data: {"choices":[{"delta":{"content":"TEST OUTPUT"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"MORE OUTPUT"},"finish_reason":"length"}]}\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":31,"completion_tokens":2}}\n',
            b'data: [DONE]\n',
        ]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter(self.lines)


class BenchmarkTests(unittest.TestCase):
    def test_prompt_is_reproducible_and_size_changes(self):
        self.assertEqual(bench.synthetic_prompt(260, 1), bench.synthetic_prompt(260, 1))
        self.assertNotEqual(bench.synthetic_prompt(260, 1), bench.synthetic_prompt(260, 2))
        self.assertEqual(bench.synthetic_prompt(0, 1), bench.synthetic_prompt(0, 2))
        self.assertEqual(len(bench.synthetic_prompt(780, 1).splitlines()), 781)

    def test_stream_extracts_only_metrics_and_requires_https(self):
        with patch.object(bench.SAFE_OPENER, "open", return_value=FakeResponse()) as opening:
            with patch.object(bench.time, "monotonic", side_effect=[1.0, 2.0, 4.0, 4.5, 4.5]):
                result = bench.probe("https://example.test/v1", "candidate", "FAKE-KEY", "short", 0, 1, 256)
        self.assertEqual(result["prompt_tokens"], 31)
        self.assertEqual(result["decode_tps"], 0.4)
        self.assertEqual(result["finish_reason"], "length")
        self.assertNotIn("FAKE-KEY", json.dumps(result))
        self.assertNotIn("TEST OUTPUT", json.dumps(result))
        self.assertTrue(opening.call_args.args[0].get_full_url().startswith("https://"))
        with self.assertRaises(ValueError):
            bench.probe("http://example.test/v1", "candidate", "FAKE-KEY", "short", 0, 1, 256)

    def test_redirect_is_blocked(self):
        self.assertIsNone(bench.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://other"))

    def test_committed_baseline_renders_and_escapes(self):
        path = MODULE_PATH.parent / "results" / "20261004-qwen3.6-35b-a3b-intel.json"
        baseline = json.loads(path.read_text())
        stats = bench.summarize(baseline["samples"], "long")
        self.assertEqual(stats["completed"], 3)
        self.assertEqual(stats["prompt_min"], 25171)
        self.assertEqual(stats["decode_tps"], 43.67)
        baseline["configuration"] = "<script>unsafe</script>"
        html = bench.render([baseline])
        self.assertIn("43.67 tok/s", html)
        self.assertIn("Not tested", html)
        self.assertNotIn("<script>", html)

    def test_report_preserves_multiple_configurations_for_same_model(self):
        path = MODULE_PATH.parent / "results" / "20261005T192618268181Z-qwen3.8-27b-autoround-intel.json"
        older = json.loads(path.read_text())
        newer = json.loads(path.read_text())
        newer["created_utc"] = "2026-10-06T00:00:00+00:00"
        newer["configuration"] = "80K q8_0 K/V <new>"
        html = bench.render([older, newer])
        self.assertIn("32K q4_0 KV", html)
        self.assertIn("80K q8_0 K/V &lt;new&gt;", html)
        self.assertIn('id="model-3-run-0"', html)
        self.assertIn('id="model-3-run-1"', html)
        self.assertEqual(html.count("9/9 completed"), 2)

    def test_report_from_results_is_single_html_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = json.loads((MODULE_PATH.parent / "results" / "20261004-qwen3.6-35b-a3b-intel.json").read_text())
            (root / "run.json").write_text(json.dumps(baseline))
            class Args:
                results_dir = root
                output = root / "report.html"
            bench.report(Args())
            self.assertEqual(list(root.glob("*.html")), [Args.output])
            self.assertIn("48.94 tok/s", Args.output.read_text())


if __name__ == "__main__":
    unittest.main()
