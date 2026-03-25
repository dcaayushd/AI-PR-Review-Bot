from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .context import load_pr_context
from .formatter import format_inline_comment, format_summary_comment
from .github_api import GitHubClient
from .reviewer import run_review
from .runtime import load_dotenv_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-powered GitHub pull request review bot")
    parser.add_argument("--repo-root", default=".", help="Repository root that contains the git checkout")
    parser.add_argument("--event-path", default="", help="Path to the GitHub event JSON file")
    parser.add_argument("--config", default="", help="Optional path to .ai-review.yml")
    parser.add_argument("--base-sha", default="", help="Override the PR base SHA")
    parser.add_argument("--head-sha", default="", help="Override the PR head SHA")
    parser.add_argument(
        "--head-ref",
        default="",
        help="Optional git revision to diff against the base SHA. Useful for trusted workflows fetching PR refs.",
    )
    parser.add_argument("--skip-github-post", action="store_true", help="Do not post results back to GitHub")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    load_dotenv_file()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    repo_root = Path(args.repo_root).resolve()
    config_path = Path(args.config).resolve() if args.config else None
    event_path = Path(args.event_path).resolve() if args.event_path else None
    config = load_config(repo_root, config_path, allow_repo_github_settings=True)
    pr_context = load_pr_context(
        event_path,
        base_sha_override=args.base_sha or None,
        head_sha_override=args.head_sha or None,
    )

    review_head_revision = args.head_ref or pr_context.head_sha
    report = run_review(repo_root, pr_context, config, head_revision=review_head_revision)

    summary_comment = format_summary_comment(report, pr_context)
    logging.info("Review completed. Findings=%s InlineComments=%s", len(report.findings), len(report.inline_comments))
    print(summary_comment)

    if args.skip_github_post:
        return 0

    github = GitHubClient.from_env(pr_context.repo_full_name, config.github)
    try:
        github.upsert_summary_comment(pr_context.pull_number, summary_comment)
        inline_payload = [
            {
                "path": comment.file_path,
                "line": comment.line,
                "side": "RIGHT",
                "body": format_inline_comment(comment),
            }
            for comment in report.inline_comments
        ]
        github.create_inline_review(
            pull_number=pr_context.pull_number,
            commit_id=pr_context.head_sha,
            comments=inline_payload,
            body=f"Inline AI review for `{pr_context.head_sha[:12]}`.",
        )
    finally:
        github.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
