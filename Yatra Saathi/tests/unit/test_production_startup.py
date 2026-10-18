"""Regression test verifying that production entrypoint scripts resolve imports cleanly.

Prevents Render startup failures such as:
    ModuleNotFoundError: No module named 'scripts'
    ModuleNotFoundError: No module named 'src'
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"


class TestProductionStartupImports(unittest.TestCase):
    def test_direct_script_execution_resolves_scripts_and_src(self):
        """Simulates Render running 'python scripts/run_production.py' from backend root."""
        sub_code = (
            "import sys\n"
            "from pathlib import Path\n"
            "import scripts.run_production\n"
            "import scripts.init_production_db\n"
            "print('SUCCESS: scripts and src resolved cleanly')\n"
        )
        cmd = [sys.executable, "-c", sub_code]
        res = subprocess.run(cmd, cwd=str(_BACKEND_DIR), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Import test failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn("SUCCESS: scripts and src resolved cleanly", res.stdout)

    def test_script_path_invocation_resolves_backend_dir(self):
        """Simulates executing 'python scripts/run_production.py' where sys.path[0] is scripts/."""
        sub_code = (
            "import sys\n"
            "from pathlib import Path\n"
            "scripts_dir = Path.cwd() / 'scripts'\n"
            "sys.path[0] = str(scripts_dir)\n"
            "import run_production\n"
            "assert hasattr(run_production, '_BACKEND_DIR')\n"
            "print('SUCCESS: sys.path[0] was normalized and backend root was added')\n"
        )
        cmd = [sys.executable, "-c", sub_code]
        res = subprocess.run(cmd, cwd=str(_BACKEND_DIR), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Path invocation failed:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        self.assertIn("SUCCESS: sys.path[0] was normalized and backend root was added", res.stdout)


if __name__ == "__main__":
    unittest.main()
