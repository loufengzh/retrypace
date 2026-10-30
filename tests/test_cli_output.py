import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OutputTests(unittest.TestCase):
    def cases(self):
        for args in (("--summary-only",), (), ("--format", "csv")):
            for gate in ((), ("--max-peak-concurrency", "0")):
                yield args + gate

    def assert_output_error(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("retrypace: output failed (", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("Exception ignored", result.stderr)
        self.assertNotIn("exceeds", result.stderr)

    @unittest.skipUnless(Path('/dev/full').exists(), 'requires a full device')
    def test_full_device(self):
        for args in self.cases():
            with self.subTest(args=args), open('/dev/full', 'wb') as output:
                result = subprocess.run([sys.executable, '-m', 'retrypace', *args],
                                        cwd=ROOT, stdout=output, stderr=subprocess.PIPE,
                                        text=True, timeout=30)
                self.assert_output_error(result)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX pipe descriptors')
    def test_pipe_without_reader(self):
        for args in self.cases():
            with self.subTest(args=args):
                reader, writer = os.pipe()
                os.close(reader)
                try:
                    result = subprocess.run([sys.executable, '-m', 'retrypace', *args],
                                            cwd=ROOT, stdout=writer, stderr=subprocess.PIPE,
                                            text=True, timeout=30)
                finally:
                    os.close(writer)
                self.assert_output_error(result)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX closed startup descriptor')
    def test_absent_stdout_at_startup(self):
        for args in self.cases():
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-m', 'retrypace', *args],
                                        cwd=ROOT, stderr=subprocess.PIPE, text=True,
                                        preexec_fn=lambda: os.close(1), timeout=30)
                self.assert_output_error(result)

    def test_closed_stdout(self):
        code = 'import sys; from retrypace.cli import main; sys.stdout.close(); sys.exit(main())'
        for args in self.cases():
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, '-c', code, *args],
                                        cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assert_output_error(result)


if __name__ == '__main__':
    unittest.main()
