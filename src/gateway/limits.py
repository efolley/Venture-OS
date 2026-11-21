"""Fixed-window rate limits: Redis when REDIS_URL is set (shared by every gateway), else memory."""

import os
import threading
import time
from typing import Any, Protocol


class Limiter(Protocol):
    def hit(self, key: str, window: int) -> int:
        """Count 1 request for key in the current window and return the count so far."""
        ...


class MemoryLimiter:
    def __init__(self) -> None:
        self.counts: dict[str, tuple[float, int]] = {}
        self.lock = threading.Lock()

    def hit(self, key: str, window: int) -> int:
        bucket = f"{key}:{int(time.time() // window)}"
        with self.lock:
            now = time.time()
            if len(self.counts) > 10000:  # drop expired windows so memory stays bounded
                self.counts = {k: v for k, v in self.counts.items() if v[0] > now}
            expires, count = self.counts.get(bucket, (now + window, 0))
            self.counts[bucket] = (expires, count + 1)
            return count + 1


class RedisLimiter:
    def __init__(self, url: str | None = None, *, client: Any = None) -> None:
        if client is None:
            import redis

            client = redis.Redis.from_url(url or os.environ["REDIS_URL"], decode_responses=True,
                                          socket_timeout=2)
        self.redis = client

    def hit(self, key: str, window: int) -> int:
        bucket = f"rl:{key}:{int(time.time() // window)}"
        count = int(self.redis.incr(bucket))
        if count == 1:
            self.redis.expire(bucket, window)
        return count


def default_limiter() -> Limiter:
    return RedisLimiter() if os.getenv("REDIS_URL") else MemoryLimiter()
