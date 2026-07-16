from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from time import monotonic
from typing import Generic, TypeVar

TKey = TypeVar("TKey")
TValue = TypeVar("TValue")


class BoundedTTLCache(Generic[TKey, TValue]):
    """Small thread-safe TTL/LRU cache for process-local best-effort data."""

    def __init__(
        self,
        *,
        maxsize: int,
        ttl_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._maxsize = maxsize
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._values: OrderedDict[TKey, tuple[float, TValue]] = OrderedDict()
        self._lock = Lock()

    def lookup(self, key: TKey) -> tuple[bool, TValue | None]:
        now = self._clock()
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if expires_at <= now:
                del self._values[key]
                return False, None
            self._values.move_to_end(key)
            return True, value

    def set(self, key: TKey, value: TValue) -> None:
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            self._values[key] = (now + self._ttl_seconds, value)
            self._values.move_to_end(key)
            while len(self._values) > self._maxsize:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        now = self._clock()
        with self._lock:
            self._remove_expired(now)
            return len(self._values)

    def _remove_expired(self, now: float) -> None:
        expired = [key for key, (expires_at, _) in self._values.items() if expires_at <= now]
        for key in expired:
            del self._values[key]
