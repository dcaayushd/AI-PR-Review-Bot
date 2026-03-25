from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .git_utils import resolve_revision, run_git


@dataclass(slots=True)
class RepoCheckout:
    path: Path
    head_revision: str
    resolved_head_sha: str

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class RepositoryCheckoutError(RuntimeError):
    pass


def build_authenticated_repo_url(repo_full_name: str, token: str) -> str:
    encoded_token = quote(token, safe="")
    return f"https://x-access-token:{encoded_token}@github.com/{repo_full_name}.git"


def _has_merge_base(repo_root: Path, left_revision: str, right_revision: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", left_revision, right_revision],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _ensure_merge_base(
    *,
    checkout_dir: Path,
    pull_number: int,
    base_sha: str,
    base_ref: str,
    head_revision: str,
    fetch_depth: int,
    fetch_timeout_seconds: int,
) -> None:
    if _has_merge_base(checkout_dir, base_sha, head_revision):
        return

    base_tracking_ref = f"refs/remotes/origin/base/{base_ref}"
    depth = max(fetch_depth, 32)
    max_depth = 4096

    while depth <= max_depth:
        run_git(
            checkout_dir,
            ["fetch", "--no-tags", f"--depth={depth}", "origin", f"refs/heads/{base_ref}:{base_tracking_ref}"],
            timeout_seconds=fetch_timeout_seconds,
        )
        run_git(
            checkout_dir,
            ["fetch", "--no-tags", f"--depth={depth}", "origin", f"pull/{pull_number}/head:{head_revision}"],
            timeout_seconds=fetch_timeout_seconds,
        )
        if _has_merge_base(checkout_dir, base_sha, head_revision):
            return
        depth *= 2

    run_git(
        checkout_dir,
        ["fetch", "--no-tags", "origin", f"refs/heads/{base_ref}:{base_tracking_ref}"],
        timeout_seconds=fetch_timeout_seconds,
    )
    run_git(
        checkout_dir,
        ["fetch", "--no-tags", "origin", f"pull/{pull_number}/head:{head_revision}"],
        timeout_seconds=fetch_timeout_seconds,
    )
    if _has_merge_base(checkout_dir, base_sha, head_revision):
        return

    raise RepositoryCheckoutError(
        "Unable to compute a merge base for the pull request diff after deepening fetch history."
    )


def checkout_pull_request(
    *,
    repo_full_name: str,
    pull_number: int,
    base_sha: str,
    base_ref: str,
    token: str,
    workspace_root: Path,
    fetch_depth: int,
    fetch_timeout_seconds: int,
) -> RepoCheckout:
    repo_url = build_authenticated_repo_url(repo_full_name, token)
    checkout_dir = Path(tempfile.mkdtemp(prefix="review-", dir=workspace_root))
    head_revision = f"refs/remotes/origin/pr/{pull_number}"
    try:
        run_git(checkout_dir, ["init"])
        run_git(checkout_dir, ["remote", "add", "origin", repo_url])
        run_git(
            checkout_dir,
            ["fetch", "--no-tags", f"--depth={fetch_depth}", "origin", base_sha],
            timeout_seconds=fetch_timeout_seconds,
        )
        run_git(
            checkout_dir,
            ["fetch", "--no-tags", f"--depth={fetch_depth}", "origin", f"pull/{pull_number}/head:{head_revision}"],
            timeout_seconds=fetch_timeout_seconds,
        )
        _ensure_merge_base(
            checkout_dir=checkout_dir,
            pull_number=pull_number,
            base_sha=base_sha,
            base_ref=base_ref,
            head_revision=head_revision,
            fetch_depth=fetch_depth,
            fetch_timeout_seconds=fetch_timeout_seconds,
        )
        run_git(checkout_dir, ["checkout", "--detach", head_revision], timeout_seconds=fetch_timeout_seconds)
        resolved_head_sha = resolve_revision(checkout_dir, head_revision)
        return RepoCheckout(path=checkout_dir, head_revision=head_revision, resolved_head_sha=resolved_head_sha)
    except Exception as exc:
        shutil.rmtree(checkout_dir, ignore_errors=True)
        message = str(exc)
        if "Authentication failed" in message or "invalid credentials" in message.lower():
            message = (
                "Authentication failed while fetching the repository. "
                "Verify the GitHub App is installed on this repository and has Contents: Read-only permission."
            )
        raise RepositoryCheckoutError(f"Unable to prepare repository checkout: {message}") from exc
