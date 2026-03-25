from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .domain import ReviewReport
from .webhooks import ReviewRequest


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(slots=True)
class ReviewJob:
    job_id: str
    delivery_id: str
    event_name: str
    action: str
    installation_id: int
    repo_full_name: str
    pull_number: int
    base_sha: str
    head_sha: str
    status: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    findings_count: int = 0
    inline_comments_count: int = 0
    analyzed_files_count: int = 0
    model_used: str = ""
    provider: str = ""
    chunk_count: int = 0
    omitted_sections: int = 0
    redaction_count: int = 0
    risk_level: str = "medium"
    risk_score: int = 0
    check_run_id: int | None = None
    superseded_by_head_sha: str = ""
    risk_reasons_json: str = "[]"
    findings_json: str = "[]"
    suggested_tests_json: str = "[]"
    analyzed_files_json: str = "[]"
    skipped_files_json: str = "[]"
    error_message: str = ""
    summary_points_json: str = "[]"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary_points"] = json.loads(self.summary_points_json or "[]")
        payload["findings"] = json.loads(self.findings_json or "[]")
        payload["suggested_tests"] = json.loads(self.suggested_tests_json or "[]")
        payload["analyzed_files"] = json.loads(self.analyzed_files_json or "[]")
        payload["skipped_files"] = json.loads(self.skipped_files_json or "[]")
        payload["risk_reasons"] = json.loads(self.risk_reasons_json or "[]")
        payload["duration_seconds"] = self.duration_seconds
        payload.pop("summary_points_json", None)
        payload.pop("risk_reasons_json", None)
        payload.pop("findings_json", None)
        payload.pop("suggested_tests_json", None)
        payload.pop("analyzed_files_json", None)
        payload.pop("skipped_files_json", None)
        return payload

    @property
    def duration_seconds(self) -> float | None:
        started = _parse_iso8601(self.started_at)
        completed = _parse_iso8601(self.completed_at)
        if started is None or completed is None:
            return None
        return max((completed - started).total_seconds(), 0.0)


