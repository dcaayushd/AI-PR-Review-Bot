import unittest

from pr_review_bot.dashboard import render_dashboard_page, render_job_detail_page
from pr_review_bot.storage import ReviewJob


class DashboardTests(unittest.TestCase):
    def test_render_dashboard_page_includes_recent_jobs_and_metrics(self) -> None:
        job = ReviewJob(
            job_id="job-1",
            delivery_id="delivery-1",
            event_name="pull_request",
            action="opened",
            installation_id=10,
            repo_full_name="octo/repo",
            pull_number=7,
            base_sha="a" * 40,
            head_sha="b" * 40,
            status="completed",
            created_at="2026-03-25T10:00:00+00:00",
            updated_at="2026-03-25T10:01:00+00:00",
            provider="gemini",
            model_used="gemini-2.5-flash",
            risk_level="high",
            risk_score=8,
            findings_count=2,
        )
        html = render_dashboard_page(
            app_version="0.4.0",
            runtime_snapshot={
                "queued_jobs": 1,
                "running_jobs": 2,
                "max_pending_reviews": 32,
                "max_parallel_reviews": 4,
                "max_repo_active_reviews": 6,
                "queue_accepting": True,
            },
            metrics_summary={
                "counts_by_status": {"completed": 5, "running": 2},
                "counts_by_provider": {"gemini": 5},
                "counts_by_risk": {"high": 3, "low": 2},
                "total_jobs": 7,
                "total_findings": 9,
                "total_inline_comments": 4,
                "total_redactions": 3,
                "active_repositories": 2,
                "avg_duration_seconds": 12.4,
                "top_repositories": [{"repo_full_name": "octo/repo", "job_count": 4}],
            },
            recent_jobs=[job],
        )

        self.assertIn("AI PR Review Control Plane", html)
        self.assertIn("octo/repo", html)
        self.assertIn("/jobs/job-1/view", html)
        self.assertIn("Avg duration", html)
        self.assertIn("Risk mix", html)
        self.assertIn("High", html)

    def test_render_job_detail_page_includes_findings_and_tests(self) -> None:
        job = ReviewJob(
            job_id="job-2",
            delivery_id="delivery-2",
            event_name="pull_request",
            action="synchronize",
            installation_id=10,
            repo_full_name="octo/repo",
            pull_number=9,
            base_sha="a" * 40,
            head_sha="c" * 40,
            status="completed",
            created_at="2026-03-25T10:00:00+00:00",
            updated_at="2026-03-25T10:03:00+00:00",
            started_at="2026-03-25T10:00:20+00:00",
            completed_at="2026-03-25T10:02:20+00:00",
            findings_count=1,
            inline_comments_count=1,
            analyzed_files_count=1,
            model_used="gpt-5.4",
            provider="openai",
            chunk_count=1,
            redaction_count=2,
            risk_level="high",
            risk_score=9,
            risk_reasons_json='["changes security-sensitive or auth-related paths","changes dependency or infrastructure files"]',
            findings_json='[{"title":"Missing guard","severity":"critical","category":"correctness","why_it_matters":"Can crash on null.","suggested_fix":"Add a null check.","file_path":"src/app.py","line":18}]',
            suggested_tests_json='["Add a null input regression test."]',
            analyzed_files_json='["src/app.py"]',
            skipped_files_json='["assets/logo.png (ignored)"]',
            summary_points_json='["Analyzed 1 reviewable file.","Risk level is high."]',
        )

        html = render_job_detail_page(app_version="0.4.0", job=job)

        self.assertIn("Missing guard", html)
        self.assertIn("Add a null input regression test.", html)
        self.assertIn("src/app.py", html)
        self.assertIn("octo/repo", html)
        self.assertIn("Risk routing", html)


if __name__ == "__main__":
    unittest.main()
