import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_review_bot.runtime import AppSettings, load_dotenv_file


class RuntimeTests(unittest.TestCase):
    def test_load_dotenv_file_populates_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text("LLM_PROVIDER=gemini\nGOOGLE_API_KEY=test-key\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_dotenv_file(dotenv_path)
                self.assertEqual(os.getenv("LLM_PROVIDER"), "gemini")
                self.assertEqual(os.getenv("GOOGLE_API_KEY"), "test-key")

    def test_load_dotenv_file_does_not_override_existing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text("GOOGLE_API_KEY=file-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"GOOGLE_API_KEY": "env-key"}, clear=True):
                load_dotenv_file(dotenv_path)
                self.assertEqual(os.getenv("GOOGLE_API_KEY"), "env-key")

    def test_app_settings_reads_operational_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            private_key_path = Path(temp_dir) / "app.pem"
            private_key_path.write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n", encoding="utf-8")
            workspace_root = Path(temp_dir) / "workspaces"
            with patch.dict(
                os.environ,
                {
                    "GITHUB_APP_ID": "123",
                    "GITHUB_APP_PRIVATE_KEY_PATH": str(private_key_path),
                    "GITHUB_WEBHOOK_SECRET": "secret",
                    "WORKSPACE_ROOT": str(workspace_root),
                    "MAX_PENDING_REVIEWS": "12",
                    "MAX_REPO_ACTIVE_REVIEWS": "3",
                    "CANCEL_SUPERSEDED_REVIEWS": "false",
                    "PUBLIC_BASE_URL": "https://bot.example.com/",
                },
                clear=True,
            ):
                settings = AppSettings.from_env()

            self.assertEqual(settings.max_pending_reviews, 12)
            self.assertEqual(settings.max_repo_active_reviews, 3)
            self.assertFalse(settings.cancel_superseded_reviews)
            self.assertEqual(settings.public_base_url, "https://bot.example.com")


if __name__ == "__main__":
    unittest.main()
