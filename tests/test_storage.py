import tempfile
import unittest
from pathlib import Path

from pr_review_bot.domain import PullRequestContext, ReviewReport
from pr_review_bot.storage import ReviewJobStore
from pr_review_bot.webhooks import ReviewRequest


class StorageTests(unittest.TestCase):
    def test_create_and_complete_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reviews.db"
            store = ReviewJobStore(f"sqlite:///{db_path}")
            request = ReviewRequest(
                delivery_id="delivery-1",
                event_name="pull_request",
                action="opened",
                installation_id=10,
                pr_context=PullRequestContext(
                    owner="octo",
                    repo="repo",
                    pull_number=5,
                    title="Improve review flow",
                    body="",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                ),
            )

            job, created = store.create_or_get_job(request)
            self.assertTrue(created)
            self.assertEqual(job.status, "queued")

            store.mark_running(job.job_id)
            running = store.get_job(job.job_id)
            assert running is not None
            self.assertEqual(running.status, "running")

            report = ReviewReport(
                summary_points=["Analyzed 2 files."],
                analyzed_files=["src/app.py", "tests/test_app.py"],
                model_used="gpt-5.4",
            )
            store.mark_completed(job.job_id, report)
            completed = store.get_job(job.job_id)
            assert completed is not None
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.model_used, "gpt-5.4")


if __name__ == "__main__":
    unittest.main()
