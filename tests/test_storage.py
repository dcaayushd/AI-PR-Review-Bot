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
                provider_used="gemini",
                model_used="gpt-5.4",
                chunk_count=2,
                redaction_count=3,
            )
            store.mark_completed(job.job_id, report)
            completed = store.get_job(job.job_id)
            assert completed is not None
            self.assertEqual(completed.status, "completed")
            self.assertEqual(completed.model_used, "gpt-5.4")
            self.assertEqual(completed.provider, "gemini")
            self.assertEqual(completed.analyzed_files_count, 2)
            self.assertEqual(completed.redaction_count, 3)

            summary = store.metrics_summary()
            self.assertEqual(summary["total_jobs"], 1)
            self.assertEqual(summary["total_redactions"], 3)

    def test_create_or_get_job_reuses_active_job_for_same_head(self) -> None:
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
            duplicate_request = ReviewRequest(
                delivery_id="delivery-2",
                event_name="pull_request",
                action="synchronize",
                installation_id=10,
                pr_context=request.pr_context,
            )

            first_job, first_created = store.create_or_get_job(request)
            second_job, second_created = store.create_or_get_job(duplicate_request)
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first_job.job_id, second_job.job_id)

    def test_supersede_pull_jobs_marks_older_active_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reviews.db"
            store = ReviewJobStore(f"sqlite:///{db_path}")
            first_request = ReviewRequest(
                delivery_id="delivery-1",
                event_name="pull_request",
                action="opened",
                installation_id=10,
                pr_context=PullRequestContext(
                    owner="octo",
                    repo="repo",
                    pull_number=5,
                    title="Initial review",
                    body="",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                ),
            )
            second_request = ReviewRequest(
                delivery_id="delivery-2",
                event_name="pull_request",
                action="synchronize",
                installation_id=10,
                pr_context=PullRequestContext(
                    owner="octo",
                    repo="repo",
                    pull_number=5,
                    title="New head",
                    body="",
                    base_sha="a" * 40,
                    head_sha="c" * 40,
                ),
            )

            first_job, _ = store.create_or_get_job(first_request)
            store.mark_running(first_job.job_id)
            second_job, _ = store.create_or_get_job(second_request)

            superseded = store.supersede_pull_jobs(
                repo_full_name="octo/repo",
                pull_number=5,
                exclude_job_id=second_job.job_id,
                new_head_sha=second_request.pr_context.head_sha,
            )

            self.assertEqual(len(superseded), 1)
            updated_first = store.get_job(first_job.job_id)
            assert updated_first is not None
            self.assertEqual(updated_first.status, "superseded")
            self.assertEqual(updated_first.superseded_by_head_sha, "c" * 40)

            updated_second = store.get_job(second_job.job_id)
            assert updated_second is not None
            self.assertEqual(updated_second.status, "queued")

    def test_count_jobs_filters_by_status_and_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reviews.db"
            store = ReviewJobStore(f"sqlite:///{db_path}")
            request_one = ReviewRequest(
                delivery_id="delivery-1",
                event_name="pull_request",
                action="opened",
                installation_id=10,
                pr_context=PullRequestContext(
                    owner="octo",
                    repo="repo",
                    pull_number=5,
                    title="PR one",
                    body="",
                    base_sha="a" * 40,
                    head_sha="b" * 40,
                ),
            )
            request_two = ReviewRequest(
                delivery_id="delivery-2",
                event_name="pull_request",
                action="opened",
                installation_id=10,
                pr_context=PullRequestContext(
                    owner="octo",
                    repo="another",
                    pull_number=8,
                    title="PR two",
                    body="",
                    base_sha="a" * 40,
                    head_sha="c" * 40,
                ),
            )

            job_one, _ = store.create_or_get_job(request_one)
            job_two, _ = store.create_or_get_job(request_two)
            store.mark_running(job_one.job_id)
            store.mark_rejected(job_two.job_id, "queue full")

            self.assertEqual(store.count_jobs(statuses=("queued", "running")), 1)
            self.assertEqual(store.count_jobs(statuses=("running",), repo_full_name="octo/repo"), 1)
            self.assertEqual(store.count_jobs(statuses=("rejected",), repo_full_name="octo/another"), 1)


if __name__ == "__main__":
    unittest.main()
