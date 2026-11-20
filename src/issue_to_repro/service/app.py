"""FastAPI app: verify, route, enqueue. The request returns at once; work happens in the queue.

Fail closed: without a webhook secret the app refuses to start, and any request whose signature
does not verify is rejected before its body is parsed.
"""

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from ..config import Settings, get_settings
from .events import Action, Approve, Ignore, Reproduce, route
from .signature import verify_signature

Enqueue = Callable[[Action], None]


def create_app(enqueue: Enqueue, settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    if s.github_webhook_secret is None or not s.github_webhook_secret.get_secret_value():
        raise ValueError("GITHUB_WEBHOOK_SECRET must be set; refusing to accept unsigned webhooks")
    secret = s.github_webhook_secret.get_secret_value().encode()
    app = FastAPI(title="issue-to-repro", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/github", status_code=202)
    async def github_webhook(
        request: Request,
        x_github_event: str = Header(default=""),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = await request.body()
        if not verify_signature(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="body is not JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body is not a JSON object")
        action = route(x_github_event, payload, s.approve_label)
        if isinstance(action, Ignore):
            return {"status": "ignored", "reason": action.reason}
        enqueue(action)
        return {"status": "queued", "action": _kind(action), "issue": _issue(action)}

    return app


def _kind(action: Reproduce | Approve) -> str:
    return "reproduce" if isinstance(action, Reproduce) else "approve"


def _issue(action: Reproduce | Approve) -> str:
    return f"{action.repo}#{action.issue_number}"
