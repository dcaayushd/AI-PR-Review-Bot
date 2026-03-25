from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .checkout import checkout_pull_request
from .config import GitHubSettings, load_config
from .formatter import format_inline_comment, format_summary_comment
from .github_app import GitHubAppClient
from .reviewer import run_review
from .runtime import AppSettings
from .storage import ReviewJob, ReviewJobStore
from .webhooks import ReviewRequest

LOGGER = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, settings: AppSettings, store: ReviewJobStore) -> None:
        self._settings = settings
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=settings.max_parallel_reviews, thread_name_prefix="review-job")
        self._github_app = GitHubAppClient(settings)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._github_app.close()

    def submit(self, request: ReviewRequest) -> ReviewJob:
        job, created = self._store.create_or_get_job(request)
        if created:
            self._executor.submit(self._run_job, job.job_id, request)
        return job

    def _run_job(self, job_id: str, request: ReviewRequest) -> None:
        LOGGER.info(
            "Starting review job %s for %s#%s", job_id, request.pr_context.repo_full_name, request.pr_context.pull_number
        )
        self._store.mark_running(job_id)
        github_settings = GitHubSettings(
            api_url=self._settings.github_api_url,
            api_version=self._settings.github_api_version,
        )
        checkout = None
        github = None
        try:
            installation_token = self._github_app.create_installation_token(request.installation_id)
            checkout = checkout_pull_request(
                repo_full_name=request.pr_context.repo_full_name,
                pull_number=request.pr_context.pull_number,
                base_sha=request.pr_context.base_sha,
                base_ref=request.pr_context.base_ref,
                token=installation_token,
                workspace_root=self._settings.workspace_root,
                fetch_depth=self._settings.git_fetch_depth,
                fetch_timeout_seconds=self._settings.git_fetch_timeout_seconds,
            )
            if checkout.resolved_head_sha != request.pr_context.head_sha:
                self._store.mark_skipped(
                    job_id,
                    "Skipped outdated delivery because the pull request head changed before checkout completed.",
                )
                return

            config = load_config(checkout.path, allow_repo_github_settings=False)
            report = run_review(checkout.path, request.pr_context, config, head_revision=checkout.head_revision)

            github = self._github_app.create_repo_client(
                request.installation_id,
                request.pr_context.repo_full_name,
                github_settings,
            )
            latest_pr = github.get_pull_request(request.pr_context.pull_number)
            latest_head = ((latest_pr.get("head") or {}).get("sha") if isinstance(latest_pr, dict) else "") or ""
            if str(latest_head) != request.pr_context.head_sha:
                self._store.mark_skipped(
                    job_id,
                    "Skipped posting review because a newer commit was pushed to the pull request.",
                )
                return

            summary_comment = format_summary_comment(report, request.pr_context)
            github.upsert_summary_comment(request.pr_context.pull_number, summary_comment)
            inline_payload = [
                {
                    "path": comment.file_path,
                    "line": comment.line,
                    "side": "RIGHT",
                    "body": format_inline_comment(comment),
                }
                for comment in report.inline_comments
            ]
            github.create_inline_review(
                pull_number=request.pr_context.pull_number,
                commit_id=request.pr_context.head_sha,
                comments=inline_payload,
                body=f"Inline AI review for `{request.pr_context.head_sha[:12]}`.",
            )
            self._store.mark_completed(job_id, report)
            LOGGER.info("Completed review job %s with %s findings.", job_id, len(report.findings))
        except Exception as exc:
            LOGGER.exception("Review job %s failed: %s", job_id, exc)
            self._store.mark_failed(job_id, str(exc))
        finally:
            if github is not None:
                github.close()
            if checkout is not None:
                checkout.cleanup()
