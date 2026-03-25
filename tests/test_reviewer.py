import unittest
from pathlib import Path
from unittest.mock import patch

from pr_review_bot.config import BotConfig
from pr_review_bot.domain import PullRequestContext
from pr_review_bot.reviewer import ReviewAbortedError, run_review


class ReviewerAbortTests(unittest.TestCase):
    @patch("pr_review_bot.reviewer.load_repository_snippets", return_value=[])
    @patch(
        "pr_review_bot.reviewer.build_unified_diff",
        return_value=(
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-print('old')\n"
            "+print('new')\n"
        ),
    )
    def test_run_review_aborts_before_model_call_when_cancelled(
        self,
        _build_unified_diff,
        _load_repository_snippets,
    ) -> None:
        config = BotConfig()
        pr_context = PullRequestContext(
            owner="octo",
            repo="repo",
            pull_number=5,
            title="Update app",
            body="",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )

        with patch("pr_review_bot.reviewer.LLMClient") as llm_client:
            with self.assertRaises(ReviewAbortedError):
                run_review(
                    Path("."),
                    pr_context,
                    config,
                    head_revision="b" * 40,
                    should_abort=lambda: True,
                )

        llm_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
