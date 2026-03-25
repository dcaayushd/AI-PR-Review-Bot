from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .context import load_pr_context_from_payload
from .domain import PullRequestContext

SUPPORTED_PULL_REQUEST_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


class WebhookVerificationError(RuntimeError):
    pass


@dataclass(slots=True)
class ReviewRequest:
    delivery_id: str
    event_name: str
    action: str
    installation_id: int
    pr_context: PullRequestContext


def verify_github_webhook(payload_body: bytes, signature_header: str | None, secret: str) -> None:
    if not signature_header:
        raise WebhookVerificationError("Missing X-Hub-Signature-256 header.")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookVerificationError("Webhook signature validation failed.")


def build_review_request(delivery_id: str, event_name: str, payload: dict[str, object]) -> ReviewRequest | None:
    if event_name != "pull_request":
        return None

    action = str(payload.get("action") or "").strip()
    if action not in SUPPORTED_PULL_REQUEST_ACTIONS:
        return None

    pull_request = payload.get("pull_request")
    pull_request = pull_request if isinstance(pull_request, dict) else {}
    if bool(pull_request.get("draft")):
        return None
    if str(pull_request.get("state") or "").lower() != "open":
        return None

    installation = payload.get("installation")
    installation = installation if isinstance(installation, dict) else {}
    installation_id = installation.get("id")
    if not installation_id:
        raise ValueError("Webhook payload is missing installation.id.")

    pr_context = load_pr_context_from_payload(payload)
    return ReviewRequest(
        delivery_id=delivery_id,
        event_name=event_name,
        action=action,
        installation_id=int(installation_id),
        pr_context=pr_context,
    )

