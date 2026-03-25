import unittest

from pr_review_bot.webhooks import build_review_request, verify_github_webhook


class WebhookTests(unittest.TestCase):
    def test_verify_github_webhook_accepts_valid_signature(self) -> None:
        payload = b'{"hello":"world"}'
        secret = "top-secret"
        signature = "sha256=b0c5e0dfac98355531e006bb94cc20b4e035f40b56175e6c21818e796ee9c2fc"
        verify_github_webhook(payload, signature, secret)

    def test_build_review_request_ignores_draft_prs(self) -> None:
        payload = {
            "action": "opened",
            "installation": {"id": 7},
            "repository": {"full_name": "octo/repo"},
            "pull_request": {
                "number": 12,
                "title": "Draft",
                "body": "",
                "state": "open",
                "draft": True,
                "base": {"sha": "a" * 40, "ref": "main"},
                "head": {"sha": "b" * 40, "ref": "feature"},
                "user": {"login": "alice"},
            },
        }
        request = build_review_request("delivery-1", "pull_request", payload)
        self.assertIsNone(request)

    def test_build_review_request_returns_pr_context_for_supported_event(self) -> None:
        payload = {
            "action": "synchronize",
            "installation": {"id": 9},
            "repository": {"full_name": "octo/repo"},
            "pull_request": {
                "number": 15,
                "title": "Update API",
                "body": "Refresh endpoint handling",
                "html_url": "https://github.com/octo/repo/pull/15",
                "state": "open",
                "draft": False,
                "base": {"sha": "a" * 40, "ref": "main"},
                "head": {"sha": "b" * 40, "ref": "feature"},
                "user": {"login": "alice"},
            },
        }
        request = build_review_request("delivery-2", "pull_request", payload)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.installation_id, 9)
        self.assertEqual(request.pr_context.repo_full_name, "octo/repo")
        self.assertEqual(request.pr_context.pull_number, 15)


if __name__ == "__main__":
    unittest.main()
