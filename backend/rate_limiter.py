"""Rate limiter module (NOT USED in simplified hackathon version).

This module implements per-key sliding-window rate limiting. It was removed
from the active codebase per the hackathon "Out of Scope" requirements.

To re-enable rate limiting in production:
1. Import `check_rate_limit` from this module in `backend/main.py`
2. Add rate limit checks to endpoints that need protection
3. Set `FIN_RATE_LIMIT_PER_MINUTE` environment variable (default: 60)

Original description:
Simple per-key sliding-window rate limiter. In-process only - correct
for a single instance; behind multiple replicas each instance enforces its
own limit independently (an acceptable degradation, not a security hole,
since the cap still bounds worst-case load per instance). For strict
global limits across replicas, back this with Redis (INCR + EXPIRE) instead
of the in-memory dict below - the check_rate_limit() call site doesn't need
to change.
"""
import threading
import time
from collections import defaultdict, deque

from backend.config import RATE_LIMIT_PER_MINUTE

_WINDOW_SECONDS = 60
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def check_rate_limit(key: str) -> tuple[bool, int]:
    """Returns (allowed, remaining). Records the hit if allowed."""
    now = time.monotonic()
    with _lock:
        window = _hits[key]
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            return False, 0
        window.append(now)
        return True, RATE_LIMIT_PER_MINUTE - len(window)
