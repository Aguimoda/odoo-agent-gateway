"""Per-login sliding-window rate limit, kept in process memory (ADR 0009)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

ANONYMOUS = "anonymous"


class RateLimiter:
    def __init__(
        self,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = 60.0,
    ) -> None:
        if per_minute < 1:
            raise ValueError("per_minute must be at least 1")
        self._limit = per_minute
        self._clock = clock
        self._window = window_seconds
        self._calls: dict[str, deque[float]] = {}

    def allow(self, login: str | None) -> bool:
        """Record a call for `login` and say whether it is within the limit.

        Refused calls are not recorded, so hammering while blocked does not extend the block.
        """
        key = (login or "").strip().lower() or ANONYMOUS
        now = self._clock()
        calls = self._calls.setdefault(key, deque())
        while calls and now - calls[0] >= self._window:
            calls.popleft()
        if len(calls) >= self._limit:
            return False
        calls.append(now)
        return True
