from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def load_dotenv_file(path: str | Path = ".env") -> None:
    dotenv_path = Path(path).expanduser()
    if not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _load_private_key_from_env() -> str:
    value = os.getenv("GITHUB_APP_PRIVATE_KEY", "").strip()
    if value:
        return value.replace("\\n", "\n")

    path_value = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
    if path_value:
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise ValueError(
                f"GITHUB_APP_PRIVATE_KEY_PATH points to a missing file: {path}. "
                "Download the private key from your GitHub App settings or set GITHUB_APP_PRIVATE_KEY directly."
            )
        return path.read_text(encoding="utf-8")
    return ""


@dataclass(slots=True)
class AppSettings:
    github_app_id: str
    github_private_key: str
    github_webhook_secret: str
    database_url: str
    workspace_root: Path
    host: str
    port: int
    max_parallel_reviews: int
    max_pending_reviews: int
    max_repo_active_reviews: int
    cancel_superseded_reviews: bool
    git_fetch_timeout_seconds: int
    git_fetch_depth: int
    github_api_url: str
    github_api_version: str
    public_base_url: str
    log_level: str

    @classmethod
    def from_env(cls) -> "AppSettings":
        load_dotenv_file()
        github_app_id = os.getenv("GITHUB_APP_ID", "").strip()
        github_private_key = _load_private_key_from_env()
        github_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
        if not github_app_id:
            raise ValueError("GITHUB_APP_ID is required.")
        if not github_private_key:
            raise ValueError("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH is required.")
        if not github_webhook_secret:
            raise ValueError("GITHUB_WEBHOOK_SECRET is required.")

        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "./runtime/workspaces")).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)

        return cls(
            github_app_id=github_app_id,
            github_private_key=github_private_key,
            github_webhook_secret=github_webhook_secret,
            database_url=os.getenv("DATABASE_URL", "sqlite:///./runtime/reviews.db"),
            workspace_root=workspace_root,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            max_parallel_reviews=max(1, int(os.getenv("MAX_PARALLEL_REVIEWS", "4"))),
            max_pending_reviews=max(1, int(os.getenv("MAX_PENDING_REVIEWS", "32"))),
            max_repo_active_reviews=max(1, int(os.getenv("MAX_REPO_ACTIVE_REVIEWS", "6"))),
            cancel_superseded_reviews=_env_bool("CANCEL_SUPERSEDED_REVIEWS", True),
            git_fetch_timeout_seconds=max(30, int(os.getenv("GIT_FETCH_TIMEOUT_SECONDS", "180"))),
            git_fetch_depth=max(1, int(os.getenv("GIT_FETCH_DEPTH", "1"))),
            github_api_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            github_api_version=os.getenv("GITHUB_API_VERSION", "2026-03-10"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
