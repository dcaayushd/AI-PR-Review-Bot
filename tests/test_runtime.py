import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_review_bot.runtime import load_dotenv_file


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


if __name__ == "__main__":
    unittest.main()
