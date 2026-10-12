"""App factory: loads prompts (start-up stops if any is missing), mounts the API and the static Frontend."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .llm import PromptLoadError, load_prompts
from .security import RedactingFilter, redact
from .settings import PROJECT_ROOT, get_settings
from .storage import AppError

log = logging.getLogger("credit_app")


def create_app() -> FastAPI:
    settings = get_settings()
    try:
        prompts = load_prompts(settings.prompts_dir)
    except PromptLoadError as exc:
        raise SystemExit(f"Start-up stopped: runtime prompt {exc.prompt_id} could not be loaded ({exc.reason}).") from exc

    redacting = RedactingFilter(lambda: get_settings().secrets())
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "credit_app"):
        logging.getLogger(name).addFilter(redacting)

    app = FastAPI(title="AI-Assisted Credit Analysis", docs_url=None, redoc_url=None)
    app.state.prompts = prompts

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        secrets = get_settings().secrets()
        body = {"error_code": exc.code, "message": redact(exc.message, secrets)}
        if exc.fields:
            body["fields"] = exc.fields
        if exc.details is not None:
            body["details"] = [redact(d, secrets) if isinstance(d, str) else d for d in exc.details] if isinstance(exc.details, list) else exc.details
        return JSONResponse(status_code=exc.status, content=body)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(x) for x in e["loc"][1:]) or "body", "reason": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error_code": "invalid_request", "message": "Please correct the highlighted fields.", "fields": fields})

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("Unexpected error")
        return JSONResponse(status_code=500, content={"error_code": "internal_error",
                                                      "message": redact(f"Unexpected error: {exc}", get_settings().secrets())})

    app.include_router(router)
    app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "frontend"), html=True), name="frontend")
    return app


app = create_app()
