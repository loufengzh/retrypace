import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from retrypace.cli import MAX_CONFIG_BYTES, _load_config

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "retrypace", *args],
                              cwd=ROOT, text=True, capture_output=True)

    def test_default_json(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertIn("events", report)

    def test_examples_and_comparison(self):
        for path in (ROOT / "examples").glob("*.json"):
            result = self.run_cli("--config", str(path), "--compare")
            self.assertEqual(result.returncode, 0, result.stderr)
            reports = json.loads(result.stdout)
            self.assertEqual(len(reports), 5)
            self.assertTrue(all("events" not in r for r in reports.values()))

    def test_csv(self):
        result = self.run_cli("--config", "examples/burst.json", "--format", "csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        self.assertEqual(set(rows[0]), {"client", "attempt", "start_ms", "end_ms"})
        report = json.loads(self.run_cli("--config", "examples/burst.json").stdout)
        self.assertEqual(len(rows), report["summary"]["attempts"])

    def test_gates_output_and_exit(self):
        passed = self.run_cli("--max-peak-concurrency", "100", "--max-window-starts", "100000")
        self.assertEqual(passed.returncode, 0, passed.stderr)
        failed = self.run_cli("--max-peak-concurrency", "1", "--summary-only")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("exceeds 1", failed.stderr)
        self.assertNotIn("events", json.loads(failed.stdout))
        failed = self.run_cli("--compare", "--max-window-starts", "1")
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(len(json.loads(failed.stdout)), 5)
        self.assertEqual(failed.stderr.count("exceeds 1"), 5)

    def test_strategy_override(self):
        result = self.run_cli("--config", "examples/burst.json", "--strategy", "fixed")
        self.assertEqual(json.loads(result.stdout)["config"]["strategy"], "fixed")

    def test_invalid_file_and_values(self):
        result = self.run_cli("--config", "does-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for text in ('{"clients": 0}', '[]', '{broken', '{"clients": true}'):
                path.write_text(text, encoding="utf-8")
                result = self.run_cli("--config", str(path))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)

    def test_invalid_argument_combinations(self):
        for args in (("--compare", "--strategy", "fixed"),
                     ("--format", "csv", "--summary-only"),
                     ("--format", "csv", "--compare"),
                     ("--max-peak-concurrency", "-1")):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertIn("error", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_duplicate_config_keys_rejected_before_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for text in ('{"clients": 100, "clients": 1, "max_attempts": 1}',
                         '{"clients": 1, "clients": 1}',
                         r'{"cl\u0069ents": 100, "clients": 1}',
                         '{"strategy": "fixed", "strategy": "full-jitter"}',
                         '{"clients": {"nested": 1, "nested": 2}}'):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    # Neither an explicit strategy nor a passing gate may hide
                    # an ambiguous input policy, and no partial report is emitted.
                    result = self.run_cli("--config", str(path), "--strategy", "fixed",
                                          "--max-peak-concurrency", "1", "--summary-only")
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("duplicate JSON configuration key", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_nonstandard_json_constants_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for constant in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(constant=constant):
                    path.write_text('{"clients": ' + constant + '}', encoding="utf-8")
                    result = self.run_cli("--config", str(path))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("nonstandard JSON numeric constant", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_deeply_nested_config_rejected_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text('[' * 20000 + ']' * 20000, encoding="utf-8")
            result = self.run_cli("--config", str(path))
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("retrypace:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_config_byte_limit_includes_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_bytes(b'{}' + b' ' * (MAX_CONFIG_BYTES - 2))
            result = self.run_cli("--config", str(path), "--summary-only")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["config"]["clients"], 100)
            for raw in (path.read_bytes() + b' ', b'{"unknown":"' + '中'.encode('utf-8') * (MAX_CONFIG_BYTES // 3) + b'"}'):
                path.write_bytes(raw)
                result = self.run_cli("--config", str(path))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("configuration exceeds 64 KiB", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_config_read_is_bounded(self):
        stream = mock.MagicMock()
        stream.__enter__.return_value = stream
        stream.read.return_value = b'{}'
        with mock.patch("builtins.open", return_value=stream) as opened:
            config = _load_config("policy.json")
        opened.assert_called_once_with("policy.json", "rb")
        stream.read.assert_called_once_with(MAX_CONFIG_BYTES + 1)
        self.assertEqual(config.clients, 100)

    def test_config_requires_utf8_without_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for raw in (b'\xff', b'\xef\xbb\xbf{}', '{}'.encode('utf-16'), '{}'.encode('utf-32')):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    result = self.run_cli("--config", str(path))
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertNotIn("Traceback", result.stderr)

    def test_valid_config_whitespace_and_escaped_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_bytes(b' \r\n\t{"cl\\u0069ents": 2, "max_attempts": 1}\r\n')
            result = self.run_cli("--config", str(path), "--summary-only")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["summary"]["attempts"], 2)

    def test_help_version(self):
        self.assertEqual(self.run_cli("--help").returncode, 0)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "0.1.0")


if __name__ == "__main__":
    unittest.main()
