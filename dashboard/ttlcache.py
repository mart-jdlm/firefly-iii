"""TTL cache shared by the API answers."""

import threading
import time


CACHE_SECONDS = 300


class Cache:
    """TTL cache with one lock per key: concurrent loads of the same page share one set of API
    calls, but a slow key (Yahoo quotes, a 24-month build) never blocks the others. When Firefly III
    fails, the last value is served instead of an error."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._items: dict[str, tuple[float, object]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, key: str, make):
        with self._guard:
            hit = self._items.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            with self._guard:
                hit = self._items.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]  # filled while this call waited for the lock
            try:
                value = make()
            except Exception:
                if hit:
                    return hit[1]  # stale rather than an error page
                raise
            with self._guard:
                self._items[key] = (time.time(), value)
            return value

    def drop(self, key: str) -> None:
        with self._guard:
            self._items.pop(key, None)

    def expire_all(self) -> None:
        """Marks everything stale but keeps it as a fallback if the next refresh fails."""
        with self._guard:
            self._items = {k: (0.0, v) for k, (_, v) in self._items.items()}


cache = Cache(CACHE_SECONDS)


def cached(key: str, make):
    return cache.get(key, make)
