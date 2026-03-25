from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .domain import InlineComment, ReviewFinding
from .utils import normalize_path


class ReviewFindingModel(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    severity: str = Field(pattern="^(critical|warning|nitpick)$")
    category: str = Field(pattern="^(correctness|security|performance|testing|maintainability|api|devex)$")
    why_it_matters: str = Field(min_length=8, max_length=1200)
    suggested_fix: str = Field(min_length=8, max_length=1600)
    file_path: str | None = Field(default=None, max_length=500)
    line: int | None = Field(default=None, ge=1)
    code_snippet: str | None = Field(default=None, max_length=1200)

    @field_validator("title", "why_it_matters", "suggested_fix", "file_path", "code_snippet", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    def to_domain(self) -> ReviewFinding:
        return ReviewFinding(
            title=self.title,
            severity=self.severity,  # type: ignore[arg-type]
            category=self.category,  # type: ignore[arg-type]
            why_it_matters=self.why_it_matters,
            suggested_fix=self.suggested_fix,
            file_path=normalize_path(self.file_path) if self.file_path else None,
            line=self.line,
            code_snippet=self.code_snippet,
        )


class InlineCommentModel(BaseModel):
    file_path: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)
    severity: str = Field(pattern="^(critical|warning|nitpick)$")
    title: str = Field(min_length=3, max_length=180)
    body: str = Field(min_length=8, max_length=900)

    @field_validator("file_path", "title", "body", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    def to_domain(self) -> InlineComment:
        return InlineComment(
            file_path=normalize_path(self.file_path),
            line=self.line,
            severity=self.severity,  # type: ignore[arg-type]
            title=self.title,
            body=self.body,
        )


class ChunkReviewResponseModel(BaseModel):
    summary_points: list[str] = Field(default_factory=list, max_length=4)
    findings: list[ReviewFindingModel] = Field(default_factory=list, max_length=12)
    inline_comments: list[InlineCommentModel] = Field(default_factory=list, max_length=6)
    suggested_tests: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("summary_points", "suggested_tests", mode="before")
    @classmethod
    def normalize_list(cls, value: object) -> object:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def to_domain(self) -> tuple[list[str], list[ReviewFinding], list[InlineComment], list[str]]:
        return (
            self.summary_points,
            [finding.to_domain() for finding in self.findings],
            [comment.to_domain() for comment in self.inline_comments],
            self.suggested_tests,
        )

