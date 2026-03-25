from __future__ import annotations

import json
import os
from pathlib import Path

from .domain import PullRequestContext


def load_pr_context_from_payload(
    payload: dict[str, object],
    *,
    base_sha_override: str | None = None,
    head_sha_override: str | None = None,
) -> PullRequestContext:
    pull_request = payload.get("pull_request") if isinstance(payload, dict) else None
    pull_request = pull_request if isinstance(pull_request, dict) else {}
    repository = payload.get("repository") if isinstance(payload, dict) else None
    repository = repository if isinstance(repository, dict) else {}

    full_name = repository.get("full_name") or os.getenv("GITHUB_REPOSITORY", "")
    if not full_name or "/" not in full_name:
        raise ValueError("Unable to resolve repository full name from event payload or GITHUB_REPOSITORY.")
    owner, repo = str(full_name).split("/", 1)

    base = pull_request.get("base") if isinstance(pull_request, dict) else None
    base = base if isinstance(base, dict) else {}
    head = pull_request.get("head") if isinstance(pull_request, dict) else None
    head = head if isinstance(head, dict) else {}

    base_sha = base_sha_override or str(base.get("sha") or os.getenv("BASE_SHA", "")).strip()
    head_sha = head_sha_override or str(head.get("sha") or os.getenv("HEAD_SHA", "")).strip()
    if not base_sha or not head_sha:
        raise ValueError("Both base SHA and head SHA are required to review a pull request.")

    number = pull_request.get("number") or payload.get("number") or os.getenv("PR_NUMBER")
    if not number:
        raise ValueError("Unable to resolve pull request number from event payload or PR_NUMBER.")

    user = pull_request.get("user") if isinstance(pull_request, dict) else None
    user = user if isinstance(user, dict) else {}

    return PullRequestContext(
        owner=owner,
        repo=repo,
        pull_number=int(number),
        title=str(pull_request.get("title") or os.getenv("PR_TITLE", "Untitled PR")),
        body=str(pull_request.get("body") or os.getenv("PR_BODY", "")),
        base_sha=base_sha,
        head_sha=head_sha,
        html_url=str(pull_request.get("html_url") or ""),
        author=str(user.get("login") or ""),
        base_ref=str(base.get("ref") or ""),
        head_ref=str(head.get("ref") or ""),
    )


def load_pr_context(
    event_path: Path | None,
    *,
    base_sha_override: str | None = None,
    head_sha_override: str | None = None,
) -> PullRequestContext:
    payload: dict[str, object] = {}
    if event_path and event_path.exists():
        payload = json.loads(event_path.read_text(encoding="utf-8"))
    return load_pr_context_from_payload(
        payload,
        base_sha_override=base_sha_override,
        head_sha_override=head_sha_override,
    )