class ReviewJobStore:
    def __init__(self, database_url: str) -> None:
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL values are currently supported.")
        path_value = database_url.removeprefix("sqlite:///")
        self._db_path = Path(path_value).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_jobs (
                    job_id TEXT PRIMARY KEY,
                    delivery_id TEXT UNIQUE NOT NULL,
                    event_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    installation_id INTEGER NOT NULL,
                    repo_full_name TEXT NOT NULL,
                    pull_number INTEGER NOT NULL,
                    base_sha TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    findings_count INTEGER NOT NULL DEFAULT 0,
                    inline_comments_count INTEGER NOT NULL DEFAULT 0,
                    analyzed_files_count INTEGER NOT NULL DEFAULT 0,
                    model_used TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    omitted_sections INTEGER NOT NULL DEFAULT 0,
                    redaction_count INTEGER NOT NULL DEFAULT 0,
                    risk_level TEXT NOT NULL DEFAULT 'medium',
                    risk_score INTEGER NOT NULL DEFAULT 0,
                    check_run_id INTEGER,
                    superseded_by_head_sha TEXT NOT NULL DEFAULT '',
                    risk_reasons_json TEXT NOT NULL DEFAULT '[]',
                    findings_json TEXT NOT NULL DEFAULT '[]',
                    suggested_tests_json TEXT NOT NULL DEFAULT '[]',
                    analyzed_files_json TEXT NOT NULL DEFAULT '[]',
                    skipped_files_json TEXT NOT NULL DEFAULT '[]',
                    error_message TEXT NOT NULL DEFAULT '',
                    summary_points_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            self._ensure_column(connection, "analyzed_files_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "provider", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "chunk_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "omitted_sections", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "redaction_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "risk_level", "TEXT NOT NULL DEFAULT 'medium'")
            self._ensure_column(connection, "risk_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "check_run_id", "INTEGER")
            self._ensure_column(connection, "superseded_by_head_sha", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "risk_reasons_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "findings_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "suggested_tests_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "analyzed_files_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "skipped_files_json", "TEXT NOT NULL DEFAULT '[]'")

    def _ensure_column(self, connection: sqlite3.Connection, column_name: str, column_type: str) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(review_jobs)").fetchall()
        }
        if column_name in columns:
            return
        connection.execute(f"ALTER TABLE review_jobs ADD COLUMN {column_name} {column_type}")

    def create_or_get_job(self, request: ReviewRequest) -> tuple[ReviewJob, bool]:
        existing = self.get_job_by_delivery(request.delivery_id)
        if existing:
            return existing, False
        active = self.get_active_job_for_head(
            repo_full_name=request.pr_context.repo_full_name,
            pull_number=request.pr_context.pull_number,
            head_sha=request.pr_context.head_sha,
        )
        if active:
            return active, False

        now = _utc_now()
        job = ReviewJob(
            job_id=str(uuid.uuid4()),
            delivery_id=request.delivery_id,
            event_name=request.event_name,
            action=request.action,
            installation_id=request.installation_id,
            repo_full_name=request.pr_context.repo_full_name,
            pull_number=request.pr_context.pull_number,
            base_sha=request.pr_context.base_sha,
            head_sha=request.pr_context.head_sha,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO review_jobs (
                    job_id, delivery_id, event_name, action, installation_id, repo_full_name,
                    pull_number, base_sha, head_sha, status, created_at, updated_at,
                    started_at, completed_at, findings_count, inline_comments_count, analyzed_files_count,
                    model_used, provider, chunk_count, omitted_sections, redaction_count, risk_level, risk_score,
                    check_run_id, superseded_by_head_sha, risk_reasons_json, findings_json, suggested_tests_json,
                    analyzed_files_json, skipped_files_json, error_message, summary_points_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.delivery_id,
                    job.event_name,
                    job.action,
                    job.installation_id,
                    job.repo_full_name,
                    job.pull_number,
                    job.base_sha,
                    job.head_sha,
                    job.status,
                    job.created_at,
                    job.updated_at,
                    job.started_at,
                    job.completed_at,
                    job.findings_count,
                    job.inline_comments_count,
                    job.analyzed_files_count,
                    job.model_used,
                    job.provider,
                    job.chunk_count,
                    job.omitted_sections,
                    job.redaction_count,
                    job.risk_level,
                    job.risk_score,
                    job.check_run_id,
                    job.superseded_by_head_sha,
                    job.risk_reasons_json,
                    job.findings_json,
                    job.suggested_tests_json,
                    job.analyzed_files_json,
                    job.skipped_files_json,
                    job.error_message,
                    job.summary_points_json,
                ),
            )
        return job, True

    def get_job_by_delivery(self, delivery_id: str) -> ReviewJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM review_jobs WHERE delivery_id = ?", (delivery_id,)).fetchone()
        return _row_to_job(row) if row else None

    def get_job(self, job_id: str) -> ReviewJob | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM review_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def get_active_job_for_head(self, *, repo_full_name: str, pull_number: int, head_sha: str) -> ReviewJob | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM review_jobs
                WHERE repo_full_name = ? AND pull_number = ? AND head_sha = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (repo_full_name, pull_number, head_sha),
            ).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, limit: int = 20) -> list[ReviewJob]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM review_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def list_jobs_for_pull(self, *, repo_full_name: str, pull_number: int, limit: int = 20) -> list[ReviewJob]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM review_jobs
                WHERE repo_full_name = ? AND pull_number = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (repo_full_name, pull_number, max(1, min(limit, 200))),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def count_jobs(self, *, statuses: tuple[str, ...], repo_full_name: str | None = None) -> int:
        filtered_statuses = tuple(dict.fromkeys(statuses))
        if not filtered_statuses:
            return 0
        placeholders = ", ".join("?" for _ in filtered_statuses)
        query = f"SELECT COUNT(*) AS count FROM review_jobs WHERE status IN ({placeholders})"
        params: list[object] = list(filtered_statuses)
        if repo_full_name:
            query += " AND repo_full_name = ?"
            params.append(repo_full_name)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return int(row["count"] if row else 0)

    def metrics_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = {
                row["status"]: row["count"]
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM review_jobs GROUP BY status"
                ).fetchall()
            }
            risk_counts = {
                row["risk_level"]: row["count"]
                for row in connection.execute(
                    "SELECT risk_level, COUNT(*) AS count FROM review_jobs GROUP BY risk_level"
                ).fetchall()
            }
            totals = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_jobs,
                    SUM(findings_count) AS total_findings,
                    SUM(inline_comments_count) AS total_inline_comments,
                    SUM(redaction_count) AS total_redactions,
                    COUNT(DISTINCT repo_full_name) AS active_repositories,
                    AVG(
                        CASE
                            WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
                            THEN (julianday(completed_at) - julianday(started_at)) * 86400.0
                            ELSE NULL
                        END
                    ) AS avg_duration_seconds
                FROM review_jobs
                """
            ).fetchone()
            providers = {
                (row["provider"] or "unknown"): row["count"]
                for row in connection.execute(
                    """
                    SELECT COALESCE(NULLIF(provider, ''), 'unknown') AS provider, COUNT(*) AS count
                    FROM review_jobs
                    GROUP BY COALESCE(NULLIF(provider, ''), 'unknown')
                    """
                ).fetchall()
            }
            repositories = [
                {"repo_full_name": row["repo_full_name"], "job_count": int(row["job_count"])}
                for row in connection.execute(
                    """
                    SELECT repo_full_name, COUNT(*) AS job_count
                    FROM review_jobs
                    GROUP BY repo_full_name
                    ORDER BY job_count DESC, repo_full_name ASC
                    LIMIT 5
                    """
                ).fetchall()
            ]
        return {
            "counts_by_status": counts,
            "counts_by_provider": providers,
            "counts_by_risk": risk_counts,
            "total_jobs": int(totals["total_jobs"] or 0),
            "total_findings": int(totals["total_findings"] or 0),
            "total_inline_comments": int(totals["total_inline_comments"] or 0),
            "total_redactions": int(totals["total_redactions"] or 0),
            "active_repositories": int(totals["active_repositories"] or 0),
            "avg_duration_seconds": round(float(totals["avg_duration_seconds"] or 0.0), 2),
            "top_repositories": repositories,
        }

    def mark_running(self, job_id: str) -> None:
        now = _utc_now()
        self._update_status(job_id, "running", started_at=now, updated_at=now, superseded_by_head_sha="")

    def set_check_run_id(self, job_id: str, check_run_id: int) -> None:
        self._update_status(job_id, "running", updated_at=_utc_now(), check_run_id=check_run_id)

    def mark_completed(self, job_id: str, report: ReviewReport) -> None:
        now = _utc_now()
        self._update_status(
            job_id,
            "completed",
            updated_at=now,
            completed_at=now,
            findings_count=len(report.findings),
            inline_comments_count=len(report.inline_comments),
            analyzed_files_count=len(report.analyzed_files),
            model_used=report.model_used,
            provider=report.provider_used,
            chunk_count=report.chunk_count,
            omitted_sections=report.omitted_sections,
            redaction_count=report.redaction_count,
            risk_level=report.risk_level,
            risk_score=report.risk_score,
            superseded_by_head_sha="",
            risk_reasons_json=json.dumps(report.risk_reasons),
            findings_json=json.dumps([asdict(finding) for finding in report.findings]),
            suggested_tests_json=json.dumps(report.suggested_tests),
            analyzed_files_json=json.dumps(report.analyzed_files),
            skipped_files_json=json.dumps(report.skipped_files),
            summary_points_json=json.dumps(report.summary_points),
            error_message="",
        )

    def mark_skipped(self, job_id: str, reason: str) -> None:
        now = _utc_now()
        self._update_status(
            job_id,
            "skipped",
            updated_at=now,
            completed_at=now,
            superseded_by_head_sha="",
            risk_level="medium",
            risk_score=0,
            risk_reasons_json="[]",
            findings_json="[]",
            suggested_tests_json="[]",
            analyzed_files_json="[]",
            skipped_files_json="[]",
            error_message=reason,
        )

    def mark_rejected(self, job_id: str, reason: str) -> None:
        now = _utc_now()
        self._update_status(
            job_id,
            "rejected",
            updated_at=now,
            completed_at=now,
            superseded_by_head_sha="",
            risk_level="medium",
            risk_score=0,
            risk_reasons_json="[]",
            findings_json="[]",
            suggested_tests_json="[]",
            analyzed_files_json="[]",
            skipped_files_json="[]",
            error_message=reason,
        )

    def mark_superseded(self, job_id: str, *, reason: str, superseded_by_head_sha: str) -> None:
        now = _utc_now()
        self._update_status(
            job_id,
            "superseded",
            updated_at=now,
            completed_at=now,
            error_message=reason,
            superseded_by_head_sha=superseded_by_head_sha,
            risk_level="medium",
            risk_score=0,
            risk_reasons_json="[]",
            findings_json="[]",
            suggested_tests_json="[]",
            analyzed_files_json="[]",
            skipped_files_json="[]",
        )

    def mark_failed(self, job_id: str, error_message: str) -> None:
        now = _utc_now()
        self._update_status(
            job_id,
            "failed",
            updated_at=now,
            completed_at=now,
            superseded_by_head_sha="",
            risk_level="medium",
            risk_score=0,
            risk_reasons_json="[]",
            findings_json="[]",
            suggested_tests_json="[]",
            analyzed_files_json="[]",
            skipped_files_json="[]",
            error_message=error_message,
        )

    def supersede_pull_jobs(
        self,
        *,
        repo_full_name: str,
        pull_number: int,
        exclude_job_id: str,
        new_head_sha: str,
    ) -> list[ReviewJob]:
        now = _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM review_jobs
                WHERE repo_full_name = ?
                  AND pull_number = ?
                  AND job_id != ?
                  AND head_sha != ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                """,
                (repo_full_name, pull_number, exclude_job_id, new_head_sha),
            ).fetchall()
            if not rows:
                return []
            connection.execute(
                """
                UPDATE review_jobs
                SET status = 'superseded',
                    updated_at = ?,
                    completed_at = ?,
                    error_message = ?,
                    superseded_by_head_sha = ?,
                    risk_level = 'medium',
                    risk_score = 0,
                    risk_reasons_json = '[]',
                    findings_json = '[]',
                    suggested_tests_json = '[]',
                    analyzed_files_json = '[]',
                    skipped_files_json = '[]'
                WHERE repo_full_name = ?
                  AND pull_number = ?
                  AND job_id != ?
                  AND head_sha != ?
                  AND status IN ('queued', 'running')
                """,
                (
                    now,
                    now,
                    "Superseded because a newer commit was queued for this pull request.",
                    new_head_sha,
                    repo_full_name,
                    pull_number,
                    exclude_job_id,
                    new_head_sha,
                ),
            )
        return [_row_to_job(row) for row in rows]

    def _update_status(self, job_id: str, status: str, **fields: object) -> None:
        columns = ["status = ?"]
        values: list[object] = [status]
        for key, value in fields.items():
            columns.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        statement = f"UPDATE review_jobs SET {', '.join(columns)} WHERE job_id = ?"
        with self._connect() as connection:
            connection.execute(statement, values)


