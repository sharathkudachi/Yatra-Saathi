"""Backend startup must not silently inherit a repository-level production DATABASE_URL."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.main import _load_backend_environment


class BackendEnvironmentLoadingTests(unittest.TestCase):
    def test_backend_env_stops_root_dotenv_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend_env = Path(tmp) / "backend" / ".env.backend"
            root_env = Path(tmp) / ".env"
            backend_env.parent.mkdir()
            backend_env.touch()
            root_env.touch()

            with patch("src.main.load_dotenv") as load_dotenv:
                loaded = _load_backend_environment([backend_env, root_env])

            self.assertEqual(loaded, backend_env)
            load_dotenv.assert_called_once_with(backend_env)

    def test_root_dotenv_is_fallback_when_no_backend_env_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "backend" / ".env.backend"

            with patch("src.main.load_dotenv") as load_dotenv:
                loaded = _load_backend_environment([missing])

            self.assertIsNone(loaded)
            load_dotenv.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
