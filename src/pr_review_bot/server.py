from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
        version="0.2.0",
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

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job.as_dict()

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
            version="0.2.0",
            summary="Placeholder app until runtime configuration is valid",
        )

        @placeholder.get("/healthz")
        async def healthcheck() -> dict[str, str]:
            return {
                "status": "misconfigured",
                "detail": str(exc),
            }

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
