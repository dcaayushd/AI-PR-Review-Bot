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
    check_run_id: int | None = None
    error_message: str = ""
    summary_points_json: str = "[]"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary_points"] = json.loads(self.summary_points_json or "[]")
        payload.pop("summary_points_json", None)
        return payload


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
                    check_run_id INTEGER,
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
            self._ensure_column(connection, "check_run_id", "INTEGER")

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
                    model_used, provider, chunk_count, omitted_sections, redaction_count, check_run_id,
                    error_message, summary_points_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    job.check_run_id,
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

    def metrics_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = {
                row["status"]: row["count"]
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM review_jobs GROUP BY status"
                ).fetchall()
            }
            totals = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_jobs,
                    SUM(findings_count) AS total_findings,
                    SUM(inline_comments_count) AS total_inline_comments,
                    SUM(redaction_count) AS total_redactions
                FROM review_jobs
                """
            ).fetchone()
        return {
            "counts_by_status": counts,
            "total_jobs": int(totals["total_jobs"] or 0),
            "total_findings": int(totals["total_findings"] or 0),
            "total_inline_comments": int(totals["total_inline_comments"] or 0),
            "total_redactions": int(totals["total_redactions"] or 0),
        }

    def mark_running(self, job_id: str) -> None:
        now = _utc_now()
        self._update_status(job_id, "running", started_at=now, updated_at=now)

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
            summary_points_json=json.dumps(report.summary_points),
            error_message="",
        )

    def mark_skipped(self, job_id: str, reason: str) -> None:
        now = _utc_now()
        self._update_status(job_id, "skipped", updated_at=now, completed_at=now, error_message=reason)

    def mark_failed(self, job_id: str, error_message: str) -> None:
        now = _utc_now()
        self._update_status(job_id, "failed", updated_at=now, completed_at=now, error_message=error_message)

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
        check_run_id=row["check_run_id"],
        error_message=row["error_message"],
        summary_points_json=row["summary_points_json"],
    )
