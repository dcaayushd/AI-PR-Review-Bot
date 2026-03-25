from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .dashboard import render_dashboard_page, render_job_detail_page
from .review_service import ReviewService
from .runtime import AppSettings
from .storage import ReviewJobStore
from .webhooks import WebhookVerificationError, build_review_request, verify_github_webhook

LOGGER = logging.getLogger(__name__)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    runtime_settings = settings or AppSettings.from_env()
    logging.basicConfig(
        level=getattr(logging, runtime_settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    store = ReviewJobStore(runtime_settings.database_url)
    service = ReviewService(runtime_settings, store)

    app = FastAPI(
        title="AI PR Review",
        version="0.4.0",
        summary="GitHub App webhook service for AI pull request reviews",
    )
    app.state.settings = runtime_settings
    app.state.store = store
    app.state.service = service

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        service.close()

    @app.get("/healthz")
    async def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(
            render_dashboard_page(
                app_version=app.version,
                runtime_snapshot=service.runtime_snapshot(),
                metrics_summary=store.metrics_summary(),
                recent_jobs=store.list_jobs(limit=25),
            )
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_alias() -> HTMLResponse:
        return await dashboard()

    @app.get("/readyz")
    async def readiness() -> JSONResponse:
        snapshot = service.runtime_snapshot()
        status_code = 200 if snapshot["queue_accepting"] else 503
        return JSONResponse(
            {
                "status": "ready" if status_code == 200 else "degraded",
                **snapshot,
            },
            status_code=status_code,
        )

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job.as_dict()

    @app.get("/jobs/{job_id}/view", response_class=HTMLResponse)
    async def get_job_view(job_id: str) -> HTMLResponse:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return HTMLResponse(render_job_detail_page(app_version=app.version, job=job))

    @app.get("/jobs")
    async def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
        return [job.as_dict() for job in store.list_jobs(limit=limit)]

    @app.get("/repos/{owner}/{repo}/pulls/{pull_number}/jobs")
    async def list_pull_jobs(owner: str, repo: str, pull_number: int, limit: int = 20) -> list[dict[str, Any]]:
        return [
            job.as_dict()
            for job in store.list_jobs_for_pull(repo_full_name=f"{owner}/{repo}", pull_number=pull_number, limit=limit)
        ]

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        summary = store.metrics_summary()
        snapshot = service.runtime_snapshot()
        lines = [
            f'ai_pr_review_total_jobs {summary["total_jobs"]}',
            f'ai_pr_review_total_findings {summary["total_findings"]}',
            f'ai_pr_review_total_inline_comments {summary["total_inline_comments"]}',
            f'ai_pr_review_total_redactions {summary["total_redactions"]}',
            f'ai_pr_review_active_repositories {summary["active_repositories"]}',
            f'ai_pr_review_avg_duration_seconds {summary["avg_duration_seconds"]}',
            f'ai_pr_review_running_jobs {snapshot["running_jobs"]}',
            f'ai_pr_review_queued_jobs {snapshot["queued_jobs"]}',
            f'ai_pr_review_max_parallel_reviews {snapshot["max_parallel_reviews"]}',
            f'ai_pr_review_max_pending_reviews {snapshot["max_pending_reviews"]}',
            f'ai_pr_review_max_repo_active_reviews {snapshot["max_repo_active_reviews"]}',
            f'ai_pr_review_queue_accepting {1 if snapshot["queue_accepting"] else 0}',
        ]
        for status, count in sorted(summary["counts_by_status"].items()):
            lines.append(f'ai_pr_review_jobs_status{{status="{status}"}} {count}')
        for provider, count in sorted(summary["counts_by_provider"].items()):
            lines.append(f'ai_pr_review_jobs_provider{{provider="{provider}"}} {count}')
        for risk_level, count in sorted(summary["counts_by_risk"].items()):
            lines.append(f'ai_pr_review_jobs_risk{{level="{risk_level}"}} {count}')
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.post("/webhooks/github")
    async def github_webhook(request: Request) -> JSONResponse:
        payload_body = await request.body()
        signature_header = request.headers.get("x-hub-signature-256")
        delivery_id = request.headers.get("x-github-delivery", "")
        event_name = request.headers.get("x-github-event", "")
        if not delivery_id:
            raise HTTPException(status_code=400, detail="Missing X-GitHub-Delivery header.")
        try:
            verify_github_webhook(payload_body, signature_header, runtime_settings.github_webhook_secret)
        except WebhookVerificationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        payload = json.loads(payload_body.decode("utf-8"))
        review_request = build_review_request(delivery_id, event_name, payload)
        if review_request is None:
            return JSONResponse(
                {
                    "accepted": False,
                    "reason": "Event ignored because it is not a reviewable pull_request action.",
                },
                status_code=202,
            )

        job = service.submit(review_request)
        return JSONResponse(
            {
                "accepted": True,
                "job_id": job.job_id,
                "status": job.status,
                "repo": job.repo_full_name,
                "pull_number": job.pull_number,
            },
            status_code=202,
        )

    return app


def _create_default_app() -> FastAPI:
    try:
        return create_app()
    except Exception as exc:
        LOGGER.warning("Server app loaded in placeholder mode: %s", exc)
        placeholder = FastAPI(
            title="AI PR Review",
            version="0.4.0",
            summary="Placeholder app until runtime configuration is valid",
        )

        @placeholder.get("/healthz")
        async def healthcheck() -> dict[str, str]:
            return {
                "status": "misconfigured",
                "detail": str(exc),
            }

        @placeholder.get("/readyz")
        async def readiness() -> JSONResponse:
            return JSONResponse(
                {
                    "status": "misconfigured",
                    "detail": str(exc),
                },
                status_code=503,
            )

        @placeholder.get("/", response_class=HTMLResponse)
        async def dashboard() -> HTMLResponse:
            return HTMLResponse(
                "<html><body><h1>AI PR Review</h1><p>Server is misconfigured. "
                f"{str(exc)}</p></body></html>"
            )

        return placeholder


app = _create_default_app()


def run() -> None:
    import uvicorn

    settings = AppSettings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        reload=False,
    )
