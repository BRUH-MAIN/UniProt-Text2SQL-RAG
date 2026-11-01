"""In-process sliding-window rate limiter.

The public demo spends the owner's LLM quota on every request, so unauthenticated traffic
is capped per client and globally. Process-local on purpose: it is a cost guard for a
single small Space, not a distributed quota system.
"""
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, per_client: int, global_limit: int, window_s: float = 3600.0, clock=time.monotonic):
        self.per_client, self.global_limit, self.window_s, self._clock = per_client, global_limit, window_s, clock
        self._by_client: dict[str, deque] = defaultdict(deque)
        self._all: deque = deque()
        self._lock = threading.Lock()

    def _trim(self, q: deque, now: float) -> None:
        while q and now - q[0] > self.window_s:
            q.popleft()

    def allow(self, client: str) -> tuple[bool, str]:
        with self._lock:
            now = self._clock()
            mine = self._by_client[client]
            self._trim(mine, now)
            self._trim(self._all, now)
            if len(mine) >= self.per_client:
                return False, f"Limit of {self.per_client} questions per hour reached; please try again later."
            if len(self._all) >= self.global_limit:
                return False, "The demo has reached its hourly capacity; please try again later."
            mine.append(now)
            self._all.append(now)
            return True, ""
