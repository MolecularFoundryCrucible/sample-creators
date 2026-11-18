import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ClientStartupResilienceTests(unittest.TestCase):
    def _clean_env(self, tmpdir, api_key_mode):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": tmpdir,
            "XDG_CONFIG_HOME": tmpdir,
            "CRUCIBLE_AUTH_STORE": "file",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        if api_key_mode == "empty":
            env["CRUCIBLE_API_KEY"] = ""
        elif api_key_mode == "whitespace":
            env["CRUCIBLE_API_KEY"] = "   "
        elif api_key_mode is not None:
            env["CRUCIBLE_API_KEY"] = api_key_mode
        return env

    def test_import_and_mocking_succeed_without_credentials_and_unmocked_request_fails_cleanly(self):
        script = textwrap.dedent("""
            import sys
            from unittest.mock import patch
            sys.path.insert(0, "tests")

            from app import create_app
            import routes.shared as shared
            try:
                from tests import fake_crucible
            except ImportError:
                import fake_crucible
            from crucible import CrucibleClient
            from crucible.errors import NotSignedInError

            assert isinstance(shared.cruc_client, CrucibleClient)
            assert shared.cruc_client.credential_source is None
            assert shared.cruc_client.api_key is None

            app = create_app()
            app.config.update(TESTING=True, SECRET_KEY="test")
            client = app.test_client()
            assert client.get("/").status_code == 200

            with patch("routes.shared.cruc_client.users.get", return_value={
                "unique_id": "0000-0001-2345-6789", "username": "u1", "first_name": "U", "last_name": "One"
            }), patch("routes.shared.cruc_client.users.list_projects", return_value=[{"project_id": "p1"}]):
                r = client.post("/api/user/login", json={"user_ref": "u1"})
                assert r.status_code == 200, r.get_data(as_text=True)

            store, restore = fake_crucible.install(shared.cruc_client)
            restore()
            assert "FakeSamples" not in repr(shared.cruc_client.samples)

            with patch("requests.Session.request", side_effect=AssertionError("Socket must not be touched")):
                try:
                    shared.cruc_client.samples.list()
                except NotSignedInError:
                    pass
                else:
                    raise AssertionError("Expected NotSignedInError on unmocked request")

                r_unauth = client.post("/api/user/login", json={"user_ref": "u1"})
                assert r_unauth.status_code == 500
        """)
        for mode in (None, "empty"):
            with self.subTest(api_key_mode=mode), tempfile.TemporaryDirectory() as tmpdir:
                proc = subprocess.run(
                    [sys.executable, "-B", "-c", script],
                    cwd=REPO_ROOT,
                    env=self._clean_env(tmpdir, mode),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    def test_empty_env_api_key_falls_back_to_config_ini_after_oauth_check(self):
        script = textwrap.dedent("""
            import routes.shared as shared
            assert shared.cruc_client.api_key == "ini-fallback-test-token"
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_dir = Path(tmpdir) / "nano-crucible"
            ini_dir.mkdir(parents=True, exist_ok=True)
            (ini_dir / "config.ini").write_text("[crucible]\napi_key = ini-fallback-test-token\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=REPO_ROOT,
                env=self._clean_env(tmpdir, "empty"),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


    def test_oauth_session_takes_precedence_over_config_ini_when_env_key_is_empty(self):
        script = textwrap.dedent("""
            from unittest.mock import MagicMock, patch
            from crucible.auth.session import SessionCredential

            fake_tokens = MagicMock()
            fake_tokens.access_token = "oauth-session-token"
            fake_tokens.expired.return_value = False
            fake_store = MagicMock()
            fake_store.load.return_value = fake_tokens

            with patch("crucible.auth.store.signed_in", return_value={"backend": "file"}), \
                 patch("crucible.auth.store.store_for", return_value=fake_store):
                import routes.shared as shared
                assert shared.cruc_client.api_key is None
                assert isinstance(shared.cruc_client._credential, SessionCredential)
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_dir = Path(tmpdir) / "nano-crucible"
            ini_dir.mkdir(parents=True, exist_ok=True)
            (ini_dir / "config.ini").write_text("[crucible]\napi_key = ini-should-lose\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=REPO_ROOT,
                env=self._clean_env(tmpdir, "empty"),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")



    def test_whitespace_env_key_falls_back_to_config_ini_with_quotes_and_percent(self):
        script = textwrap.dedent("""
            import routes.shared as shared
            assert shared.cruc_client.api_key == "token-with-%-and-quotes"
        """)
        with tempfile.TemporaryDirectory() as tmpdir:
            ini_dir = Path(tmpdir) / "nano-crucible"
            ini_dir.mkdir(parents=True, exist_ok=True)
            (ini_dir / "config.ini").write_text('[crucible]\napi_key = "token-with-%-and-quotes"\n', encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-B", "-c", script],
                cwd=REPO_ROOT,
                env=self._clean_env(tmpdir, "whitespace"),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
