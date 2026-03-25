from __future__ import annotations

from collections import Counter

from .domain import InlineComment, PullRequestContext, ReviewFinding, ReviewReport
from .utils import language_for_path, truncate_text

SUMMARY_MARKER = "<!-- ai-pr-review:summary -->"

SEVERITY_ORDER = {"critical": 0, "warning": 1, "nitpick": 2}
SEVERITY_LABEL = {"critical": "Critical", "warning": "Warning", "nitpick": "Nitpick"}


def build_summary_points(report: ReviewReport) -> list[str]:
    severities = Counter(finding.severity for finding in report.findings)
    categories = Counter(finding.category for finding in report.findings)
    summary: list[str] = [
        f"Analyzed {len(report.analyzed_files)} reviewable files across {report.chunk_count} diff chunk(s).",
    ]
    if severities["critical"]:
        summary.append(
            f"Risk level is high: found {severities['critical']} critical issue(s) that should be fixed before merge."
        )
    elif severities["warning"]:
        summary.append(
            f"No critical issues found, but there are {severities['warning']} important improvement(s) to address."
        )
    else:
        summary.append("No critical issues found in the reviewed diff.")

    if categories:
        top_categories = ", ".join(name for name, _ in categories.most_common(3))
        summary.append(f"Most findings cluster around: {top_categories}.")
    if report.omitted_sections:
        summary.append(
            f"Omitted {report.omitted_sections} diff section(s) because the review hit the configured chunk cap."
        )
    if report.skipped_files:
        summary.append(f"Skipped {len(report.skipped_files)} file(s) due to ignore rules or binary content.")
    return summary[:6]


def format_summary_comment(report: ReviewReport, pr_context: PullRequestContext) -> str:
    summary_points = report.summary_points or build_summary_points(report)
    critical = [finding for finding in report.findings if finding.severity == "critical"]
    improvements = [finding for finding in report.findings if finding.severity == "warning"]
    nitpicks = [finding for finding in report.findings if finding.severity == "nitpick"]

    lines = [
        SUMMARY_MARKER,
        f"## AI PR Review for `{pr_context.head_sha[:12]}`",
        "",
        "### 1. Summary",
    ]
    lines.extend(f"- {point}" for point in summary_points[:6])
    lines.append("")
    lines.append("### 2. Critical Issues (must fix)")
    if critical:
        for finding in critical:
            lines.extend(_render_finding_block(finding, pr_context))
    else:
        lines.append("No critical issues found.")
    lines.append("")
    lines.append("### 3. Improvements (should fix)")
    if improvements:
        for finding in improvements:
            lines.extend(_render_finding_block(finding, pr_context))
    else:
        lines.append("No improvements flagged.")
    lines.append("")
    lines.append("### 4. Nitpicks (optional)")
    if nitpicks:
        for finding in nitpicks:
            lines.extend(_render_finding_block(finding, pr_context))
    else:
        lines.append("- None.")
    lines.append("")
    lines.append("### 5. Suggested Tests")
    if report.suggested_tests:
        lines.extend(f"- {test_case}" for test_case in report.suggested_tests)
    else:
        lines.append("- Add regression tests covering the modified execution paths and error cases.")
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>Review metadata</summary>")
    lines.append("")
    lines.append(f"- Model(s): `{report.model_used or 'unknown'}`")
    lines.append(f"- Reviewable files: `{len(report.analyzed_files)}`")
    lines.append(f"- Inline comments prepared: `{len(report.inline_comments)}`")
    if report.skipped_files:
        lines.append(f"- Skipped files: `{', '.join(report.skipped_files[:10])}`")
    lines.append("</details>")
    return "\n".join(lines).strip()


def format_inline_comment(comment: InlineComment) -> str:
    severity = SEVERITY_LABEL[comment.severity]
    body = truncate_text(comment.body, 700)
    return f"**[{severity}] {comment.title}**\n\n{body}"


def _render_finding_block(finding: ReviewFinding, pr_context: PullRequestContext) -> list[str]:
    location = _format_location(finding, pr_context)
    lines = [f"- **{finding.title}**{location}"]
    lines.append(f"  **Why it matters**: {truncate_text(finding.why_it_matters, 700)}")
    lines.append(f"  **Suggested fix**: {truncate_text(finding.suggested_fix, 900)}")
    if finding.code_snippet:
        info = language_for_path(finding.file_path or "")
        snippet = truncate_text(finding.code_snippet.strip(), 700)
        lines.append(f"  ```{info}")
        lines.append(snippet)
        lines.append("  ```")
    return lines


def _format_location(finding: ReviewFinding, pr_context: PullRequestContext) -> str:
    if not finding.file_path:
        return ""
    if finding.line:
        url = f"https://github.com/{pr_context.repo_full_name}/blob/{pr_context.head_sha}/{finding.file_path}#L{finding.line}"
        return f" ([`{finding.file_path}:{finding.line}`]({url}))"
    url = f"https://github.com/{pr_context.repo_full_name}/blob/{pr_context.head_sha}/{finding.file_path}"
    return f" ([`{finding.file_path}`]({url}))"

