"""Unit tests for the token-bucket rate limiter."""

import time

import pytest

from app.services.security.rate_limiter import RateLimiter


def _limiter(rpm: float = 60, burst: int = 5) -> RateLimiter:
    return RateLimiter(requests_per_minute=rpm, burst=burst)


class TestCheck:
    def test_allows_first_request(self):
        assert _limiter().check("ip") is True

    def test_allows_up_to_burst(self):
        limiter = _limiter(rpm=60, burst=3)
        results = [limiter.check("ip") for _ in range(3)]
        assert all(results)

    def test_blocks_after_burst_exhausted(self):
        limiter = _limiter(rpm=60, burst=3)
        for _ in range(3):
            limiter.check("ip")
        assert limiter.check("ip") is False

    def test_different_keys_are_independent(self):
        limiter = _limiter(rpm=60, burst=1)
        assert limiter.check("ip-a") is True
        assert limiter.check("ip-b") is True  # separate bucket

    def test_bucket_refills_over_time(self):
        limiter = _limiter(rpm=3600, burst=1)  # 1 token/second
        limiter.check("ip")  # consume 1
        assert limiter.check("ip") is False  # exhausted

        # Manually advance last_refill time to simulate 2 seconds passing
        tokens, _ = limiter._buckets["ip"]
        limiter._buckets["ip"] = (tokens, time.monotonic() - 2.0)

        assert limiter.check("ip") is True  # refilled

    def test_high_rpm_allows_many_requests(self):
        limiter = _limiter(rpm=1000, burst=50)
        results = [limiter.check("ip") for _ in range(50)]
        assert all(results)


class TestRemaining:
    def test_full_bucket_for_new_key(self):
        limiter = _limiter(rpm=60, burst=5)
        assert limiter.remaining("new-key") == pytest.approx(5.0, abs=0.1)

    def test_remaining_decreases_after_check(self):
        limiter = _limiter(rpm=60, burst=5)
        limiter.check("ip")
        assert limiter.remaining("ip") < 5.0

    def test_remaining_zero_when_exhausted(self):
        limiter = _limiter(rpm=60, burst=2)
        limiter.check("ip")
        limiter.check("ip")
        assert limiter.remaining("ip") < 1.0


class TestReset:
    def test_reset_restores_full_bucket(self):
        limiter = _limiter(rpm=60, burst=2)
        limiter.check("ip")
        limiter.check("ip")
        assert limiter.check("ip") is False

        limiter.reset("ip")
        assert limiter.check("ip") is True

    def test_reset_nonexistent_key_no_error(self):
        limiter = _limiter()
        limiter.reset("ghost")  # should not raise


class TestBucketCount:
    def test_zero_initially(self):
        assert _limiter().bucket_count() == 0

    def test_increments_on_new_key(self):
        limiter = _limiter()
        limiter.check("a")
        limiter.check("b")
        assert limiter.bucket_count() == 2

    def test_same_key_counted_once(self):
        limiter = _limiter()
        limiter.check("a")
        limiter.check("a")
        assert limiter.bucket_count() == 1
