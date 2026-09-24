"""Smoke test for the Windows scheduled-task runner using a fake secret."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT / "scripts" / "run_windows.ps1"
SHELL = shutil.which("pwsh") or "powershell.exe"


@unittest.skipUnless(os.name == "nt", "Windows Task Scheduler runner")
class WindowsRunnerTests(unittest.TestCase):
    def test_dpapi_secret_launches_offline_sample_without_printing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_path = Path(directory) / "sendkey.dpapi"
            env = dict(os.environ, FRONTIER_TEST_SECRET_PATH=str(secret_path))
            create = subprocess.run(
                [
                    SHELL, "-NoProfile", "-NonInteractive", "-Command",
                    "$s = ConvertTo-SecureString 'TEST-KEY' -AsPlainText -Force; "
                    "ConvertFrom-SecureString $s | Set-Content -LiteralPath $env:FRONTIER_TEST_SECRET_PATH",
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20,
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            result = subprocess.run(
                [
                    SHELL, "-NoProfile", "-NonInteractive", "-File", str(RUNNER),
                    "-ProjectPath", str(PROJECT),
                    "-PythonPath", sys.executable,
                    "-SecretPath", str(secret_path),
                    "-Sample",
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("FPGA accelerator", result.stdout)
            self.assertNotIn("TEST-KEY", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
