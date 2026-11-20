"""The API gateway, offline: the upstream API is an httpx MockTransport."""

import unittest
from typing import Any

try:
    import httpx
    from fastapi.testclient import TestClient

    from gateway.app import Settings, create_app
    from gateway.limits import MemoryLimiter, RedisLimiter
except ImportError:  # the api and test extras are optional
    TestClient = None  # type: ignore[assignment,misc]


class Upstream:
    def __init__(self, fail: Exception | None = None) -> None:
        self.requests: list[Any] = []
        self.fail = fail

    def __call__(self, request: "httpx.Request") -> "httpx.Response":
        self.requests.append(request)
        if self.fail:
            raise self.fail
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(201, json={"path": request.url.path, "query": str(request.url.params)},
                              headers={"X-Upstream": "yes"})


class BrokenLimiter:
    def hit(self, key: str, window: int) -> int:
        raise ConnectionError("redis down")


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


@unittest.skipIf(TestClient is None, "install the api and test extras")
class GatewayTests(unittest.TestCase):
    def client(self, upstream: Upstream | None = None, limiter: Any = None, **settings: Any):  # type: ignore[no-untyped-def]
        self.upstream = upstream or Upstream()
        app = create_app(Settings(**settings), limiter=limiter or MemoryLimiter(),
                         transport=httpx.MockTransport(self.upstream))
        return TestClient(app)

    def test_forwards_requests_and_adds_a_request_id(self) -> None:
        client = self.client()
        response = client.post("/api/chats?limit=5", json={"message": "x"},
                               headers={"X-API-Key": "not forwarded"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"path": "/api/chats", "query": "limit=5"})
        self.assertEqual(response.headers["X-Upstream"], "yes")
        forwarded = self.upstream.requests[0]
        self.assertEqual(forwarded.headers["X-Request-ID"], response.headers["X-Request-ID"])
        self.assertNotIn("x-api-key", forwarded.headers)
        self.assertEqual(forwarded.headers["X-Forwarded-For"], "testclient")
        kept = client.get("/", headers={"X-Request-ID": "abc12345-run"})
        self.assertEqual(kept.headers["X-Request-ID"], "abc12345-run")
        invalid = client.get("/", headers={"X-Request-ID": "bad id with spaces"})
        self.assertNotEqual(invalid.headers["X-Request-ID"], "bad id with spaces")

    def test_api_key_guards_the_api_but_not_the_web_ui(self) -> None:
        client = self.client(api_key="secret-key")
        self.assertEqual(client.get("/api/chats").status_code, 401)
        self.assertEqual(client.get("/api/chats", headers={"X-API-Key": "wrong"}).status_code, 401)
        self.assertEqual(client.get("/api/chats", headers={"X-API-Key": "secret-key"}).status_code, 201)
        self.assertEqual(client.get("/index.html").status_code, 201)

    def test_rate_limits(self) -> None:
        client = self.client(rate_limit=3, message_limit=1)
        self.assertEqual(client.post("/api/chats/c/messages", json={}).status_code, 201)
        limited = client.post("/api/chats/c/messages", json={})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["Retry-After"], "60")
        self.assertEqual(client.get("/api/chats").status_code, 201)
        self.assertEqual(client.get("/api/chats").status_code, 429)
        self.assertEqual(client.get("/assets/app.js").status_code, 201)  # web UI files are not limited

    def test_a_broken_limiter_lets_requests_through(self) -> None:
        self.assertEqual(self.client(limiter=BrokenLimiter()).get("/api/chats").status_code, 201)

    def test_body_limit(self) -> None:
        client = self.client(max_body=100)
        self.assertEqual(client.post("/api/chats", content=b"x" * 101).status_code, 413)
        self.assertEqual(client.post("/api/chats", content=b"x" * 100).status_code, 201)

    def test_upstream_down_or_slow(self) -> None:
        down = self.client(Upstream(fail=httpx.ConnectError("refused")))
        self.assertEqual(down.get("/api/chats").status_code, 502)
        self.assertEqual(down.get("/gateway/health").status_code, 503)
        slow = self.client(Upstream(fail=httpx.ReadTimeout("slow")))
        self.assertEqual(slow.get("/api/chats").status_code, 504)
        self.assertEqual(self.client().get("/gateway/health").json(), {"status": "ok", "upstream": "ok"})

    def test_redis_limiter_counts_per_window_and_expires(self) -> None:
        fake = FakeRedis()
        limiter = RedisLimiter(client=fake)
        self.assertEqual([limiter.hit("all:ip", 60) for _ in range(3)], [1, 2, 3])
        self.assertEqual(list(fake.expiries.values()), [60])


if __name__ == "__main__":
    unittest.main()
