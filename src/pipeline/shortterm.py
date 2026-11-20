"""Short-term state: chat locks, job status and progress events, and a cache of open chats.

Redis when REDIS_URL is set, so the API and any number of workers share it; otherwise memory,
which works only when jobs run inside the API process. Everything here expires (24 hours by
default): PostgreSQL, through the session store, is the long-term record.
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from research.contracts import JsonObject

TTL = 24 * 60 * 60
LOCK_TTL = 15 * 60  # longer than a full Research, GTM, and PM turn
MAX_EVENTS = 200

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


class ShortTerm(Protocol):
    def acquire(self, chat_id: str, owner: str, ttl: int = LOCK_TTL) -> bool: ...
    def release(self, chat_id: str, owner: str) -> None: ...
    def put_job(self, job_id: str, job: JsonObject) -> None: ...
    def get_job(self, job_id: str) -> JsonObject | None: ...
    def add_event(self, job_id: str, event: JsonObject) -> None: ...
    def events(self, job_id: str, after: int = 0) -> list[JsonObject]: ...
    def cache_chat(self, chat_id: str, value: JsonObject) -> None: ...
    def cached_chat(self, chat_id: str) -> JsonObject | None: ...
    def drop_chat(self, chat_id: str) -> None: ...


@dataclass
class MemoryShortTerm:
    ttl: int = TTL
    _values: dict[str, tuple[float, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _get(self, key: str) -> Any:
        entry = self._values.get(key)
        if entry is None or entry[0] < time.time():
            self._values.pop(key, None)
            return None
        return entry[1]

    def _set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._values[key] = (time.time() + (ttl or self.ttl), value)

    def acquire(self, chat_id: str, owner: str, ttl: int = LOCK_TTL) -> bool:
        with self._lock:
            if self._get(f"lock:chat:{chat_id}") is not None:
                return False
            self._set(f"lock:chat:{chat_id}", owner, ttl)
            return True

    def release(self, chat_id: str, owner: str) -> None:
        with self._lock:
            if self._get(f"lock:chat:{chat_id}") == owner:
                self._values.pop(f"lock:chat:{chat_id}", None)

    def put_job(self, job_id: str, job: JsonObject) -> None:
        with self._lock:
            self._set(f"job:{job_id}", json.loads(json.dumps(job)))

    def get_job(self, job_id: str) -> JsonObject | None:
        with self._lock:
            value = self._get(f"job:{job_id}")
            return dict(value) if value else None

    def add_event(self, job_id: str, event: JsonObject) -> None:
        with self._lock:
            events = self._get(f"job:{job_id}:events") or []
            if len(events) < MAX_EVENTS:
                events.append(json.loads(json.dumps(event, default=str)))
            self._set(f"job:{job_id}:events", events)

    def events(self, job_id: str, after: int = 0) -> list[JsonObject]:
        with self._lock:
            return list((self._get(f"job:{job_id}:events") or [])[after:])

    def cache_chat(self, chat_id: str, value: JsonObject) -> None:
        with self._lock:
            self._set(f"chat:{chat_id}", json.loads(json.dumps(value)))

    def cached_chat(self, chat_id: str) -> JsonObject | None:
        with self._lock:
            value = self._get(f"chat:{chat_id}")
            return json.loads(json.dumps(value)) if value else None

    def drop_chat(self, chat_id: str) -> None:
        with self._lock:
            self._values.pop(f"chat:{chat_id}", None)


class RedisShortTerm:
    """The same state in Redis. Values are JSON strings; every key has a TTL."""

    def __init__(self, url: str | None = None, *, client: Any = None, ttl: int = TTL) -> None:
        self.ttl = ttl
        if client is not None:
            self.redis = client
            return
        url = url or os.getenv("REDIS_URL", "")
        if not url:
            raise ValueError("Set REDIS_URL to use Redis for short-term state.")
        try:
            import redis
        except ImportError as error:
            raise ValueError("redis is not installed. Run: pip install -e '.[queue]'") from error
        self.redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=10)

    def ping(self) -> None:
        self.redis.ping()

    def acquire(self, chat_id: str, owner: str, ttl: int = LOCK_TTL) -> bool:
        return bool(self.redis.set(f"lock:chat:{chat_id}", owner, nx=True, ex=ttl))

    def release(self, chat_id: str, owner: str) -> None:
        self.redis.eval(_RELEASE, 1, f"lock:chat:{chat_id}", owner)

    def put_job(self, job_id: str, job: JsonObject) -> None:
        self.redis.set(f"job:{job_id}", json.dumps(job), ex=self.ttl)

    def get_job(self, job_id: str) -> JsonObject | None:
        value = self.redis.get(f"job:{job_id}")
        return cast(JsonObject, json.loads(value)) if value else None

    def add_event(self, job_id: str, event: JsonObject) -> None:
        key = f"job:{job_id}:events"
        if self.redis.llen(key) >= MAX_EVENTS:
            return
        self.redis.rpush(key, json.dumps(event, default=str))
        self.redis.expire(key, self.ttl)

    def events(self, job_id: str, after: int = 0) -> list[JsonObject]:
        return [json.loads(item) for item in self.redis.lrange(f"job:{job_id}:events", after, -1)]

    def cache_chat(self, chat_id: str, value: JsonObject) -> None:
        self.redis.set(f"chat:{chat_id}", json.dumps(value), ex=self.ttl)

    def cached_chat(self, chat_id: str) -> JsonObject | None:
        value = self.redis.get(f"chat:{chat_id}")
        return cast(JsonObject, json.loads(value)) if value else None

    def drop_chat(self, chat_id: str) -> None:
        self.redis.delete(f"chat:{chat_id}")


def default_short_term() -> ShortTerm:
    """Redis when REDIS_URL is set, otherwise memory."""
    if os.getenv("REDIS_URL"):
        store = RedisShortTerm()
        store.ping()
        return store
    return MemoryShortTerm()
