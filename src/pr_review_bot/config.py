from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


DEFAULT_IGNORE_PATTERNS = [
    "**/.git/**",
    "**/.next/**",
    "**/__pycache__/**",
    "**/coverage/**",
    "**/dist/**",
    "**/build/**",
    "**/node_modules/**",
    "**/*.lock",
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
    "**/*.pdf",
]

DEFAULT_CONTEXT_FILES = [
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements*.txt",
    ".github/workflows/*.yml",
]


@dataclass(slots=True)
class ReviewSettings:
    provider: str = "openai"
    model: str = "gpt-5.4"
    fallback_model: str = "gpt-5-mini"
    reasoning_effort: str = "medium"
    temperature: float = 0.15
    max_output_tokens: int = 3500
    max_issues: int = 18
    max_inline_comments: int = 8
    max_chunk_chars: int = 18000
    max_chunks: int = 12
    retry_attempts: int = 3


@dataclass(slots=True)
class DiffSettings:
    context_lines: int = 3
    ignore: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))


@dataclass(slots=True)
class GitHubSettings:
    api_url: str = "https://api.github.com"
    api_version: str = "2026-03-10"
    update_summary_comment: bool = True
    create_inline_review: bool = True
    request_timeout_seconds: int = 30
    retry_attempts: int = 3


@dataclass(slots=True)
class RepositoryContextSettings:
    enabled: bool = True
    max_files: int = 6
    max_chars_per_file: int = 3000
    include: list[str] = field(default_factory=lambda: list(DEFAULT_CONTEXT_FILES))


@dataclass(slots=True)
class BotConfig:
    review: ReviewSettings = field(default_factory=ReviewSettings)
    diff: DiffSettings = field(default_factory=DiffSettings)
    github: GitHubSettings = field(default_factory=GitHubSettings)
    repository_context: RepositoryContextSettings = field(default_factory=RepositoryContextSettings)


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _default_provider() -> str:
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("GOOGLE_API_KEY", "").strip() and not os.getenv("OPENAI_API_KEY", "").strip():
        return "gemini"
    return "openai"


def load_config(
    repo_root: Path,
    explicit_path: Path | None = None,
    *,
    allow_repo_github_settings: bool = False,
) -> BotConfig:
    path = explicit_path or repo_root / ".ai-review.yml"
    payload: dict[str, object] = {}
    if path.exists():
        payload = _as_dict(yaml.safe_load(path.read_text(encoding="utf-8")))

    review_data = _as_dict(payload.get("review"))
    diff_data = _as_dict(payload.get("diff"))
    github_data = _as_dict(payload.get("github")) if allow_repo_github_settings else {}
    repository_context_data = _as_dict(payload.get("repository_context"))
    provider = str(review_data.get("provider", _default_provider())).strip().lower()
    default_model = "gemini-2.5-flash" if provider == "gemini" else "gpt-5.4"
    default_fallback_model = "gemini-2.5-flash-lite" if provider == "gemini" else "gpt-5-mini"
    model_env = os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "")).strip()
    fallback_model_env = os.getenv("LLM_FALLBACK_MODEL", os.getenv("OPENAI_FALLBACK_MODEL", "")).strip()
    temperature_env = os.getenv("LLM_TEMPERATURE", os.getenv("OPENAI_TEMPERATURE", "")).strip()
    max_output_tokens_env = os.getenv("LLM_MAX_OUTPUT_TOKENS", os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "")).strip()

    config = BotConfig(
        review=ReviewSettings(
            provider=provider,
            model=str(model_env or review_data.get("model", default_model)),
            fallback_model=str(fallback_model_env or review_data.get("fallback_model", default_fallback_model)),
            reasoning_effort=str(review_data.get("reasoning_effort", "medium")),
            temperature=float(temperature_env or review_data.get("temperature", 0.15)),
            max_output_tokens=int(max_output_tokens_env or review_data.get("max_output_tokens", 3500)),
            max_issues=int(review_data.get("max_issues", 18)),
            max_inline_comments=int(review_data.get("max_inline_comments", 8)),
            max_chunk_chars=int(review_data.get("max_chunk_chars", 18000)),
            max_chunks=int(review_data.get("max_chunks", 12)),
            retry_attempts=int(review_data.get("retry_attempts", 3)),
        ),
        diff=DiffSettings(
            context_lines=int(diff_data.get("context_lines", 3)),
            ignore=list(diff_data.get("ignore", DEFAULT_IGNORE_PATTERNS)),
        ),
        github=GitHubSettings(
            api_url=str(github_data.get("api_url", "https://api.github.com")),
            api_version=str(github_data.get("api_version", "2026-03-10")),
            update_summary_comment=bool(github_data.get("update_summary_comment", True)),
            create_inline_review=bool(github_data.get("create_inline_review", True)),
            request_timeout_seconds=int(github_data.get("request_timeout_seconds", 30)),
            retry_attempts=int(github_data.get("retry_attempts", 3)),
        ),
        repository_context=RepositoryContextSettings(
            enabled=bool(repository_context_data.get("enabled", True)),
            max_files=int(repository_context_data.get("max_files", 6)),
            max_chars_per_file=int(repository_context_data.get("max_chars_per_file", 3000)),
            include=list(repository_context_data.get("include", DEFAULT_CONTEXT_FILES)),
        ),
    )
    return config
