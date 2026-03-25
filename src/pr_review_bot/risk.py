from __future__ import annotations

from dataclasses import dataclass, replace

from .config import ReviewSettings, RoutingSettings
from .diff_parser import FilePatch


HIGH_RISK_KEYWORDS = (
    "auth",
    "permission",
    "token",
    "secret",
    "credential",
    "payment",
    "billing",
    "crypto",
    "jwt",
    "oauth",
)

INFRA_PATTERNS = (
    "dockerfile",
    ".github/workflows/",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements",
    ".tf",
    "k8s",
    "helm",
)

DATA_PATTERNS = (
    "migration",
    "schema",
    "sql",
    "database",
    "alembic",
)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    level: str
    score: int
    reasons: list[str]


def assess_review_risk(patches: list[FilePatch]) -> RiskAssessment:
    score = 0
    reasons: list[str] = []
    total_added_lines = sum(len(patch.added_lines) for patch in patches)
    file_count = len(patches)
    normalized_paths = [patch.path.lower() for patch in patches]

    if file_count >= 8:
        score += 2
        reasons.append(f"touches {file_count} reviewable files")
    elif file_count >= 4:
        score += 1
        reasons.append(f"touches {file_count} reviewable files")

    if total_added_lines >= 300:
        score += 3
        reasons.append(f"adds {total_added_lines} lines")
    elif total_added_lines >= 120:
        score += 2
        reasons.append(f"adds {total_added_lines} lines")
    elif total_added_lines >= 40:
        score += 1
        reasons.append(f"adds {total_added_lines} lines")

    if any(keyword in path for path in normalized_paths for keyword in HIGH_RISK_KEYWORDS):
        score += 4
        reasons.append("changes security-sensitive or auth-related paths")

    if any(pattern in path for path in normalized_paths for pattern in INFRA_PATTERNS):
        score += 3
        reasons.append("changes dependency or infrastructure files")

    if any(pattern in path for path in normalized_paths for pattern in DATA_PATTERNS):
        score += 3
        reasons.append("changes migrations, schemas, or database files")

    level = "high" if score >= 7 else "medium" if score >= 3 else "low"
    unique_reasons = list(dict.fromkeys(reasons))
    if not unique_reasons:
        unique_reasons.append("small, localized code change")
    return RiskAssessment(level=level, score=score, reasons=unique_reasons[:4])


def route_review_settings(
    base: ReviewSettings,
    routing: RoutingSettings,
    assessment: RiskAssessment,
) -> ReviewSettings:
    if not routing.enabled:
        return base

    if assessment.level == "low":
        low_risk_model = base.fallback_model if routing.use_fallback_for_low_risk and base.fallback_model else base.model
        return replace(
            base,
            model=low_risk_model,
            fallback_model=base.model if low_risk_model != base.model else base.fallback_model,
            reasoning_effort=routing.low_risk_reasoning_effort,
            max_issues=min(base.max_issues, 8),
            max_inline_comments=min(base.max_inline_comments, 4),
        )

    if assessment.level == "high":
        return replace(
            base,
            reasoning_effort=routing.high_risk_reasoning_effort,
            max_issues=max(base.max_issues, routing.high_risk_max_issues),
            max_inline_comments=max(base.max_inline_comments, routing.high_risk_max_inline_comments),
        )

    return replace(base, reasoning_effort=routing.medium_risk_reasoning_effort)
