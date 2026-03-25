from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .config import BotConfig
from .diff_parser import build_changed_line_map, build_review_chunks, filter_reviewable_patches, parse_unified_diff
from .domain import InlineComment, PullRequestContext, ReviewFinding, ReviewReport
from .formatter import build_summary_points
from .git_utils import build_unified_diff
from .llm_client import LLMClient
from .redaction import redact_chunks, redact_pull_request_context, redact_repository_snippets
from .repository_context import load_repository_snippets

LOGGER = logging.getLogger(__name__)


class ReviewAbortedError(RuntimeError):
    pass


def run_review(
    repo_root: Path,
    pr_context: PullRequestContext,
    config: BotConfig,
    *,
    head_revision: str,
    should_abort: Callable[[], bool] | None = None,
) -> ReviewReport:
    _raise_if_aborted(should_abort)
    raw_diff = build_unified_diff(
        repo_root=repo_root,
        base_revision=pr_context.base_sha,
        head_revision=head_revision,
        context_lines=config.diff.context_lines,
    )
    patches = parse_unified_diff(raw_diff)
    reviewable_patches, skipped_files = filter_reviewable_patches(patches, config.diff.ignore)
    if not reviewable_patches:
        summary_points = ["No reviewable source changes were found after applying ignore rules."]
        if skipped_files:
            summary_points.append(
                f"Skipped {len(skipped_files)} file(s) because they matched ignore rules or were binary."
            )
        return ReviewReport(
            summary_points=summary_points,
            analyzed_files=[],
            skipped_files=skipped_files,
            model_used=config.review.model,
            chunk_count=0,
        )

    chunks, omitted_sections = build_review_chunks(
        reviewable_patches,
        max_chunk_chars=config.review.max_chunk_chars,
        max_chunks=config.review.max_chunks,
    )
    repository_snippets = load_repository_snippets(repo_root, config.repository_context)
    safe_context, pr_redactions = redact_pull_request_context(pr_context, config.security)
    chunks, chunk_redactions = redact_chunks(chunks, config.security)
    repository_snippets, snippet_redactions = redact_repository_snippets(repository_snippets, config.security)
    redaction_count = pr_redactions + chunk_redactions + snippet_redactions
    _raise_if_aborted(should_abort)
    llm = LLMClient(config.review)

    summary_points: list[str] = []
    findings: list[ReviewFinding] = []
    inline_comments: list[InlineComment] = []
    suggested_tests: list[str] = []
    models_used: list[str] = []

    for chunk in chunks:
        _raise_if_aborted(should_abort)
        response, model_used = llm.review_chunk(safe_context, chunk, repository_snippets)
        _raise_if_aborted(should_abort)
        models_used.append(model_used)
        chunk_summary, chunk_findings, chunk_inline_comments, chunk_tests = response.to_domain()
        summary_points.extend(chunk_summary)
        findings.extend(chunk_findings)
        inline_comments.extend(chunk_inline_comments)
        suggested_tests.extend(chunk_tests)

    findings = _dedupe_findings(findings)[: config.review.max_issues]
    changed_line_map = build_changed_line_map(reviewable_patches)
    inline_comments = _filter_inline_comments(inline_comments, changed_line_map)[: config.review.max_inline_comments]
    suggested_tests = _dedupe_strings(suggested_tests)[:8]

    report = ReviewReport(
        summary_points=_compose_summary(
            findings=findings,
            analyzed_files=[patch.path for patch in reviewable_patches],
            skipped_files=skipped_files,
            chunk_count=len(chunks),
            omitted_sections=omitted_sections,
            chunk_summary_points=summary_points,
        ),
        findings=findings,
        inline_comments=inline_comments,
        suggested_tests=suggested_tests,
        analyzed_files=[patch.path for patch in reviewable_patches],
        skipped_files=skipped_files,
        provider_used=config.review.provider,
        model_used=", ".join(_dedupe_strings(models_used)),
        chunk_count=len(chunks),
        omitted_sections=omitted_sections,
        redaction_count=redaction_count,
    )
    return report


def _compose_summary(
    *,
    findings: list[ReviewFinding],
    analyzed_files: list[str],
    skipped_files: list[str],
    chunk_count: int,
    omitted_sections: int,
    chunk_summary_points: list[str],
) -> list[str]:
    temp_report = ReviewReport(
        summary_points=[],
        findings=findings,
        analyzed_files=analyzed_files,
        skipped_files=skipped_files,
        chunk_count=chunk_count,
        omitted_sections=omitted_sections,
    )
    summary = build_summary_points(temp_report)
    extras = _dedupe_strings(chunk_summary_points)
    for point in extras:
        if len(summary) >= 6:
            break
        if point not in summary:
            summary.append(point)
    return summary[:6]


def _dedupe_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    severity_rank = {"critical": 0, "warning": 1, "nitpick": 2}
    best_by_key: dict[tuple[str, str, int], ReviewFinding] = {}
    for finding in findings:
        key = (
            finding.title.casefold(),
            finding.file_path or "",
            finding.line or 0,
        )
        existing = best_by_key.get(key)
        if existing is None or severity_rank[finding.severity] < severity_rank[existing.severity]:
            best_by_key[key] = finding
    return sorted(
        best_by_key.values(),
        key=lambda item: (severity_rank[item.severity], item.file_path or "", item.line or 0, item.title.casefold()),
    )


def _filter_inline_comments(
    comments: list[InlineComment],
    changed_line_map: dict[str, set[int]],
) -> list[InlineComment]:
    best_by_key: dict[tuple[str, int], InlineComment] = {}
    severity_rank = {"critical": 0, "warning": 1, "nitpick": 2}
    for comment in comments:
        changed_lines = changed_line_map.get(comment.file_path)
        if not changed_lines or comment.line not in changed_lines:
            continue
        key = (comment.file_path, comment.line)
        existing = best_by_key.get(key)
        if existing is None or severity_rank[comment.severity] < severity_rank[existing.severity]:
            best_by_key[key] = comment
    return sorted(best_by_key.values(), key=lambda item: (severity_rank[item.severity], item.file_path, item.line))


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _raise_if_aborted(should_abort: Callable[[], bool] | None) -> None:
    if should_abort and should_abort():
        raise ReviewAbortedError("Review aborted because a newer pull request head superseded this job.")
