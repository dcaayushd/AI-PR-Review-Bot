import unittest

from pr_review_bot.config import SecuritySettings
from pr_review_bot.domain import DiffChunk, PullRequestContext, RepositorySnippet
from pr_review_bot.redaction import redact_chunks, redact_pull_request_context, redact_repository_snippets, redact_text


class RedactionTests(unittest.TestCase):
    def test_redact_text_masks_google_api_keys_and_assignments(self) -> None:
        settings = SecuritySettings()
        text = "GOOGLE_API_KEY=AIzaSy12345678901234567890123456789012345\nsecret=super-secret"
        redacted, count = redact_text(text, settings)
        self.assertIn("[REDACTED]", redacted)
        self.assertGreaterEqual(count, 2)
        self.assertNotIn("super-secret", redacted)

    def test_redact_chunks_preserves_chunk_identity(self) -> None:
        settings = SecuritySettings()
        chunks = [DiffChunk(chunk_id=1, text="+ api_key=sk-abcdefghijklmnopqrstuvwxyz123456", files=["src/app.py"])]
        redacted_chunks, count = redact_chunks(chunks, settings)
        self.assertEqual(redacted_chunks[0].chunk_id, 1)
        self.assertEqual(redacted_chunks[0].files, ["src/app.py"])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz123456", redacted_chunks[0].text)
        self.assertGreaterEqual(count, 1)

    def test_redact_pr_context_and_repo_snippets(self) -> None:
        settings = SecuritySettings()
        pr_context = PullRequestContext(
            owner="octo",
            repo="repo",
            pull_number=1,
            title="Use token ghp_abcdefghijklmnopqrstuvwxyz123456",
            body="client_secret=hidden",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )
        safe_context, pr_count = redact_pull_request_context(pr_context, settings)
        snippets, snippet_count = redact_repository_snippets(
            [RepositorySnippet(path="README.md", content="password=my-password")],
            settings,
        )
        self.assertGreaterEqual(pr_count, 2)
        self.assertGreaterEqual(snippet_count, 1)
        self.assertNotIn("hidden", safe_context.body)
        self.assertNotIn("my-password", snippets[0].content)


if __name__ == "__main__":
    unittest.main()
