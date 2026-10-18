"""Enforces the import rule (section 4, adapted to the repo-root layout):
Developer 2's AI/agent code (root `ai/`, or a legacy `backend/src/agent|tools`)
may only import the shared `src.contracts` package, never the backend's
database, services, tokens or API internals. Also checks `.env.agent.example`
carries no DB path or backend secrets (section 12)."""
from __future__ import annotations

import ast
import os
import unittest

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(TESTS_DIR)) if os.path.basename(TESTS_DIR) == "backend" \
    else os.path.dirname(TESTS_DIR)
BACKEND = os.path.join(REPO_ROOT, "backend") if os.path.isdir(os.path.join(REPO_ROOT, "backend")) else REPO_ROOT

FORBIDDEN_PREFIXES = ("src.db", "src.services", "src.core.human_tokens", "src.core.agent_tokens", "src.api")
CANDIDATE_AGENT_DIRS = (
    os.path.join(REPO_ROOT, "ai"),
    os.path.join(BACKEND, "src", "agent"),
    os.path.join(BACKEND, "src", "tools"),
)


def _imported_modules(tree: ast.AST) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


class AgentIsolationTests(unittest.TestCase):
    def test_agent_and_tools_only_import_contracts(self):
        offenders = []
        for package_dir in CANDIDATE_AGENT_DIRS:
            if not os.path.isdir(package_dir):
                continue  # Developer 2's code; nothing to check until it exists.
            for root, _dirs, files in os.walk(package_dir):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read(), filename=path)
                    for module in _imported_modules(tree):
                        if module.startswith(FORBIDDEN_PREFIXES):
                            offenders.append(f"{path}: imports {module}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_env_agent_example_has_no_db_path_or_backend_secrets(self):
        path = os.path.join(REPO_ROOT, "ai", ".env.agent.example")
        self.assertTrue(os.path.isfile(path), "ai/.env.agent.example is missing")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for forbidden in ("APS_DB_PATH", "APS_DB_ORIGINAL_PATH", "HUMAN_TOKEN_SECRET", "AGENT_TOKEN_SECRET"):
            self.assertNotIn(forbidden, text, f"{forbidden} must never appear in .env.agent.example")


if __name__ == "__main__":
    unittest.main()
