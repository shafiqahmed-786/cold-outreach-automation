"""
Unit tests for utils/retry.py.

Tests verify:
- Successful call on first attempt returns immediately.
- Failed call retries up to max_attempts, then re-raises.
- Correct number of invocations occurs.
- Only specified exception types trigger a retry.
- on_retry callback is invoked correctly.
"""

import asyncio
import pytest

from utils.retry import async_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _CountedError(Exception):
    pass

class _OtherError(Exception):
    pass


def _make_flaky(fail_times: int, error_cls=_CountedError):
    """Returns an async function that raises `fail_times` times, then succeeds."""
    calls = {"n": 0}

    @async_retry(
        max_attempts=fail_times + 1,
        base_delay=0.0,  # no sleep in tests
        exceptions=(_CountedError,),
    )
    async def fn():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise error_cls("boom")
        return "ok"

    return fn, calls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_first_attempt():
    """Function succeeds first try – should not retry."""
    @async_retry(max_attempts=3, base_delay=0.0)
    async def fn():
        return 42

    result = await fn()
    assert result == 42


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    """Fails twice, succeeds on 3rd attempt."""
    fn, calls = _make_flaky(fail_times=2)
    result = await fn()
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_raises_after_all_attempts_exhausted():
    """Fails every attempt – should raise after max_attempts."""
    @async_retry(max_attempts=3, base_delay=0.0, exceptions=(_CountedError,))
    async def always_fails():
        raise _CountedError("always")

    with pytest.raises(_CountedError):
        await always_fails()


@pytest.mark.asyncio
async def test_correct_attempt_count_on_exhaustion():
    """Verify the function is called exactly max_attempts times."""
    call_count = {"n": 0}

    @async_retry(max_attempts=4, base_delay=0.0, exceptions=(_CountedError,))
    async def fn():
        call_count["n"] += 1
        raise _CountedError("always")

    with pytest.raises(_CountedError):
        await fn()

    assert call_count["n"] == 4


@pytest.mark.asyncio
async def test_non_matching_exception_not_retried():
    """An exception NOT in the `exceptions` tuple should propagate immediately."""
    call_count = {"n": 0}

    @async_retry(max_attempts=3, base_delay=0.0, exceptions=(_CountedError,))
    async def fn():
        call_count["n"] += 1
        raise _OtherError("unexpected")

    with pytest.raises(_OtherError):
        await fn()

    # Should have been called only once – no retry for unregistered exception.
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_on_retry_callback_invoked():
    """on_retry callback must be called once per retry (not on first attempt)."""
    retry_log: list[tuple[int, Exception]] = []

    async def record(attempt: int, exc: Exception):
        retry_log.append((attempt, exc))

    @async_retry(
        max_attempts=3,
        base_delay=0.0,
        exceptions=(_CountedError,),
        on_retry=record,
    )
    async def always_fails():
        raise _CountedError("boom")

    with pytest.raises(_CountedError):
        await always_fails()

    # 3 attempts → 2 retries → 2 callback calls (not called after final attempt)
    assert len(retry_log) == 2
    assert retry_log[0][0] == 1   # after attempt 1
    assert retry_log[1][0] == 2   # after attempt 2