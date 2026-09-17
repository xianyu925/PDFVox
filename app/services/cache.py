"""Small thread-safe TTL/LRU cache used for process-local acceleration."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Iterator, MutableMapping
from threading import RLock
from typing import Generic, TypeVar


K = TypeVar("K")
V = TypeVar("V")


class TTLCache(MutableMapping[K, V], Generic[K, V]):
    def __init__(self, max_entries: int, ttl_seconds: int):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._lock = RLock()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, (deadline, _) in self._data.items() if deadline <= now]
        for key in expired:
            self._data.pop(key, None)

    def __getitem__(self, key: K) -> V:
        with self._lock:
            self._purge_expired()
            deadline, value = self._data[key]
            self._data.move_to_end(key)
            return value

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            self._purge_expired()
            self._data[key] = (time.monotonic() + self.ttl_seconds, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def __delitem__(self, key: K) -> None:
        with self._lock:
            del self._data[key]

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            self._purge_expired()
            return iter(list(self._data.keys()))

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._data)

    def get(self, key: K, default=None):
        try:
            return self[key]
        except KeyError:
            return default
