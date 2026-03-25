from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Severity = Literal["critical", "warning", "nitpick"]
Category = Literal[
    "correctness",
    "security",
    "performance",
    "testing",
    "maintainability",
    "api",
    "devex",
]


@dataclass(slots=True)
class PullRequestContext:
    owner: str
    repo: str
    pull_number: int
    title: str
    body: str
    base_sha: str
    head_sha: str
    html_url: str = ""
    author: str = ""
    base_ref: str = ""
    head_ref: str = ""

    @property
    def repo_full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(slots=True)
class ReviewFinding:
    title: str
    severity: Severity
    category: Category
    why_it_matters: str
    suggested_fix: str
    file_path: str | None = None
    line: int | None = None
    code_snippet: str | None = None


@dataclass(slots=True)
class InlineComment:
    file_path: str
    line: int
    severity: Severity
    title: str
    body: str


@dataclass(slots=True)
class RepositorySnippet:
    path: str
    content: str


@dataclass(slots=True)
class DiffChunk:
    chunk_id: int
    text: str
    files: list[str]


@dataclass(slots=True)
class ReviewReport:
    summary_points: list[str] = field(default_factory=list)
    findings: list[ReviewFinding] = field(default_factory=list)
    inline_comments: list[InlineComment] = field(default_factory=list)
    suggested_tests: list[str] = field(default_factory=list)
    analyzed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    model_used: str = ""
    chunk_count: int = 0
    omitted_sections: int = 0

