from app.core.bounded_cache import BoundedTTLCache


def test_cache_evicts_least_recently_used_entry() -> None:
    now = [0.0]
    cache = BoundedTTLCache[str, int](maxsize=2, ttl_seconds=60, clock=lambda: now[0])

    cache.set("first", 1)
    cache.set("second", 2)
    assert cache.lookup("first") == (True, 1)

    cache.set("third", 3)

    assert cache.lookup("first") == (True, 1)
    assert cache.lookup("second") == (False, None)
    assert cache.lookup("third") == (True, 3)


def test_cache_removes_expired_entries_and_supports_none_values() -> None:
    now = [0.0]
    cache = BoundedTTLCache[str, str | None](maxsize=2, ttl_seconds=10, clock=lambda: now[0])
    cache.set("missing-host", None)

    assert cache.lookup("missing-host") == (True, None)

    now[0] = 11.0

    assert cache.lookup("missing-host") == (False, None)
    assert len(cache) == 0
