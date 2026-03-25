import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pr_review_bot.config import load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_infers_gemini_when_google_api_key_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            with patch.dict(
                os.environ,
                {
                    "GOOGLE_API_KEY": "test-google-key",
                    "OPENAI_API_KEY": "",
                    "LLM_PROVIDER": "",
                },
                clear=False,
            ):
                config = load_config(repo_root)

            self.assertEqual(config.review.provider, "gemini")
            self.assertEqual(config.review.model, "gemini-2.5-flash")
            self.assertEqual(config.review.fallback_model, "gemini-2.5-flash-lite")


if __name__ == "__main__":
    unittest.main()
