"""`ventureos-gateway`: a small reverse proxy in front of `ventureos-api`.

For every request it:
1. gives it a request ID (or keeps a valid `X-Request-ID`) and logs method, path, status, time;
2. on `/api/*`, checks the API key when GATEWAY_API_KEY is set (`X-API-Key` header);
3. on `/api/*`, applies rate limits per client: GATEWAY_RATE_LIMIT requests a minute in all
   (default 120) and GATEWAY_MESSAGE_LIMIT new chat messages a minute (default 10);
4. rejects bodies over GATEWAY_MAX_BODY bytes (default 64 KB);
5. forwards it to GATEWAY_UPSTREAM (default http://127.0.0.1:8000) and returns the answer,
   or 502/504 when the API is down or slow.

Rate limits live in Redis when REDIS_URL is set, so several gateways share them. If Redis
fails, requests are let through and the error is logged: the limits protect, they never block.
"""

import hmac
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .limits import Limiter, MemoryLimiter, default_limiter

logger = logging.getLogger("ventureos.gateway")
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


@dataclass
class Settings:
    upstream: str = "http://127.0.0.1:8000"
    api_key: str = ""
    rate_limit: int = 120
    message_limit: int = 10
    window: int = 60
    max_body: int = 64 * 1024
    timeout: float = 30.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(upstream=os.getenv("GATEWAY_UPSTREAM", cls.upstream).rstrip("/"),
                   api_key=os.getenv("GATEWAY_API_KEY", ""),
                   rate_limit=int(os.getenv("GATEWAY_RATE_LIMIT", cls.rate_limit)),
                   message_limit=int(os.getenv("GATEWAY_MESSAGE_LIMIT", cls.message_limit)),
                   max_body=int(os.getenv("GATEWAY_MAX_BODY", cls.max_body)))


def create_app(settings: Settings | None = None, *, limiter: Limiter | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()
    limiter = limiter or MemoryLimiter()
    client = httpx.AsyncClient(base_url=settings.upstream, transport=transport,
                               timeout=settings.timeout)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await client.aclose()

    app = FastAPI(title="VentureOS gateway", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)

    @app.get("/gateway/health")
    async def health() -> JSONResponse:
        try:
            upstream = (await client.get("/api/health")).status_code == 200
        except httpx.HTTPError:
            upstream = False
        return JSONResponse({"status": "ok" if upstream else "degraded",
                             "upstream": "ok" if upstream else "down"},
                            status_code=200 if upstream else 503)

    def over_limit(key: str, limit: int) -> bool:
        try:
            return limiter.hit(key, settings.window) > limit
        except Exception as error:  # noqa: BLE001 - fail open: limits never take the app down
            logger.warning("rate limiter unavailable: %s", type(error).__name__)
            return False

    @app.api_route("/{path:path}", methods=METHODS)
    async def proxy(path: str, request: Request) -> Response:
        started = time.perf_counter()
        given = request.headers.get("x-request-id", "")
        request_id = given if _REQUEST_ID.match(given) else uuid.uuid4().hex
        client_ip = request.client.host if request.client else "unknown"

        def finish(response: Response) -> Response:
            response.headers["X-Request-ID"] = request_id
            logger.info("request_id=%s method=%s path=/%s status=%d duration_ms=%.1f", request_id,
                        request.method, path, response.status_code,
                        (time.perf_counter() - started) * 1000)
            return response

        def error(status: int, detail: str, headers: dict[str, str] | None = None) -> Response:
            return finish(JSONResponse({"detail": detail}, status_code=status, headers=headers))

        is_api = path == "api" or path.startswith("api/")
        if is_api and settings.api_key and not hmac.compare_digest(
                request.headers.get("x-api-key", "").encode(), settings.api_key.encode()):
            return error(401, "Missing or wrong API key. Send it in the X-API-Key header.")
        retry = {"Retry-After": str(settings.window)}
        if is_api and over_limit(f"all:{client_ip}", settings.rate_limit):
            return error(429, "Too many requests. Wait a minute and try again.", retry)
        if (is_api and request.method == "POST" and path.endswith("/messages")
                and over_limit(f"messages:{client_ip}", settings.message_limit)):
            return error(429, "Too many new messages. Wait a minute and try again.", retry)

        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > settings.max_body:
            return error(413, "The request body is too large.")
        body = await request.body()
        if len(body) > settings.max_body:
            return error(413, "The request body is too large.")

        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in HOP_BY_HOP and key.lower() != "x-api-key"}
        forwarded = request.headers.get("x-forwarded-for", "")
        headers.update({"X-Request-ID": request_id, "X-Forwarded-Proto": request.url.scheme,
                        "X-Forwarded-For": f"{forwarded}, {client_ip}" if forwarded else client_ip,
                        **settings.extra_headers})
        try:
            upstream = await client.request(request.method, f"/{path}",
                                            params=list(request.query_params.multi_items()),
                                            content=body, headers=headers)
        except httpx.TimeoutException:
            return error(504, "The VentureOS API took too long to answer.")
        except httpx.HTTPError:
            return error(502, "The VentureOS API is not reachable. Start it with: ventureos-api")
        reply_headers = {key: value for key, value in upstream.headers.items()
                         if key.lower() not in HOP_BY_HOP and key.lower() != "content-encoding"}
        return finish(Response(upstream.content, status_code=upstream.status_code,
                               headers=reply_headers))

    return app


def _app_from_env() -> FastAPI:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path.cwd() / ".env")
    except ImportError:
        pass
    return create_app(Settings.from_env(), limiter=default_limiter())


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = _app_from_env()
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8080"))
    print(f"VentureOS gateway is running: open http://127.0.0.1:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, access_log=False)


if __name__ == "__main__":
    main()
