import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.exceptions")


# ── Domain exceptions ─────────────────────────────────────────────────────────

class AppError(Exception):
    """Base for all application-level errors. Raise this, not HTTPException,
    from service/domain code so HTTP concerns stay in the API layer."""

    status_code: int = 500

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404

    def __init__(self, resource: str) -> None:
        super().__init__(f"{resource} not found")


class ServiceUnavailableError(AppError):
    status_code = 503

    def __init__(self, service: str, reason: str = "") -> None:
        detail = f": {reason}" if reason else ""
        super().__init__(f"{service} is unavailable{detail}")


class ValidationError(AppError):
    status_code = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ── Shared error response shape ───────────────────────────────────────────────

def _error_response(
    status_code: int,
    message: str,
    detail: object = None,
    request_id: str | None = None,
) -> JSONResponse:
    body: dict = {"error": message}
    if detail is not None:
        body["detail"] = detail
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body)


# ── Handler registration ──────────────────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "Request validation failed",
            extra={"path": str(request.url.path), "errors": exc.errors()},
        )
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="Request validation failed",
            detail=exc.errors(),
            request_id=request_id,
        )

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning(
            "HTTP error",
            extra={"status_code": exc.status_code, "detail": exc.detail},
        )
        return _error_response(
            exc.status_code,
            message=str(exc.detail),
            request_id=request_id,
        )

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error("Application error", extra={"error_message": exc.message})
        return _error_response(
            exc.status_code,
            message=exc.message,
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)

        # BaseHTTPMiddleware + anyio (Python 3.11+) wraps exceptions raised inside
        # `call_next` into a BaseExceptionGroup. FastAPI's named exception handlers
        # (AppError, HTTPException) never see the inner exception — it arrives here
        # instead. Unwrap single-exception groups so we can handle them properly.
        actual: Exception = exc
        if isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            actual = exc.exceptions[0]  # type: ignore[assignment]

        if isinstance(actual, AppError):
            logger.error("Application error", extra={"message": actual.message})
            return _error_response(actual.status_code, actual.message, request_id=request_id)

        if isinstance(actual, HTTPException):
            logger.warning("HTTP error", extra={"status_code": actual.status_code})
            return _error_response(actual.status_code, str(actual.detail), request_id=request_id)

        logger.exception("Unhandled exception", exc_info=actual)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal server error",
            request_id=request_id,
        )
