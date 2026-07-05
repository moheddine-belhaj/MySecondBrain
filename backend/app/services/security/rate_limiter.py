"""Token-bucket rate limiter.

Algorithm — token bucket
------------------------
Each client key (IP address) has an invisible bucket that holds up to `burst`
tokens.  The bucket refills at `requests_per_minute / 60` tokens per second.

On each request:
  1. Compute tokens added since last request (elapsed × refill_rate).
  2. Add to current tokens, capping at burst.
  3. If tokens >= 1 → consume 1 token, allow.
  4. If tokens < 1 → deny (return False).

Properties
----------
- Burst allowance: a client that has been idle can fire up to `burst`
  requests instantly before being throttled. This prevents false positives
  from normal UI interactions (page load triggers several requests at once).
- Smooth throttle: sustained request rates above the limit are rejected;
  requests exactly at the limit flow through continuously.

Thread safety
-------------
asyncio is single-threaded — dict operations are atomic. No locking needed.

Storage
-------
In-memory dict. For a local-first single-user app, the dict never grows
beyond a handful of entries (all requests come from 127.0.0.1).
"""

import time


class RateLimiter:
    """Token-bucket rate limiter keyed by arbitrary string (IP, user-id, …)."""

    def __init__(self, requests_per_minute: float, burst: int) -> None:
        self._rate = requests_per_minute / 60.0   # tokens per second
        self._burst = float(burst)
        # key → (current_tokens, last_refill_timestamp)
        self._buckets: dict[str, tuple[float, float]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def check(self, key: str) -> bool:
        """Consume one token for *key*. Returns True if allowed."""
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self._burst, now))

        # Refill based on elapsed time
        elapsed = now - last
        tokens = min(self._burst, tokens + elapsed * self._rate)

        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return True

        self._buckets[key] = (tokens, now)
        return False

    def remaining(self, key: str) -> float:
        """Estimated available tokens for *key* (0.0 to burst). Non-destructive."""
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self._burst, now))
        elapsed = now - last
        return min(self._burst, tokens + elapsed * self._rate)

    def reset(self, key: str) -> None:
        """Reset bucket for *key* to full capacity (useful for tests)."""
        self._buckets.pop(key, None)

    def bucket_count(self) -> int:
        """Number of tracked keys (useful for monitoring)."""
        return len(self._buckets)
