from __future__ import annotations

import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    pass


def run_git(
    repo_root: Path,
    args: list[str],
    *,
    extra_configs: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    command = ["git"]
    for config in extra_configs or []:
        command.extend(["-c", config])
    command.extend(args)
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise GitCommandError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def build_unified_diff(repo_root: Path, base_revision: str, head_revision: str, context_lines: int) -> str:
    return run_git(
        repo_root,
        [
            "diff",
            f"--unified={context_lines}",
            "--find-renames",
            "--find-copies",
            "--no-color",
            f"{base_revision}...{head_revision}",
        ],
    )


def resolve_revision(repo_root: Path, revision: str) -> str:
    return run_git(repo_root, ["rev-parse", revision]).strip()
