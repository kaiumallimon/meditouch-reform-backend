import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.logging import logger, set_request_id

# Sensitive query params or paths to exclude/mask from detailed request logs if necessary
SENSITIVE_PATHS = ["/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/change-password"]

class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Extract or generate correlation ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        set_request_id(request_id)
        request.state.request_id = request_id
        
        client_host = request.client.host if request.client else "unknown"
        method = request.method
        url_path = request.url.path
        query_params = str(request.query_params) if request.query_params else ""

        start_time = time.time()

        # Log incoming HTTP request (skip noisy health checks from debug spam)
        if url_path != "/health":
            logger.info(f"--> HTTP {method} {url_path}{'?' + query_params if query_params else ''} [Client: {client_host}]")

        try:
            response = await call_next(request)
        except Exception as e:
            process_time = (time.time() - start_time) * 1000
            logger.error(f"<-- HTTP {method} {url_path} FAILED after {process_time:.2f}ms with error: {e}", exc_info=True)
            raise

        process_time = (time.time() - start_time) * 1000
        process_time_str = f"{process_time:.2f}ms"

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = process_time_str

        # Log completed HTTP response
        if url_path != "/health":
            status_code = response.status_code
            if status_code >= 400:
                logger.warning(f"<-- HTTP {method} {url_path} {status_code} [{process_time_str}]")
            else:
                logger.info(f"<-- HTTP {method} {url_path} {status_code} [{process_time_str}]")

        return response
