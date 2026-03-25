import unittest

from pr_review_bot.checkout import build_authenticated_repo_url


class CheckoutTests(unittest.TestCase):
    def test_build_authenticated_repo_url_uses_x_access_token_auth(self) -> None:
        url = build_authenticated_repo_url("octo/repo", "abc123")
        self.assertEqual(url, "https://x-access-token:abc123@github.com/octo/repo.git")

    def test_build_authenticated_repo_url_encodes_special_characters(self) -> None:
        url = build_authenticated_repo_url("octo/repo", "a+b/c=")
        self.assertEqual(url, "https://x-access-token:a%2Bb%2Fc%3D@github.com/octo/repo.git")


if __name__ == "__main__":
    unittest.main()
