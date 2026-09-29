"""Small in-memory per-IP rate limiter for the public (key-less) endpoints.

Counters live only in process memory, are never persisted and expire after the window.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        for key in list(self._hits):
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if not q:
                del self._hits[key]

    def hit(self, key: str) -> int:
        """Register a hit; return seconds to wait if the limit is exceeded, else 0."""
        now = time.monotonic()
        with self._lock:
            self._cleanup(now)
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return int(self.window - (now - q[0])) + 1
            q.append(now)
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(limit: int, window_seconds: int):
    limiter = RateLimiter(limit, window_seconds)

    def dependency(request: Request) -> None:
        wait = limiter.hit(client_ip(request))
        if wait:
            raise HTTPException(
                status_code=429,
                detail=f"rate limit exceeded ({limit} requests per {window_seconds // 60} minutes); retry in {wait}s",
                headers={"Retry-After": str(wait)},
            )

    dependency.limiter = limiter  # type: ignore[attr-defined]
    return dependency