def _row_to_job(row: sqlite3.Row) -> ReviewJob:
    return ReviewJob(
        job_id=row["job_id"],
        delivery_id=row["delivery_id"],
        event_name=row["event_name"],
        action=row["action"],
        installation_id=row["installation_id"],
        repo_full_name=row["repo_full_name"],
        pull_number=row["pull_number"],
        base_sha=row["base_sha"],
        head_sha=row["head_sha"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        findings_count=row["findings_count"],
        inline_comments_count=row["inline_comments_count"],
        analyzed_files_count=row["analyzed_files_count"],
        model_used=row["model_used"],
        provider=row["provider"],
        chunk_count=row["chunk_count"],
        omitted_sections=row["omitted_sections"],
        redaction_count=row["redaction_count"],
        risk_level=row["risk_level"],
        risk_score=row["risk_score"],
        check_run_id=row["check_run_id"],
        superseded_by_head_sha=row["superseded_by_head_sha"],
        risk_reasons_json=row["risk_reasons_json"],
        findings_json=row["findings_json"],
        suggested_tests_json=row["suggested_tests_json"],
        analyzed_files_json=row["analyzed_files_json"],
        skipped_files_json=row["skipped_files_json"],
        error_message=row["error_message"],
        summary_points_json=row["summary_points_json"],
    )
