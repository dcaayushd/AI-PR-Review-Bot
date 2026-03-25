import unittest

from pr_review_bot.domain import PullRequestContext, ReviewFinding, ReviewReport
from pr_review_bot.formatter import format_summary_comment


class FormatterTests(unittest.TestCase):
    def test_format_summary_comment_includes_required_sections(self) -> None:
        report = ReviewReport(
            summary_points=[
                "Analyzed 1 reviewable files across 1 diff chunk(s).",
                "Risk level is high: found 1 critical issue(s) that should be fixed before merge.",
            ],
            findings=[
                ReviewFinding(
                    title="Missing input validation",
                    severity="critical",
                    category="security",
                    why_it_matters="Untrusted input reaches a shell command without validation.",
                    suggested_fix="Validate the input and avoid shell interpolation.",
                    file_path="src/app.py",
                    line=12,
                    code_snippet="safe_value = shlex.quote(user_value)",
                ),
                ReviewFinding(
                    title="Missing regression test",
                    severity="warning",
                    category="testing",
                    why_it_matters="The failure mode is not covered by tests.",
                    suggested_fix="Add a test for malformed payloads.",
                    file_path="tests/test_app.py",
                    line=44,
                ),
            ],
            suggested_tests=["Add a malformed payload test case."],
            analyzed_files=["src/app.py"],
            model_used="gpt-5.4",
            chunk_count=1,
        )
        pr_context = PullRequestContext(
            owner="octo",
            repo="repo",
            pull_number=42,
            title="Improve validation",
            body="",
            base_sha="a" * 40,
            head_sha="b" * 40,
        )

        rendered = format_summary_comment(report, pr_context)

        self.assertIn("### 1. Summary", rendered)
        self.assertIn("### 2. Critical Issues (must fix)", rendered)
        self.assertIn("### 3. Improvements (should fix)", rendered)
        self.assertIn("### 4. Nitpicks (optional)", rendered)
        self.assertIn("### 5. Suggested Tests", rendered)
        self.assertNotIn("No improvements flagged.", rendered)
        self.assertNotIn("No critical issues found.", rendered)
        self.assertIn("[`src/app.py:12`](https://github.com/octo/repo/blob/", rendered)


if __name__ == "__main__":
    unittest.main()
