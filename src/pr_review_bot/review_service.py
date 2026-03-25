from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from .checkout import checkout_pull_request
from .config import GitHubSettings, load_config
from .formatter import format_inline_comment, format_summary_comment
from .github_api import GitHubAPIError, GitHubClient
from .github_app import GitHubAppClient
from .reviewer import ReviewAbortedError, run_review
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
            superseded_jobs = self._supersede_stale_pull_jobs(job, request)
            if superseded_jobs:
                LOGGER.info(
                    "Superseded %s older job(s) for %s#%s with new head %s.",
                    len(superseded_jobs),
                    request.pr_context.repo_full_name,
                    request.pr_context.pull_number,
                    request.pr_context.head_sha[:12],
                )
            rejection_reason = self._admission_rejection_reason(job)
            if rejection_reason:
                self._store.mark_rejected(job.job_id, rejection_reason)
                LOGGER.warning("Rejected review job %s: %s", job.job_id, rejection_reason)
                rejected_job = self._store.get_job(job.job_id)
                return rejected_job or job
            self._executor.submit(self._run_job, job.job_id, request)
        return job

    def _run_job(self, job_id: str, request: ReviewRequest) -> None:
        current_job = self._store.get_job(job_id)
        if current_job is None:
            LOGGER.warning("Skipping review job %s because it no longer exists.", job_id)
            return
        if current_job.status != "queued":
            LOGGER.info("Skipping worker start for job %s because it is already %s.", job_id, current_job.status)
            return
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
        check_run_id: int | None = None
        try:
            installation_token = self._github_app.create_installation_token(request.installation_id)
            github = self._github_app.create_repo_client(
                request.installation_id,
                request.pr_context.repo_full_name,
                github_settings,
            )
            self._raise_if_aborted(job_id)
            check_run_id = self._maybe_create_in_progress_check_run(github, github_settings, job_id, request)
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
            self._raise_if_aborted(job_id)
            if checkout.resolved_head_sha != request.pr_context.head_sha:
                self._store.mark_superseded(
                    job_id,
                    reason="Skipped outdated delivery because the pull request head changed before checkout completed.",
                    superseded_by_head_sha=checkout.resolved_head_sha,
                )
                self._maybe_complete_check_run(
                    github,
                    check_run_id,
                    job_id=job_id,
                    conclusion="neutral",
                    title="Review skipped",
                    summary="Skipped because the pull request head changed before checkout completed.",
                )
                return

            config = load_config(checkout.path, allow_repo_github_settings=False)
            report = run_review(
                checkout.path,
                request.pr_context,
                config,
                head_revision=checkout.head_revision,
                should_abort=lambda: self._is_job_aborted(job_id),
            )
            latest_pr = github.get_pull_request(request.pr_context.pull_number)
            latest_head = ((latest_pr.get("head") or {}).get("sha") if isinstance(latest_pr, dict) else "") or ""
            if str(latest_head) != request.pr_context.head_sha:
                self._store.mark_superseded(
                    job_id,
                    reason="Skipped posting review because a newer commit was pushed to the pull request.",
                    superseded_by_head_sha=str(latest_head),
                )
                self._maybe_complete_check_run(
                    github,
                    check_run_id,
                    job_id=job_id,
                    conclusion="neutral",
                    title="Review skipped",
                    summary="Skipped because a newer commit was pushed before review results were posted.",
                )
                return

            self._raise_if_aborted(job_id)
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
            self._raise_if_aborted(job_id)
            github.create_inline_review(
                pull_number=request.pr_context.pull_number,
                commit_id=request.pr_context.head_sha,
                comments=inline_payload,
                body=f"Inline AI review for `{request.pr_context.head_sha[:12]}`.",
            )
            if self._is_job_aborted(job_id):
                LOGGER.info("Suppressing completion for job %s because it was superseded during execution.", job_id)
                self._maybe_complete_check_run(
                    github,
                    check_run_id,
                    job_id=job_id,
                    conclusion="neutral",
                    title="Review superseded",
                    summary="Stopped posting results because a newer pull request commit superseded this review.",
                )
                return
            self._store.mark_completed(job_id, report)
            self._maybe_complete_check_run(
                github,
                check_run_id,
                job_id=job_id,
                conclusion=_conclusion_for_report(report),
                title=_title_for_report(report),
                summary=_summary_for_check_run(report),
                text=summary_comment,
            )
            LOGGER.info("Completed review job %s with %s findings.", job_id, len(report.findings))
        except ReviewAbortedError as exc:
            LOGGER.info("Review job %s aborted: %s", job_id, exc)
            if not self._is_terminal(job_id):
                self._store.mark_superseded(
                    job_id,
                    reason=str(exc),
                    superseded_by_head_sha=request.pr_context.head_sha,
                )
            self._maybe_complete_check_run(
                github,
                check_run_id,
                job_id=job_id,
                conclusion="neutral",
                title="Review superseded",
                summary=str(exc),
            )
        except Exception as exc:
            LOGGER.exception("Review job %s failed: %s", job_id, exc)
            if not self._is_job_aborted(job_id):
                self._store.mark_failed(job_id, str(exc))
            self._maybe_complete_check_run(
                github,
                check_run_id,
                job_id=job_id,
                conclusion="failure",
                title="Review failed",
                summary=str(exc),
            )
        finally:
            if github is not None:
                github.close()
            if checkout is not None:
                checkout.cleanup()

    def runtime_snapshot(self) -> dict[str, int | bool]:
        queued = self._store.count_jobs(statuses=("queued",))
        running = self._store.count_jobs(statuses=("running",))
        return {
            "queued_jobs": queued,
            "running_jobs": running,
            "max_pending_reviews": self._settings.max_pending_reviews,
            "max_parallel_reviews": self._settings.max_parallel_reviews,
            "max_repo_active_reviews": self._settings.max_repo_active_reviews,
            "queue_accepting": queued < self._settings.max_pending_reviews,
        }

    def _supersede_stale_pull_jobs(self, job: ReviewJob, request: ReviewRequest) -> list[ReviewJob]:
        if not self._settings.cancel_superseded_reviews:
            return []
        return self._store.supersede_pull_jobs(
            repo_full_name=job.repo_full_name,
            pull_number=job.pull_number,
            exclude_job_id=job.job_id,
            new_head_sha=request.pr_context.head_sha,
        )

    def _admission_rejection_reason(self, job: ReviewJob) -> str | None:
        queued_jobs = self._store.count_jobs(statuses=("queued",))
        if queued_jobs > self._settings.max_pending_reviews:
            return (
                f"Queue capacity exceeded: {queued_jobs} queued job(s) with MAX_PENDING_REVIEWS="
                f"{self._settings.max_pending_reviews}."
            )
        repo_active_jobs = self._store.count_jobs(statuses=("queued", "running"), repo_full_name=job.repo_full_name)
        if repo_active_jobs > self._settings.max_repo_active_reviews:
            return (
                f"Repository concurrency limit exceeded for {job.repo_full_name}: {repo_active_jobs} active job(s) "
                f"with MAX_REPO_ACTIVE_REVIEWS={self._settings.max_repo_active_reviews}."
            )
        return None

    def _is_job_aborted(self, job_id: str) -> bool:
        job = self._store.get_job(job_id)
        if job is None:
            return True
        return job.status in {"superseded", "rejected"}

    def _is_terminal(self, job_id: str) -> bool:
        job = self._store.get_job(job_id)
        if job is None:
            return True
        return job.status in {"completed", "skipped", "failed", "superseded", "rejected"}

    def _raise_if_aborted(self, job_id: str) -> None:
        if self._is_job_aborted(job_id):
            raise ReviewAbortedError("Review aborted because a newer pull request head superseded this job.")

    def _maybe_create_in_progress_check_run(
        self,
        github: GitHubClient,
        github_settings: GitHubSettings,
        job_id: str,
        request: ReviewRequest,
    ) -> int | None:
        if not github_settings.create_check_run:
            return None
        try:
            response = github.create_check_run(
                name=github_settings.check_run_name,
                head_sha=request.pr_context.head_sha,
                status="in_progress",
                external_id=job_id,
                started_at=_utc_now(),
                details_url=self._details_url(job_id),
                output={
                    "title": "Review in progress",
                    "summary": f"Reviewing PR #{request.pr_context.pull_number} for {request.pr_context.repo_full_name}.",
                },
            )
            check_run_id = response.get("id")
            if isinstance(check_run_id, int):
                self._store.set_check_run_id(job_id, check_run_id)
                return check_run_id
        except GitHubAPIError as exc:
            LOGGER.warning("Unable to create check run for job %s: %s", job_id, exc)
        return None

    def _maybe_complete_check_run(
        self,
        github: GitHubClient | None,
        check_run_id: int | None,
        *,
        job_id: str | None = None,
        conclusion: str,
        title: str,
        summary: str,
        text: str | None = None,
    ) -> None:
        if github is None or check_run_id is None:
            return
        try:
            output: dict[str, Any] = {
                "title": title[:255],
                "summary": summary[:65535],
            }
            if text:
                output["text"] = text[:65535]
            github.update_check_run(
                check_run_id=check_run_id,
                status="completed",
                conclusion=conclusion,
                completed_at=_utc_now(),
                details_url=self._details_url(job_id) if job_id else None,
                output=output,
            )
        except GitHubAPIError as exc:
            LOGGER.warning("Unable to update check run %s: %s", check_run_id, exc)

    def _details_url(self, job_id: str) -> str | None:
        if not self._settings.public_base_url:
            return None
        return f"{self._settings.public_base_url}/jobs/{job_id}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _conclusion_for_report(report) -> str:
    if any(finding.severity == "critical" for finding in report.findings):
        return "action_required"
    if report.findings or report.omitted_sections:
        return "neutral"
    return "success"


def _title_for_report(report) -> str:
    if any(finding.severity == "critical" for finding in report.findings):
        return "Critical review findings detected"
    if report.findings:
        return "Review completed with suggested improvements"
    return "Review completed successfully"


def _summary_for_check_run(report) -> str:
    parts = list(report.summary_points[:4]) or ["Review completed."]
    return "\n".join(f"- {item}" for item in parts)
