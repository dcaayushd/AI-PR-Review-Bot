from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from .config import GitHubSettings
from .formatter import SUMMARY_MARKER

LOGGER = logging.getLogger(__name__)


class GitHubAPIError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, repo_full_name: str, settings: GitHubSettings) -> None:
        if "/" not in repo_full_name:
            raise ValueError(f"Invalid repository name: {repo_full_name}")
        self._repo_full_name = repo_full_name
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.api_url,
            timeout=settings.request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": settings.api_version,
                "User-Agent": "ai-pr-review-bot",
            },
        )

    @classmethod
    def from_env(cls, repo_full_name: str, settings: GitHubSettings) -> "GitHubClient":
        token = os.getenv("GITHUB_TOKEN", "").strip()
        if not token:
            raise GitHubAPIError("GITHUB_TOKEN is required to post review comments.")
        return cls(token=token, repo_full_name=repo_full_name, settings=settings)

    @classmethod
    def from_token(cls, token: str, repo_full_name: str, settings: GitHubSettings) -> "GitHubClient":
        return cls(token=token, repo_full_name=repo_full_name, settings=settings)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def upsert_summary_comment(self, pull_number: int, body: str) -> None:
        if not self._settings.update_summary_comment:
            self._request("POST", self._issue_comments_path(pull_number), json={"body": body})
            return

        comments = self._request("GET", self._issue_comments_path(pull_number), params={"per_page": 100})
        if not isinstance(comments, list):
            raise GitHubAPIError("Unexpected response when listing issue comments.")

        existing = next(
            (comment for comment in comments if isinstance(comment, dict) and SUMMARY_MARKER in str(comment.get("body", ""))),
            None,
        )
        if existing and existing.get("id"):
            self._request("PATCH", f"/repos/{self._repo_full_name}/issues/comments/{existing['id']}", json={"body": body})
            return
        self._request("POST", self._issue_comments_path(pull_number), json={"body": body})

    def create_inline_review(self, pull_number: int, commit_id: str, comments: list[dict[str, Any]], body: str) -> None:
        if not self._settings.create_inline_review or not comments:
            return
        payload = {
            "commit_id": commit_id,
            "body": body,
            "event": "COMMENT",
            "comments": comments,
        }
        self._request("POST", f"/repos/{self._repo_full_name}/pulls/{pull_number}/reviews", json=payload)

    def get_pull_request(self, pull_number: int) -> dict[str, Any]:
        response = self._request("GET", f"/repos/{self._repo_full_name}/pulls/{pull_number}")
        if not isinstance(response, dict):
            raise GitHubAPIError("Unexpected response when fetching pull request details.")
        return response

    def create_check_run(
        self,
        *,
        name: str,
        head_sha: str,
        status: str,
        external_id: str | None = None,
        started_at: str | None = None,
        details_url: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        if external_id:
            payload["external_id"] = external_id
        if started_at:
            payload["started_at"] = started_at
        if details_url:
            payload["details_url"] = details_url
        if output:
            payload["output"] = output
        response = self._request("POST", f"/repos/{self._repo_full_name}/check-runs", json=payload)
        if not isinstance(response, dict):
            raise GitHubAPIError("Unexpected response when creating a check run.")
        return response

    def update_check_run(
        self,
        *,
        check_run_id: int,
        status: str | None = None,
        conclusion: str | None = None,
        completed_at: str | None = None,
        details_url: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if status:
            payload["status"] = status
        if conclusion:
            payload["conclusion"] = conclusion
        if completed_at:
            payload["completed_at"] = completed_at
        if details_url:
            payload["details_url"] = details_url
        if output:
            payload["output"] = output
        response = self._request("PATCH", f"/repos/{self._repo_full_name}/check-runs/{check_run_id}", json=payload)
        if not isinstance(response, dict):
            raise GitHubAPIError("Unexpected response when updating a check run.")
        return response

    def _issue_comments_path(self, pull_number: int) -> str:
        return f"/repos/{self._repo_full_name}/issues/{pull_number}/comments"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._settings.retry_attempts + 1):
            try:
                response = self._client.request(method, path, **kwargs)
                if response.status_code in (429, 502, 503, 504):
                    raise GitHubAPIError(f"GitHub API transient error {response.status_code}: {response.text}")
                if response.status_code == 403 and "rate limit" in response.text.lower():
                    raise GitHubAPIError(f"GitHub API rate limited: {response.text}")
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
            except (httpx.HTTPError, GitHubAPIError) as exc:
                last_error = exc
                if attempt >= self._settings.retry_attempts:
                    break
                delay = min(2 ** (attempt - 1), 8)
                LOGGER.warning("GitHub API request failed (%s). Retrying in %ss.", exc, delay)
                time.sleep(delay)
        raise GitHubAPIError(f"GitHub API request failed after retries: {last_error}") from last_error
