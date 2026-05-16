import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.requests")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns a unique ID to every request.

    Reads X-Request-ID from the incoming header if the caller provides one
    (useful for distributed tracing), otherwise generates a new UUID.
    The ID is stored in request.state.request_id and echoed in the response
    header so clients can correlate logs with their own request records.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status code, and duration for every request.

    Reads request.state.request_id set by RequestIDMiddleware so every log line
    is traceable. The ID is read after call_next() so it is always present
    regardless of middleware ordering.

    Note on streaming: BaseHTTPMiddleware buffers the entire response body before
    returning it to the client. This is acceptable for standard JSON responses.
    When real streaming chat is implemented (Task 4), the /chat/stream endpoint
    should bypass this middleware or be replaced with a pure-ASGI middleware that
    does not buffer.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        request_id = getattr(request.state, "request_id", "-")
        logger.info(
            "Request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "request_id": request_id,
            },
        )
        return response
