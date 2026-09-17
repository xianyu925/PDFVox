import unittest
from unittest.mock import patch

from app.services.cache import TTLCache


class TTLCacheTests(unittest.TestCase):
    def test_evicts_least_recently_used_entry(self):
        cache = TTLCache(max_entries=2, ttl_seconds=60)
        cache["a"] = 1
        cache["b"] = 2
        self.assertEqual(1, cache["a"])
        cache["c"] = 3

        self.assertNotIn("b", cache)
        self.assertEqual({"a", "c"}, set(cache))

    def test_expires_entries(self):
        with patch("app.services.cache.time.monotonic", side_effect=[10, 10, 12]):
            cache = TTLCache(max_entries=2, ttl_seconds=1)
            cache["a"] = 1
            self.assertNotIn("a", cache)


if __name__ == "__main__":
    unittest.main()
