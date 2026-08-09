from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from epyhia.api.auth import Unauthorized
from epyhia.config import CredentialNotConfigured
from epyhia.cost.budget import BudgetNotConfigured
from epyhia.gate.errors import PreconditionFailed

# One shape everywhere (contracts/rest-api.md "Errors"): {error: "<machine_slug>",
# detail: "<human string>"}. The credential case is named explicitly because FR-064 and
# SC-010 turn on it — a stack trace three layers deep is exactly what this must not be.

_STATUS_SLUGS = {
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "unprocessable",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


def _error_body(error: str, detail: object) -> dict:
    return {"error": error, "detail": detail}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=_error_body("validation_error", exc.errors()),
        )

    @app.exception_handler(CredentialNotConfigured)
    async def _credential_not_configured(_: Request, exc: CredentialNotConfigured) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body("credential_not_configured", str(exc)),
        )

    @app.exception_handler(BudgetNotConfigured)
    async def _budget_not_configured(_: Request, exc: BudgetNotConfigured) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body("budget_not_configured", str(exc)),
        )

    @app.exception_handler(Unauthorized)
    async def _unauthorized(_: Request, exc: Unauthorized) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=_error_body("unauthorized", exc.detail),
        )

    @app.exception_handler(PreconditionFailed)
    async def _precondition_failed(_: Request, exc: PreconditionFailed) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_error_body(exc.reason, exc.reason),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            content = exc.detail
        else:
            slug = _STATUS_SLUGS.get(exc.status_code, "error")
            content = _error_body(slug, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=content)
