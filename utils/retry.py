"""
Async retry decorator with exponential back-off + full jitter.

Usage:
    @async_retry(max_attempts=3, base_delay=1.0, exceptions=(aiohttp.ClientError,))
    async def call_api(...):
        ...

Design:
- Full jitter (sleep = random(0, cap)) reduces thundering-herd on 429s.
- Re-raises the last exception after all attempts are exhausted.
- Logs each retry at WARNING level for observability.
"""

from __future__ import annotations

import asyncio
import functools
import random
from typing import Callable, Tuple, Type

from core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_EXCEPTIONS = (Exception,)


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = _DEFAULT_EXCEPTIONS,
    on_retry: Callable | None = None,
) -> Callable:
    """
    Decorator factory that wraps an async function with retry logic.

    Args:
        max_attempts: Total number of attempts (including the first).
        base_delay:   Initial sleep duration in seconds.
        max_delay:    Upper bound for computed sleep (seconds).
        exceptions:   Tuple of exception types that trigger a retry.
        on_retry:     Optional async callable(attempt, exc) called before each retry.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error(
                            "[%s] All %d attempts failed. Last error: %s",
                            fn.__name__,
                            max_attempts,
                            exc,
                        )
                        raise

                    # Full jitter: sleep = random(0, min(cap, base * 2^attempt))
                    cap = min(max_delay, base_delay * (2 ** attempt))
                    sleep = random.uniform(0, cap)
                    logger.warning(
                        "[%s] Attempt %d/%d failed (%s). Retrying in %.2fs.",
                        fn.__name__,
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        sleep,
                    )
                    if on_retry:
                        await on_retry(attempt, exc)
                    await asyncio.sleep(sleep)

            raise last_exc  # unreachable but satisfies type checkers

        return wrapper

    return decorator