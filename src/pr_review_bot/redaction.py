from __future__ import annotations

import re
from dataclasses import replace
from typing import Pattern

from .config import SecuritySettings
from .domain import DiffChunk, PullRequestContext, RepositorySnippet


ASSIGNMENT_RE = re.compile(
    r"(?im)\b(api[_-]?key|secret|token|password|passwd|pwd|private[_-]?key|client[_-]?secret)"
    r"(\s*[:=]\s*['\"]?)([^'\"\s]+)(['\"]?)"
)


def compile_redaction_patterns(settings: SecuritySettings) -> list[Pattern[str]]:
    return [re.compile(pattern, re.MULTILINE) for pattern in settings.secret_patterns]


def redact_pull_request_context(context: PullRequestContext, settings: SecuritySettings) -> tuple[PullRequestContext, int]:
    title, title_count = redact_text(context.title, settings)
    body, body_count = redact_text(context.body, settings)
    return replace(context, title=title, body=body), title_count + body_count


def redact_chunks(chunks: list[DiffChunk], settings: SecuritySettings) -> tuple[list[DiffChunk], int]:
    total = 0
    redacted_chunks: list[DiffChunk] = []
    for chunk in chunks:
        redacted_text, count = redact_text(chunk.text, settings)
        total += count
        redacted_chunks.append(DiffChunk(chunk_id=chunk.chunk_id, text=redacted_text, files=list(chunk.files)))
    return redacted_chunks, total


def redact_repository_snippets(
    snippets: list[RepositorySnippet],
    settings: SecuritySettings,
) -> tuple[list[RepositorySnippet], int]:
    total = 0
    redacted_snippets: list[RepositorySnippet] = []
    for snippet in snippets:
        redacted_text, count = redact_text(snippet.content, settings)
        total += count
        redacted_snippets.append(RepositorySnippet(path=snippet.path, content=redacted_text))
    return redacted_snippets, total


def redact_text(text: str, settings: SecuritySettings) -> tuple[str, int]:
    if not settings.redact_secrets or not text:
        return text, 0

    redaction_count = 0
    result = text
    for pattern in compile_redaction_patterns(settings):
        result, matches = pattern.subn(settings.redaction_placeholder, result)
        redaction_count += matches

    result, matches = ASSIGNMENT_RE.subn(_assignment_replacer(settings.redaction_placeholder), result)
    redaction_count += matches
    return result, redaction_count


def _assignment_replacer(placeholder: str):
    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{placeholder}{match.group(4)}"

    return _replace

