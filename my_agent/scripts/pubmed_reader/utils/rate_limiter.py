#!/usr/bin/env python3
"""
Rate limiter for PubMed Reader skill.
Ensures compliance with NCBI E-utilities rate limits.
"""

import time
import threading
import os
from typing import Optional
from collections import deque
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket rate limiter for API requests.

    NCBI E-utilities limits:
    - Without API key: 3 requests/second
    - With API key: 10 requests/second
    - Large jobs: Should run 9 PM - 5 AM ET weekdays or weekends
    """

    # Default rate limits
    DEFAULT_RATE_NO_KEY = 3  # requests per second
    DEFAULT_RATE_WITH_KEY = 10  # requests per second

    def __init__(self, requests_per_second: Optional[float] = None):
        """
        Initialize rate limiter.

        Args:
            requests_per_second: Max requests per second (auto-detects if None)
        """
        if requests_per_second is None:
            # Auto-detect based on API key presence
            if os.environ.get('NCBI_API_KEY'):
                self.requests_per_second = self.DEFAULT_RATE_WITH_KEY
            else:
                self.requests_per_second = self.DEFAULT_RATE_NO_KEY
        else:
            self.requests_per_second = requests_per_second

        self.min_interval = 1.0 / self.requests_per_second
        self._last_request = 0.0
        self._lock = threading.Lock()

        # Track request history for monitoring
        self._request_times: deque = deque(maxlen=100)

        # Statistics
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0

        logger.info(f"Rate limiter initialized: {self.requests_per_second} req/sec")

    def wait(self) -> float:
        """
        Wait if needed to respect rate limit.

        Returns:
            Time waited in seconds (0 if no wait needed)
        """
        with self._lock:
            now = time.time()
            time_since_last = now - self._last_request

            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                time.sleep(wait_time)
                self._total_waits += 1
                self._total_wait_time += wait_time
            else:
                wait_time = 0.0

            self._last_request = time.time()
            self._request_times.append(self._last_request)
            self._total_requests += 1

            return wait_time

    def throttle(self):
        """Alias for wait() - wait if needed to respect rate limit."""
        return self.wait()

    def get_current_rate(self) -> float:
        """
        Calculate current request rate over last minute.

        Returns:
            Requests per second over the last minute
        """
        now = time.time()
        cutoff = now - 60  # Last 60 seconds

        recent = sum(1 for t in self._request_times if t > cutoff)
        return recent / 60.0

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dict with request and wait statistics
        """
        return {
            'total_requests': self._total_requests,
            'total_waits': self._total_waits,
            'total_wait_time': round(self._total_wait_time, 2),
            'avg_wait_time': round(self._total_wait_time / max(self._total_waits, 1), 3),
            'current_rate': round(self.get_current_rate(), 2),
            'max_rate': self.requests_per_second
        }

    def reset_stats(self):
        """Reset statistics."""
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0
        self._request_times.clear()


class AdaptiveRateLimiter(RateLimiter):
    """
    Rate limiter that adapts based on API responses.

    Reduces rate on errors, increases when successful.
    """

    def __init__(self, requests_per_second: Optional[float] = None):
        """Initialize adaptive rate limiter."""
        super().__init__(requests_per_second)

        self._base_rate = self.requests_per_second
        self._min_rate = 0.5  # Minimum 0.5 req/sec
        self._max_rate = self.requests_per_second

        self._consecutive_errors = 0
        self._consecutive_success = 0

    def on_success(self):
        """Call after successful request."""
        self._consecutive_errors = 0
        self._consecutive_success += 1

        # Gradually increase rate after sustained success
        if self._consecutive_success >= 10:
            new_rate = min(self.requests_per_second * 1.1, self._max_rate)
            if new_rate > self.requests_per_second:
                self.requests_per_second = new_rate
                self.min_interval = 1.0 / new_rate
                logger.debug(f"Rate increased to {new_rate:.1f} req/sec")
            self._consecutive_success = 0

    def on_error(self, is_rate_limit_error: bool = False):
        """
        Call after failed request.

        Args:
            is_rate_limit_error: True if error was due to rate limiting
        """
        self._consecutive_success = 0
        self._consecutive_errors += 1

        if is_rate_limit_error:
            # Aggressive reduction for rate limit errors
            new_rate = max(self.requests_per_second * 0.5, self._min_rate)
        else:
            # Gradual reduction for other errors
            new_rate = max(self.requests_per_second * 0.9, self._min_rate)

        if new_rate < self.requests_per_second:
            self.requests_per_second = new_rate
            self.min_interval = 1.0 / new_rate
            logger.warning(f"Rate reduced to {new_rate:.1f} req/sec")

    def reset_rate(self):
        """Reset to base rate."""
        self.requests_per_second = self._base_rate
        self.min_interval = 1.0 / self._base_rate
        self._consecutive_errors = 0
        self._consecutive_success = 0


# =============================================================================
# Global Rate Limiter Instance
# =============================================================================

_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = AdaptiveRateLimiter()
    return _rate_limiter


def throttle() -> float:
    """
    Global throttle function - wait if needed.

    Returns:
        Time waited in seconds
    """
    return get_rate_limiter().wait()


def report_success():
    """Report successful request to adaptive rate limiter."""
    limiter = get_rate_limiter()
    if isinstance(limiter, AdaptiveRateLimiter):
        limiter.on_success()


def report_error(is_rate_limit: bool = False):
    """
    Report failed request to adaptive rate limiter.

    Args:
        is_rate_limit: True if error was due to rate limiting
    """
    limiter = get_rate_limiter()
    if isinstance(limiter, AdaptiveRateLimiter):
        limiter.on_error(is_rate_limit)


# =============================================================================
# Main (for testing)
# =============================================================================

def main():
    """Test rate limiter."""
    print("Testing Rate Limiter...\n")

    # Test basic rate limiting
    print("1. Testing basic rate limiting (3 req/sec):")
    limiter = RateLimiter(requests_per_second=3)

    start = time.time()
    for i in range(6):
        wait = limiter.wait()
        print(f"   Request {i+1}: waited {wait:.3f}s")

    elapsed = time.time() - start
    print(f"   Total time for 6 requests: {elapsed:.2f}s (expected ~2s)")

    # Test statistics
    print("\n2. Testing statistics:")
    stats = limiter.get_stats()
    print(f"   Stats: {stats}")

    # Test adaptive rate limiter
    print("\n3. Testing adaptive rate limiter:")
    adaptive = AdaptiveRateLimiter(requests_per_second=5)

    print(f"   Initial rate: {adaptive.requests_per_second} req/sec")

    # Simulate rate limit errors
    for _ in range(3):
        adaptive.on_error(is_rate_limit_error=True)
    print(f"   After 3 rate limit errors: {adaptive.requests_per_second:.1f} req/sec")

    # Simulate recovery
    for _ in range(15):
        adaptive.on_success()
    print(f"   After 15 successes: {adaptive.requests_per_second:.1f} req/sec")

    print("\n All rate limiter tests passed!")


if __name__ == "__main__":
    main()
